"""
Copyright 2024 Arun Persaud.

This file is part of TagOrganizer.

TagOrganizer is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or (at
your option) any later version.

TagOrganizer is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with TagOrganizer. If not, see <https://www.gnu.org/licenses/>.

"""

import logging
import os
from pathlib import Path

from sqlmodel import SQLModel, create_engine, select, Session, func, delete
from sqlalchemy.orm import selectinload
import sqlalchemy as sa
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from . import paths
from .models import Tag, Item, ItemTagLink, ItemParentLink
from .scope import Scope
from .widgets.tag_bar import Condition, Filters

logger = logging.getLogger(__name__)

# SQLite caps bound variables at 32766 (measured, sqlite 3.53.1): a prepared
# statement with 40000 parameters raises OperationalError. Chunking helps only
# for separate statements (each with its own parameter set), not for multiple
# IN clauses in one statement. get_items_by_ids uses chunking correctly; the
# id filter uses a temp table to materialise ids out of the statement entirely.
ID_FILTER_CHUNK = 30_000
_ID_TABLE = "tagorganizer_selected_ids"


def chunk_ids(item_ids: list[int], size: int = ID_FILTER_CHUNK) -> list[list[int]]:
    """Split ids into groups small enough to bind in separate statements.

    Each chunk goes into its own query, so bound variables don't accumulate
    across statements. An empty input yields a single empty chunk, so the
    caller still builds a clause - one that matches nothing, which is what an
    empty selection means. Used by get_items_by_ids, the tagging queries, and
    the cross-profile move, all of which bind one variable per id.
    """
    if not item_ids:
        return [[]]
    return [item_ids[i : i + size] for i in range(0, len(item_ids), size)]


def _materialise_ids(session, item_ids: list[int], table: str = _ID_TABLE) -> None:
    """Put the selected ids in a temp table instead of in the statement.

    SQLite's 32766-variable cap is per prepared statement, not per IN clause,
    so splitting a large selection into OR'd IN clauses does not help - every
    parameter still lands in the same statement. A temp table keeps the id set
    out of the statement entirely, which also lets ORDER BY and LIMIT stay in
    SQL rather than being redone in Python.

    Dropped and recreated each time: connections are pooled, so a table left
    behind by an earlier query on the same connection would be reused.
    """
    conn = session.connection()
    conn.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
    conn.exec_driver_sql(f"CREATE TEMP TABLE {table} (id INTEGER PRIMARY KEY)")
    if item_ids:
        conn.exec_driver_sql(
            f"INSERT INTO {table} (id) VALUES (?)",
            [(i,) for i in item_ids],
        )


def _inside_dir(directory) -> sa.ColumnElement:
    """Whether an item's file sits beneath this directory.

    Compares a literal prefix rather than using LIKE. LIKE treats "_" and "%"
    in a directory name as wildcards, and SQLite's LIKE folds ASCII case
    whatever the filesystem does. The prefix ends in a separator so that
    /photos-old is not counted as inside /photos. Case folds only where the
    directory's filesystem ignores case, as everywhere else in the app.
    """
    prefix = str(directory).rstrip(os.sep) + os.sep
    head = sa.func.substr(Item.uri, 1, len(prefix))
    if paths.is_case_insensitive(Path(directory)):
        return sa.func.lower(head) == prefix.lower()
    return head == prefix


def _restrict(query, session, scope: Scope):
    """Narrow a query to a scope's items.

    The ids go into a temp table rather than an IN clause: SQLite's
    32766-variable cap is per prepared statement, so a large selection cannot
    be split into OR'd IN clauses to get under it.
    """
    if not scope.is_selection:
        return query
    _materialise_ids(session, list(scope.item_ids))
    return query.where(Item.id.in_(sa.text(f"SELECT id FROM {_ID_TABLE}")))


def get_items_by_ids(item_ids: list[int]) -> list[Item]:
    """Fetch items by id, in whatever order the database returns them.

    Callers hold ids rather than ORM objects now, and objects kept across
    sessions go stale, so anything needing real Items fetches them here.
    """
    if not item_ids:
        return []
    with new_session() as session:
        found = []
        for chunk in chunk_ids(item_ids):
            found.extend(session.exec(select(Item).where(Item.id.in_(chunk))).all())
        return found


engine = None


def set_engine(db_dir: str):
    """Point this module at a profile's database.

    Disposes the previous engine first. Without that, every profile switch
    left the old engine behind with a pooled connection still holding its
    database file open, and the Profiles menu can switch any number of times
    in one session.
    """
    global engine
    if engine is not None:
        engine.dispose()
    engine = create_engine(
        f"sqlite:///{db_dir}",
        # Tasks run on a single dedicated worker thread, and the pool may hand
        # that thread a connection first opened on the GUI thread. Safe ONLY
        # because exactly one worker exists - revisit if a pool is introduced.
        connect_args={"check_same_thread": False},
    )


def new_session() -> Session:
    """Open a session on the configured database.

    Every query below goes through here, so there is one place that knows how
    sessions are made and one clear error when no profile has been loaded yet
    rather than an AttributeError on None deep inside a query.
    """
    if engine is None:
        raise RuntimeError(
            "No database configured - call set_engine() before querying."
        )
    return Session(engine)


def create_db():
    SQLModel.metadata.create_all(engine)


def get_tag(name):
    """Look a tag up by name, ignoring case and surrounding space.

    Names are stored exactly as the user typed them, so the lookup has to fold
    case - otherwise entering "iphone" would create a second tag beside an
    existing "iPhone". SQLite's lower() only folds ASCII, so non-ASCII names
    remain case-sensitive.
    """
    with new_session() as session:
        return session.exec(
            select(Tag).where(func.lower(Tag.name) == name.strip().lower())
        ).first()


def get_tag_by_id(id):
    with new_session() as session:
        return session.exec(select(Tag).where(Tag.id == id)).first()


def add_tag(name):
    name = name.strip()
    with new_session() as session:
        existing_tag = session.exec(
            select(Tag).where(func.lower(Tag.name) == name.lower())
        ).first()
        if existing_tag:
            logger.debug("tag %r already exists with id %s", name, existing_tag.id)
            return existing_tag.id

        new_tag = Tag(name=name)
        session.add(new_tag)
        try:
            session.commit()
        except IntegrityError:
            # Someone created the tag between the lookup above and this
            # insert. Tagging happens from the GUI thread and from plugins on
            # the worker at the same time, so this is a real interleaving, not
            # a theoretical one. The other writer's tag is just as good as
            # ours would have been.
            session.rollback()
            logger.debug("tag %r was created concurrently; using theirs", name)
            existing_tag = session.exec(
                select(Tag).where(func.lower(Tag.name) == name.lower())
            ).first()
            if existing_tag is None:
                raise
            return existing_tag.id
        return new_tag.id


def _subtree_tag_ids(session, roots: set[int]) -> set[int]:
    """The roots and every tag beneath them, at any depth.

    Each tag is visited once. A hierarchy can contain a cycle - a database
    written before set_parent_tag refused them may hold one - and walking it
    without a visited set would recurse or loop forever.
    """
    found = set(roots)
    frontier = list(roots)
    while frontier:
        children = []
        for chunk in chunk_ids(frontier):
            children.extend(
                session.exec(select(Tag.id).where(Tag.parent_id.in_(chunk))).all()
            )
        frontier = [child for child in set(children) if child not in found]
        found.update(frontier)
    return found


def _descendant_tag_ids(session, tag_id: int) -> set[int]:
    """Every tag beneath this one, at any depth."""
    return _subtree_tag_ids(session, {tag_id}) - {tag_id}


def _ancestor_chain(session, tag_id: int) -> set[int]:
    """This tag and every tag above it, following parents up to the top.

    Stops at a tag it has already passed, for the same reason as
    _subtree_tag_ids: a stored cycle must not hang the walk.
    """
    found = set()
    current = tag_id
    while current is not None and current not in found:
        found.add(current)
        current = session.exec(select(Tag.parent_id).where(Tag.id == current)).first()
    return found


def rename_tag(tag_id: int, new_name: str) -> None:
    """Give a tag a different name.

    Refuses a name another tag already holds, compared case-insensitively:
    get_tag folds case, so two tags differing only in capitalisation could not
    be told apart afterwards. That situation is a merge, and saying so is more
    useful than silently making one.
    """
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("a tag needs a name")

    with new_session() as session:
        tag = session.get(Tag, tag_id)
        if tag is None:
            raise ValueError(f"no tag with id {tag_id}")

        clash = session.exec(
            select(Tag).where(
                func.lower(Tag.name) == new_name.lower(), Tag.id != tag_id
            )
        ).first()
        if clash is not None:
            raise ValueError(
                f"a tag named {clash.name!r} already exists; merge them instead"
            )

        tag.name = new_name
        session.add(tag)
        session.commit()


def merge_tags(source_id: int, target_id: int) -> tuple[int, int]:
    """Fold one tag into another, returning (links moved, links dropped).

    The source disappears. Its photos gain the target, its children are
    reparented onto the target, and it is deleted.

    Two cases would otherwise corrupt data. A photo already carrying both tags
    cannot simply have its link repointed - ItemTagLink has a composite primary
    key, so that link is redundant and is dropped instead. And merging a tag
    into one of its own descendants would, once the children are reparented,
    make a tag its own ancestor; that is refused rather than left to loop.
    """
    if source_id == target_id:
        raise ValueError("cannot merge a tag into itself")

    with new_session() as session:
        source = session.get(Tag, source_id)
        target = session.get(Tag, target_id)
        if source is None or target is None:
            raise ValueError("both tags must exist to merge them")

        if target_id in _descendant_tag_ids(session, source_id):
            raise ValueError(
                f"cannot merge {source.name!r} into its own descendant {target.name!r}"
            )

        already = set(
            session.exec(
                select(ItemTagLink.item_id).where(ItemTagLink.tag_id == target_id)
            ).all()
        )
        links = session.exec(
            select(ItemTagLink).where(ItemTagLink.tag_id == source_id)
        ).all()

        moved = dropped = 0
        for link in links:
            item_id = link.item_id
            session.exec(
                delete(ItemTagLink).where(
                    ItemTagLink.item_id == item_id, ItemTagLink.tag_id == source_id
                )
            )
            if item_id in already:
                dropped += 1
            else:
                session.add(ItemTagLink(item_id=item_id, tag_id=target_id))
                moved += 1

        for child in session.exec(select(Tag).where(Tag.parent_id == source_id)).all():
            child.parent_id = target_id
            session.add(child)

        # Push the reparenting to the database before removing the source.
        # Deleting a Tag makes SQLAlchemy resolve its `children` relationship to
        # process the cascade, and it would do that against the rows as they
        # still stand - undoing the reassignment above and orphaning the
        # children. Flushing first means the source genuinely has no children
        # left by the time it is deleted.
        session.flush()

        session.delete(session.get(Tag, source_id))
        session.commit()
        return moved, dropped


# A statement binds its item ids and its tag ids together, so each chunk has
# to leave room for both under SQLite's 32766-variable cap.
_LINK_CHUNK = 15_000


def remove_tags(items: list[Item], tags: list[Tag]) -> int:
    """Take tags off photos, returning how many links went.

    The tags themselves survive - this is for fixing a mistagged photo, which
    until now could only be done by deleting the tag from the whole library.
    A link that was not there is not an error. A large selection is worked in
    chunks, since one IN clause per id list would exceed the variable cap.
    """
    item_ids = [item.id for item in items if item.id is not None]
    tag_ids = [tag.id for tag in tags if tag.id is not None]
    if not item_ids or not tag_ids:
        return 0

    removed = 0
    with new_session() as session:
        for item_chunk in chunk_ids(item_ids, size=_LINK_CHUNK):
            for tag_chunk in chunk_ids(tag_ids, size=_LINK_CHUNK):
                where = (
                    ItemTagLink.item_id.in_(item_chunk),
                    ItemTagLink.tag_id.in_(tag_chunk),
                )
                removed += session.exec(
                    select(func.count()).select_from(ItemTagLink).where(*where)
                ).one()
                session.exec(delete(ItemTagLink).where(*where))
        session.commit()
    return removed


def delete_tag(id: int):
    with new_session() as session:
        tag = session.get(Tag, id)
        if tag:
            if tag.children:
                logger.warning("cannot delete tag %s: it still has subtags", id)
                return
            # unclear if this is needed or can be optimized by setting
            # other flags in the model
            session.exec(delete(ItemTagLink).where(ItemTagLink.tag_id == id))
            session.delete(tag)
            session.commit()


def delete_item(id: int):
    with new_session() as session:
        item = session.get(Item, id)
        if item:
            session.exec(delete(ItemTagLink).where(ItemTagLink.item_id == id))
            # Lineage links point at items from both ends, so a deleted photo
            # would otherwise leave links behind and the derived-from indicator
            # would claim a parent that no longer exists.
            session.exec(delete(ItemParentLink).where(ItemParentLink.child_id == id))
            session.exec(delete(ItemParentLink).where(ItemParentLink.parent_id == id))
            session.delete(item)
            session.commit()


def get_parent_ids(child_id: int) -> list[int]:
    """The items this one was derived from."""
    with new_session() as session:
        return list(
            session.exec(
                select(ItemParentLink.parent_id).where(
                    ItemParentLink.child_id == child_id
                )
            ).all()
        )


def get_child_ids(parent_id: int) -> list[int]:
    """The items derived from this one."""
    with new_session() as session:
        return list(
            session.exec(
                select(ItemParentLink.child_id).where(
                    ItemParentLink.parent_id == parent_id
                )
            ).all()
        )


def _ancestor_ids(session, item_id: int) -> set[int]:
    """Every item this one descends from, at any depth."""
    found, stack = set(), [item_id]
    while stack:
        current = stack.pop()
        for parent_id in session.exec(
            select(ItemParentLink.parent_id).where(ItemParentLink.child_id == current)
        ).all():
            if parent_id not in found:
                found.add(parent_id)
                stack.append(parent_id)
    return found


def set_parents(child_id: int, parent_ids: list[int]) -> None:
    """Record what an item was derived from, replacing any previous lineage.

    Refuses to make an item its own ancestor. Lineage exists to lead back to an
    original, so a loop would make "where did this come from" unanswerable and
    would hang any walk up the chain.
    """
    wanted = list(dict.fromkeys(parent_ids))

    if child_id in wanted:
        raise ValueError("an item cannot be derived from itself")

    with new_session() as session:
        for parent_id in wanted:
            if child_id == parent_id or child_id in _ancestor_ids(session, parent_id):
                raise ValueError(
                    "cannot record that lineage: it would make an item its own ancestor"
                )

        session.exec(delete(ItemParentLink).where(ItemParentLink.child_id == child_id))
        for parent_id in wanted:
            session.add(ItemParentLink(child_id=child_id, parent_id=parent_id))
        session.commit()


def get_items_with_parents(item_ids: list[int]) -> set[int]:
    """Which of these items were derived from something.

    Asked once per grid page rather than once per tile: the indicator needs it
    for every visible photo and a query each would be 25 round trips a page.
    """
    if not item_ids:
        return set()
    with new_session() as session:
        return set(
            session.exec(
                select(ItemParentLink.child_id).where(
                    ItemParentLink.child_id.in_(item_ids)
                )
            ).all()
        )


def get_parent_summary(item_ids: list[int]) -> dict[int, list[str]]:
    """The source photos' uris for each of these items that has any.

    One query per grid page, joined rather than looked up per tile, so the
    tooltip can name what a photo came from instead of only saying that it
    came from something. Items without sources are absent rather than mapped
    to an empty list, so the caller can test membership directly.
    """
    if not item_ids:
        return {}
    with new_session() as session:
        rows = session.exec(
            select(ItemParentLink.child_id, Item.uri)
            .join(Item, Item.id == ItemParentLink.parent_id)
            .where(ItemParentLink.child_id.in_(item_ids))
        ).all()
    summary: dict[int, list[str]] = {}
    for child_id, uri in rows:
        summary.setdefault(child_id, []).append(uri)
    return summary


def check_item_in_db(uri: str):
    with new_session() as session:
        query = select(Item).where(Item.uri == uri)
        result = session.exec(query).first()
        if result is None:
            return
        else:
            return result.id


def get_all_tags():
    with new_session() as session:
        results = session.exec(select(Tag))
        return results.all()


def _store_parent(child_id: int, parent_id: int | None) -> None:
    """Make parent_id the parent of child_id, or top-level when it is None.

    Refuses a parent that is the child itself or one of its descendants: the
    tag would then be its own ancestor, and every walk up or down the hierarchy
    would loop. A missing tag is logged and left alone, as it always was.
    """
    with new_session() as session:
        child = session.get(Tag, child_id)
        if child is None or (
            parent_id is not None and session.get(Tag, parent_id) is None
        ):
            logger.error(
                "could not set parent tag: child_id=%s parent_id=%s",
                child_id,
                parent_id,
            )
            return
        if parent_id is not None and child_id in _ancestor_chain(session, parent_id):
            raise ValueError(
                f"tag {child_id} cannot go under tag {parent_id}: "
                "that would make it its own ancestor"
            )
        child.parent_id = parent_id
        session.add(child)
        session.commit()


def set_parent_tag(child: Tag, parent: Tag | None) -> None:
    """Place a tag under another, or at the top level when parent is None.

    Raises ValueError for a placement that would make the tag its own ancestor.
    """
    if child is None:
        logger.error("set_parent_tag called without a child")
        return
    _store_parent(child.id, parent.id if parent is not None else None)


def set_parent_tag_by_id(child_id: int, parent_id: int | None) -> None:
    """Id form of set_parent_tag; the same cycle refusal applies."""
    _store_parent(child_id, parent_id)


def add_images(files):
    """Add multiple images to the database in a single session.

    Pre-loads existing URIs to avoid nested session calls. Skips duplicates,
    including a path repeated within `files`.
    """
    with new_session() as session:
        # Pre-load all existing URIs in a single query
        existing_uris = set(session.exec(select(Item.uri)).all())

        for f in files:
            f_str = str(f)
            if f_str in existing_uris:
                logger.debug("item %s already in the database", f)
                continue
            tmp = Item(uri=f_str)
            session.add(tmp)
            # also guard against the same path appearing twice in `files`:
            # add_directory globs both "*.jpg" and "*.JPG", which match the
            # same file on case-insensitive filesystems.
            existing_uris.add(f_str)
        session.commit()


def add_image(filename):
    with new_session() as session:
        if item_id := check_item_in_db(filename):
            logger.debug("item %s already in the database", filename)
            return item_id
        tmp = Item(uri=str(filename))
        session.add(tmp)
        session.commit()
        return tmp.id


def get_items_without_date(scope: Scope = None) -> list[Item]:
    with new_session() as session:
        query = select(Item).where(Item.date == sa.null())
        query = _restrict(query, session, scope or Scope.LIBRARY)
        return session.exec(query).all()


def get_items_without_location(scope: Scope = None) -> list[Item]:
    """Items missing either coordinate.

    An item with only one coordinate cannot be placed on the map, and
    filter_query's no_gps filter tests latitude, so both halves have to count.
    """
    with new_session() as session:
        query = select(Item).where(
            or_(Item.longitude == sa.null(), Item.latitude == sa.null())
        )
        query = _restrict(query, session, scope or Scope.LIBRARY)
        return session.exec(query).all()


def get_items_under_no_date() -> list[Item]:
    """Items whose file currently sits in a 'no-date' directory.

    task_move_files parks undated files there, and this is what finds them again
    once a date has been filled in.
    """
    with new_session() as session:
        statement = select(Item).where(
            or_(
                Item.uri.contains("/no-date/"),
                Item.uri.contains("\\no-date\\"),
            )
        )
        results = session.exec(statement)
        return results.all()


def get_all_items_with_location():
    with new_session() as session:
        statement = select(Item).where(Item.longitude != sa.null())
        results = session.exec(statement)
        return results.all()


def get_all_items(scope: Scope = None) -> list[Item]:
    """Every item in the database.

    Used by maintenance tasks that have to consider the whole library and then
    filter in Python - matching a file suffix is clumsy in SQL and the other
    tasks already load their candidate set this way.
    """
    with new_session() as session:
        query = _restrict(select(Item), session, scope or Scope.LIBRARY)
        return session.exec(query).all()


def get_items_without_hashes(scope: Scope = None) -> list[Item]:
    with new_session() as session:
        query = select(Item)
        conditions = [
            Item.uri_md5 == "",
            Item.data_xxhash == "",
        ]
        query = query.where(or_(*conditions))
        query = _restrict(query, session, scope or Scope.LIBRARY)
        return session.exec(query).all()


def get_all_items_not_in_dir(directories: list[Path], suffix: list[str]):
    with new_session() as session:
        all_suffixes = []
        for e in suffix:
            all_suffixes.append(e.lower())
            all_suffixes.append(e.upper())

        query = select(Item)

        for directory in set(directories):
            query = query.where(sa.not_(_inside_dir(directory)))

        conditions = [Item.uri.endswith(ext) for ext in all_suffixes]
        query = query.where(or_(*conditions))

        items = session.exec(query).all()
        return items


def update_items_in_db(items: list[Item]) -> None:
    """Persist changes to items the caller already holds.

    expire_on_commit=False so the caller's objects stay usable afterwards. The
    default expires every attribute on commit, and the next attribute access
    then tries to reload through a session that has already closed - which
    raises DetachedInstanceError. The existing tasks never happened to touch an
    item again after saving it, but a plugin reasonably would.
    """
    with Session(engine, expire_on_commit=False) as session:
        for i in items:
            session.add(i)
        session.commit()


def get_all_tag_ids(tag_names: list[str]) -> list[int]:
    """Fetch all tag IDs including children for given tag names."""
    with new_session() as session:
        # Names are stored exactly as the user typed them, so any lookup that
        # compares them literally will miss, and tag filtering fails silently
        # rather than loudly — the user just sees no photos.
        ids = session.exec(
            select(Tag.id).where(
                func.lower(Tag.name).in_([n.strip().lower() for n in tag_names])
            )
        ).all()
        return list(_subtree_tag_ids(session, set(ids)))


def condition_expression(
    condition: Condition, session: Session, id_table: str = _ID_TABLE
):
    """The boolean expression for a single filter chip.

    The same logic the flat branches of filter_query use, pulled out so chips
    can be composed with or_() instead of only applied one after another.

    An id-set chip materialises into id_table. Each one in a query needs its
    own table, or the second overwrites the first before the statement runs.
    """
    kind, value = condition.kind, condition.value

    if kind == "tag":
        tag_ids = get_all_tag_ids([value])
        subquery = (
            select(ItemTagLink.item_id)
            .where(ItemTagLink.tag_id.in_(tag_ids))
            .subquery()
        )
        return Item.id.in_(select(subquery.c.item_id))

    if kind == "start_date":
        return Item.date >= value
    if kind == "end_date":
        return Item.date <= value

    if kind == "area":
        return sa.and_(
            Item.longitude >= value["min_longitude"],
            Item.longitude <= value["max_longitude"],
            Item.latitude >= value["min_latitude"],
            Item.latitude <= value["max_latitude"],
        )

    if kind == "no_time":
        return Item.date == sa.null()
    if kind == "no_gps":
        return Item.latitude == sa.null()

    if kind == "wrong_dir":
        return sa.and_(*[sa.not_(_inside_dir(d)) for d in value])

    if kind == "item_ids":
        _materialise_ids(session, value, id_table)
        return Item.id.in_(sa.select(sa.column("id")).select_from(sa.table(id_table)))

    raise ValueError(f"unknown filter condition kind: {kind!r}")


def filter_query(query, filter: Filters, session: Session):
    # Filter by date range
    if filter.start_date:
        query = query.where(Item.date >= filter.start_date)
    if filter.end_date:
        # Exclusive. The tag bar labels this bound "<" and the timeline passes the
        # day after a dragged span, so a photo at midnight of that day is not
        # part of the span.
        query = query.where(Item.date < filter.end_date)

    # Filter by geographical bounding box
    if filter.min_longitude is not None:
        query = query.where(Item.longitude >= filter.min_longitude)
    if filter.max_longitude is not None:
        query = query.where(Item.longitude <= filter.max_longitude)
    if filter.min_latitude is not None:
        query = query.where(Item.latitude >= filter.min_latitude)
    if filter.max_latitude is not None:
        query = query.where(Item.latitude <= filter.max_latitude)

    # Filter by tags
    if filter.tags:
        # Build one subquery per requested tag to check for that tag or its descendants.
        # This correctly handles items tagged with both parent and child tags.
        # Each subquery checks: does this item have at least one link to this tag's hierarchy?
        # We AND them together so multi-tag filters use AND semantics.
        for tag_name in filter.tags:
            tag_ids = get_all_tag_ids([tag_name])
            subquery = (
                select(ItemTagLink.item_id)
                .where(ItemTagLink.tag_id.in_(tag_ids))
                .subquery()
            )
            query = query.where(Item.id.in_(select(subquery.c.item_id)))

    if filter.no_time:
        query = query.where(Item.date == sa.null())
    if filter.no_gps:
        query = query.where(Item.latitude == sa.null())

    if filter.wrong_dir and filter.directories:
        for directory in filter.directories:
            query = query.where(sa.not_(_inside_dir(directory)))

    # Filter by id set. Materialise ids in a temp table to avoid SQLite's
    # per-statement 32766 parameter limit. The temp table keeps ids out of
    # the statement entirely, so ORDER BY and LIMIT stay in SQL.
    if filter.item_ids is not None:
        _materialise_ids(session, filter.item_ids)
        query = query.where(
            Item.id.in_(sa.select(sa.column("id")).select_from(sa.table(_ID_TABLE)))
        )

    # Groups: each is OR'd internally, then AND'd like any other conjunct. Every
    # id-set condition gets its own temporary table: a shared one would be
    # overwritten by the next materialisation, and the query would then answer
    # about whichever set was written last.
    for group_index, group in enumerate(filter.groups):
        expressions = [
            condition_expression(c, session, f"{_ID_TABLE}_g{group_index}_{i}")
            for i, c in enumerate(group)
        ]
        if expressions:
            query = query.where(
                or_(*expressions) if len(expressions) > 1 else expressions[0]
            )

    return query


def _apply_standard_order(query):
    """Apply consistent ordering: newest dates first, then oldest, then undated.

    Uses nullslast() to explicitly place NULL dates at the end, and Item.id
    as a tiebreaker to ensure deterministic ordering between calls.
    """
    return query.order_by(Item.date.desc().nullslast(), Item.id)


def get_images(page: int = 0, filters: Filters | None = None) -> list[Item]:
    with new_session() as session:
        query = select(Item)
        if filters:
            query = filter_query(query, filters, session)

        # Sort by date in descending order, then by id for determinism
        query = _apply_standard_order(query)

        # Pagination
        query = query.offset(25 * page).limit(25)

        items = session.exec(query).all()
        return items


def get_number_of_items(filters: Filters | None = None):
    with new_session() as session:
        query = select(func.count(Item.id))
        if filters:
            query = filter_query(query, filters, session)
        return session.exec(query).one()


def get_times_and_location_from_images(filters: Filters | None = None) -> list:
    with new_session() as session:
        query = select(Item.date, Item.longitude, Item.latitude)

        if filters:
            query = filter_query(query, filters, session)

        # Same ordering as the grid: the timeline reads dates[0] and dates[-1]
        # as the span ends, so it has to agree with what the user is looking at.
        query = _apply_standard_order(query)

        items = session.exec(query).all()

        dates = []
        coords = []
        for d, lon, lat in items:
            if d is not None:
                dates.append(d)
            if (lat is not None) and (lon is not None):
                coords.append((lat, lon))

        return dates, coords


def get_locations_for_filter(
    filters: Filters | None = None,
) -> list[tuple[int, float, float]]:
    """Every located item's id and position, for the map's clustering.

    Ids are what distinguishes this from get_times_and_location_from_images: the
    map clusters in Python and has to be able to resolve a hovered cluster back
    to the photos in it. Items missing either coordinate cannot be placed and are
    dropped here rather than by the caller.
    """
    with new_session() as session:
        query = select(Item.id, Item.latitude, Item.longitude)
        if filters:
            query = filter_query(query, filters, session)
        query = query.where(Item.latitude != sa.null())
        query = query.where(Item.longitude != sa.null())
        return [(i, lat, lon) for i, lat, lon in session.exec(query).all()]


def get_current_image(number, filters: Filters | None = None):
    items = get_image_range(number, 1, filters)
    return items[0] if items else None


def get_image_range(
    start: int, count: int, filters: Filters | None = None
) -> list[Item]:
    """Return `count` items beginning at offset `start`, in display order.

    Ordering matches get_images, so an index means the same item everywhere.
    Callers that want a window of items should use this rather than calling
    get_current_image in a loop: each call opens its own session and sorts the
    whole table, so fetching eleven items one at a time costs ~100 ms at 30k
    items against ~0.2 ms for a single ranged query.
    """
    if start < 0:
        count += start
        start = 0
    if count <= 0:
        return []

    with new_session() as session:
        query = select(Item)
        if filters:
            query = filter_query(query, filters, session)

        query = _apply_standard_order(query)

        return session.exec(query.offset(start).limit(count)).all()


def get_common_tags(items: list[Item]) -> list[Tag]:
    with new_session() as session:
        # Load items and their tags, a chunk at a time for large selections
        tag_sets = []
        for chunk in chunk_ids([item.id for item in items]):
            loaded = session.exec(
                select(Item).where(Item.id.in_(chunk)).options(selectinload(Item.tags))
            ).all()
            tag_sets.extend(set(t.name for t in item.tags) for item in loaded)

        # Find the intersection of all tag sets
        if tag_sets:
            common_tags = set.intersection(*tag_sets)
        else:
            common_tags = set()

        return list(common_tags)


def set_tags(items: list[Item], tags: list[Tag]) -> None:
    with new_session() as session:
        loaded_tags = []
        for chunk in chunk_ids([tag.id for tag in tags]):
            loaded_tags.extend(session.exec(select(Tag).where(Tag.id.in_(chunk))).all())

        # A large selection is loaded a chunk at a time: one IN clause over all
        # of it would exceed SQLite's variable cap. The session still holds
        # every item until the commit below.
        for chunk in chunk_ids([item.id for item in items]):
            loaded = session.exec(
                select(Item).where(Item.id.in_(chunk)).options(selectinload(Item.tags))
            ).all()

            # Add each tag to each item if not already associated
            for item in loaded:
                for tag in loaded_tags:
                    if tag not in item.tags:
                        item.tags.append(tag)

        session.commit()


def set_tag_photo_by_ids(item_id, tag_id):
    with new_session() as session:
        existing_item = session.exec(
            select(ItemTagLink).where(
                ItemTagLink.item_id == item_id, ItemTagLink.tag_id == tag_id
            )
        ).first()
        if existing_item:
            return

        tmp = ItemTagLink(item_id=item_id, tag_id=tag_id)
        session.add(tmp)
        session.commit()
