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
from pathlib import Path

from sqlmodel import SQLModel, create_engine, select, Session, func, delete
from sqlalchemy.orm import selectinload
import sqlalchemy as sa
from sqlalchemy import or_

from .models import Tag, Item, ItemTagLink
from .widgets.tag_bar import Filters

logger = logging.getLogger(__name__)

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
    engine = create_engine(f"sqlite:///{db_dir}")


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
        session.commit()
        return new_tag.id


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
            session.delete(item)
            session.commit()


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


def set_parent_tag(child: Tag, parent: Tag):
    if child is None:
        logger.error("set_parent_tag called without a child")
    if parent is None:
        logger.error("set_parent_tag called without a parent")

    with new_session() as session:
        child.parent_id = parent.id
        session.add(child)
        session.commit()


def set_parent_tag_by_id(child_id: int, parent_id: int):
    with new_session() as session:
        child = session.get(Tag, child_id)
        parent = session.get(Tag, parent_id)
        if (not child) or (not parent):
            logger.error(
                "could not set parent tag: child_id=%s parent_id=%s",
                child_id,
                parent_id,
            )
            return
        child.parent_id = parent.id
        session.add(child)
        session.commit()


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


def get_items_without_date() -> list[Item]:
    with new_session() as session:
        statement = select(Item).where(Item.date == sa.null())
        results = session.exec(statement)
        return results.all()


def get_items_without_location() -> list[Item]:
    """Items missing either coordinate.

    An item with only one coordinate cannot be placed on the map, and
    filter_query's no_gps filter tests latitude, so both halves have to count.
    """
    with new_session() as session:
        statement = select(Item).where(
            or_(Item.longitude == sa.null(), Item.latitude == sa.null())
        )
        results = session.exec(statement)
        return results.all()


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


def get_items_without_hashes() -> list[Item]:
    with new_session() as session:
        query = select(Item)
        conditions = [
            Item.uri_md5 == "",
            Item.data_xxhash == "",
        ]
        query = query.where(or_(*conditions))
        results = session.exec(query)
        return results.all()


def get_all_items_not_in_dir(directories: list[Path], suffix: list[str]):
    with new_session() as session:
        all_suffixes = []
        for e in suffix:
            all_suffixes.append(e.lower())
            all_suffixes.append(e.upper())

        query = select(Item)

        for directory in set(directories):
            query = query.where(~Item.uri.startswith(str(directory)))

        conditions = [Item.uri.endswith(ext) for ext in all_suffixes]
        query = query.where(or_(*conditions))

        items = session.exec(query).all()
        return items


def update_items_in_db(items: list[Item]) -> None:
    with new_session() as session:
        for i in items:
            session.add(i)
        session.commit()


def get_all_tag_ids(tag_names: list[str]) -> list[int]:
    """Fetch all tag IDs including children for given tag names."""
    with new_session() as session:
        tag_ids = set()
        # Names are stored exactly as the user typed them, so any lookup that
        # compares them literally will miss, and tag filtering fails silently
        # rather than loudly — the user just sees no photos.
        tags = session.exec(
            select(Tag).where(
                func.lower(Tag.name).in_([n.strip().lower() for n in tag_names])
            )
        ).all()

        def fetch_child_tags(tag):
            tag_ids.add(tag.id)
            if tag.children is None:
                return
            for child in tag.children:
                fetch_child_tags(child)

        for tag in tags:
            fetch_child_tags(tag)

        return list(tag_ids)


def filter_query(query, filter: Filters):
    # Filter by date range
    if filter.start_date:
        query = query.where(Item.date >= filter.start_date)
    if filter.end_date:
        query = query.where(Item.date <= filter.end_date)

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
            query = query.where(~Item.uri.startswith(str(directory)))

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
            query = filter_query(query, filters)

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
            query = filter_query(query, filters)
        return session.exec(query).one()


def get_times_and_location_from_images(filters: Filters | None = None) -> list:
    with new_session() as session:
        query = select(Item.date, Item.longitude, Item.latitude)

        if filters:
            query = filter_query(query, filters)

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
            query = filter_query(query, filters)

        query = _apply_standard_order(query)

        return session.exec(query.offset(start).limit(count)).all()


def get_common_tags(items: list[Item]) -> list[Tag]:
    with new_session() as session:
        # Load items and their tags
        items = session.exec(
            select(Item)
            .where(Item.id.in_([item.id for item in items]))
            .options(selectinload(Item.tags))
        ).all()

        # Extract sets of tags for each item
        tag_sets = [set([t.name for t in item.tags]) for item in items]

        # Find the intersection of all tag sets
        if tag_sets:
            common_tags = set.intersection(*tag_sets)
        else:
            common_tags = set()

        return list(common_tags)


def set_tags(items: list[Item], tags: list[Tag]) -> None:
    with new_session() as session:
        items = session.exec(
            select(Item)
            .where(Item.id.in_([item.id for item in items]))
            .options(selectinload(Item.tags))
        ).all()

        tags = session.exec(
            select(Tag).where(Tag.id.in_([tag.id for tag in tags]))
        ).all()

        # Add each tag to each item if not already associated
        for item in items:
            for tag in tags:
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
