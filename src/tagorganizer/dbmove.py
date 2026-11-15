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

import contextlib
import logging
import os
from pathlib import Path
from dataclasses import dataclass, field

from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text, create_engine as sa_create_engine
from sqlmodel import SQLModel, Session

from .migrations import ALEMBIC_CFG, upgrade_db, stamp_db
from . import paths
from .db import chunk_ids

logger = logging.getLogger(__name__)


class TargetUnusable(Exception):
    """The target database cannot be written to safely.

    Raised before any transaction opens, so a refusal never leaves a partial
    move behind. This is the only feature in the application that can destroy
    photos; when in doubt it declines rather than proceeds.
    """


def journal_mode(path: Path) -> str:
    """The SQLite journal mode of a database file.

    Opens the database briefly to query its configured journal mode, which tells
    us whether atomic multi-database commits are guaranteed by SQLite.
    """
    path = Path(path)
    engine = sa_create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode")).fetchone()
            return result[0] if result else "delete"
    finally:
        engine.dispose()


def _stored_revision(path: Path) -> str | None:
    """The migration revision a database records, or None if it records none."""
    engine = sa_create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as conn:
            if not inspect(conn).has_table("alembic_version"):
                return None
            row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
            return row[0] if row else None
    finally:
        engine.dispose()


def _known_revisions() -> set[str]:
    """Every revision in the migration chain this build ships."""
    script = ScriptDirectory.from_config(ALEMBIC_CFG)
    return {revision.revision for revision in script.walk_revisions()}


def prepare_target(path: Path) -> None:
    """Make a target database safe to move rows into, or refuse.

    Every refusal is decided before anything is written, so a refused target is
    left exactly as it was. In order: the parent directory is reachable (an
    unmounted drive must fail here, not midway); an existing database is
    refused if it is in WAL mode, because SQLite's atomic multi-database commit
    guarantee does not hold there and the move would silently degrade to a
    non-atomic copy-then-delete; and refused if it records a migration this
    build does not know, because writing to a schema we do not understand is
    how a library gets corrupted. Only then is the database created and
    stamped at head if absent, or migrated if behind, exactly as switching to
    that profile would. Any failure in that migration is reported as
    TargetUnusable too.

    This is the only feature in the application that can destroy photos.
    """
    path = Path(path)

    # Check that the parent directory exists. An unmounted drive must fail here,
    # not midway through a transaction.
    if not path.parent.exists():
        raise TargetUnusable(
            f"Parent directory does not exist: {path.parent}\n"
            f"Target path: {path}\n"
            f"This may indicate an unmounted drive or invalid path."
        )

    is_new = not path.exists()

    if not is_new:
        # The journal mode is checked first, and before any upgrade. SQLite's
        # atomic multi-database commit guarantee applies only in rollback-journal
        # mode. WAL mode does not provide that guarantee, and the move would
        # silently degrade to a non-atomic copy-then-delete, losing photos on
        # any failure between the insert and delete.
        mode = journal_mode(path)
        if mode.lower() == "wal":
            raise TargetUnusable(
                f"Target database is in WAL (write-ahead logging) mode.\n"
                f"Target: {path}\n"
                f"Journal mode: {mode}\n\n"
                f"SQLite's atomic multi-database commit guarantee does not hold in WAL mode. "
                f"A move to this target would silently degrade to a non-atomic copy-then-delete, "
                f"which could lose photos on any failure between the insert and delete steps.\n"
                f"Please set the database to rollback-journal mode (journal_mode=delete) before "
                f"attempting the move."
            )

        # A database written by a newer build is refused rather than migrated:
        # this build cannot know what its later migrations changed.
        stored = _stored_revision(path)
        if stored is not None and stored not in _known_revisions():
            raise TargetUnusable(
                f"Target database is at migration {stored}, which this version of "
                f"TagOrganizer does not know. It was probably written by a newer "
                f"version.\n"
                f"Target: {path}\n"
                f"Update TagOrganizer, or move the photos with the version that "
                f"last opened this profile."
            )

    if is_new:
        # Create a local engine for this target database. Critical: do not
        # touch db.engine, which belongs to the currently loaded profile.
        target_engine = sa_create_engine(f"sqlite:///{path}")
        try:
            # Create the schema using the same tables as a freshly switched profile.
            SQLModel.metadata.create_all(target_engine)
            target_engine.dispose()

            # Now stamp it at head using the migration system. The stamp_db and
            # upgrade_db functions use ALEMBIC_CFG, which is relative to the
            # database file via TAGORGANIZER_DB_URL. Set that temporarily.
            old_env = os.environ.get("TAGORGANIZER_DB_URL")
            try:
                os.environ["TAGORGANIZER_DB_URL"] = f"sqlite:///{path}"
                stamp_db("head")
            finally:
                if old_env is not None:
                    os.environ["TAGORGANIZER_DB_URL"] = old_env
                else:
                    os.environ.pop("TAGORGANIZER_DB_URL", None)
        except Exception:
            target_engine.dispose()
            raise
    else:
        # For existing databases, run upgrade to apply any pending migrations.
        # This temporarily points ALEMBIC_CFG at the target. Again, preserve
        # the currently loaded database's environment.
        old_env = os.environ.get("TAGORGANIZER_DB_URL")
        try:
            os.environ["TAGORGANIZER_DB_URL"] = f"sqlite:///{path}"
            upgrade_db()
        except Exception as exc:
            raise TargetUnusable(
                f"Could not bring the target database up to date: {exc}\n"
                f"Target: {path}"
            ) from exc
        finally:
            if old_env is not None:
                os.environ["TAGORGANIZER_DB_URL"] = old_env
            else:
                os.environ.pop("TAGORGANIZER_DB_URL", None)


@dataclass
class MoveResult:
    """Result of moving items to another profile's database.

    Attributes:
        moved_ids: IDs of items successfully moved.
        skipped_ids: IDs of items not moved because they already exist in the target.
        dropped_tags: Names of tags linked to moved items (these links are removed).
        dropped_lineage: How many "derived from" links were removed. Each one ties
            a moved photo to a photo that stays behind, or the reverse, and cannot
            survive the move because the ids it names no longer mean the same thing.
    """

    moved_ids: list[int] = field(default_factory=list)
    skipped_ids: list[int] = field(default_factory=list)
    dropped_tags: list[str] = field(default_factory=list)
    dropped_lineage: int = 0


# Columns to move from source to target, excluding id which is reassigned.
ITEM_COLUMNS = "uri, uri_md5, data_xxhash, camera, date, longitude, latitude"


def move_items(session: Session, target_path: Path, item_ids: list[int]) -> MoveResult:
    """Move items to another profile's database, atomically.

    ATTACHes the target and performs the insert and the delete in one
    transaction: SQLite commits across attached databases atomically, so the
    move either fully happens or fully does not. That guarantee holds only in
    rollback-journal mode, which prepare_target has already checked.

    The ordering below is load-bearing. The natural alternative - insert the
    rows whose uri is not already in the target, then delete the ones now in
    the target - LOSES PHOTOS: for a duplicate the uri is in the target because
    it was already there, so the delete removes the very row the insert
    skipped. Membership is therefore decided once, up front, and the insert and
    the delete both act on exactly that set of ids. Delete by id, never by uri.
    """
    target_path = Path(target_path)
    result = MoveResult()

    if not item_ids:
        return result

    # The guarantee covers every attached database, so the source is checked
    # as well as the target. prepare_target only sees the target, and a WAL
    # source would make the move non-atomic all the same. Checked before the
    # ATTACH, so a refusal leaves both databases as they were.
    source_mode = str(
        session.connection().exec_driver_sql("PRAGMA main.journal_mode").scalar()
    )
    if source_mode.lower() == "wal":
        raise TargetUnusable(
            "The library database is in WAL (write-ahead logging) mode, so a move "
            "cannot be made atomic. Nothing was moved.\n"
            f"Journal mode: {source_mode}"
        )

    try:
        # Begin transaction and attach the target database.
        # All operations below occur in this one transaction; if any step fails,
        # SQLite rolls back changes to both databases simultaneously.
        conn = session.connection()
        # The path is bound, not interpolated: an apostrophe in a folder name
        # would otherwise end the string literal and break the statement.
        conn.exec_driver_sql("ATTACH DATABASE ? AS tgt", (str(target_path),))

        # Step 1: Determine which items can be moved (those not already in
        # target by uri). Whether case matters follows the filesystem holding
        # the photos, not the one holding the target: a target database on ext4
        # beside photos on exFAT still has to fold case for those photos. On
        # macOS and Windows /p/A.JPG and /p/a.jpg are one file, so moving one
        # beside the other would leave two rows for one photo - and the unique
        # constraint cannot catch that, because the strings genuinely differ.
        # On Linux they are two files and both belong.
        # Membership is decided once; both insert and delete act on exactly this set.
        target_uris = {
            row[0] for row in conn.exec_driver_sql("SELECT uri FROM tgt.item").all()
        }
        target_folded = {uri.lower() for uri in target_uris}
        movable_set = set()
        raw_conn = conn.connection
        for chunk in chunk_ids(item_ids):
            placeholders = ",".join("?" * len(chunk))
            cursor = raw_conn.cursor()
            source_rows = cursor.execute(
                f"SELECT id, uri FROM main.item WHERE id IN ({placeholders})", chunk
            ).fetchall()
            for item_id, uri in source_rows:
                if paths.is_case_insensitive(Path(uri).parent):
                    duplicate = uri.lower() in target_folded
                else:
                    duplicate = uri in target_uris
                if not duplicate:
                    movable_set.add(item_id)

        # Preserve order by filtering requested ids, keeping only the movable ones
        # in the order they were requested (handling duplicates in item_ids).
        movable = []
        seen = set()
        for item_id in item_ids:
            if item_id in movable_set and item_id not in seen:
                movable.append(item_id)
                seen.add(item_id)

        skipped = [item_id for item_id in item_ids if item_id not in movable_set]
        result.skipped_ids = skipped

        if not movable:
            # Nothing to move; detach and return
            conn.exec_driver_sql("DETACH DATABASE tgt")
            return result

        # Step 2: Collect what the move will cut loose, for reporting: the
        # distinct tag names linked to movable items, and every lineage link
        # touching one, from either end.
        dropped_tag_names = set()
        lineage_pairs = set()
        for chunk in chunk_ids(movable):
            if not chunk:
                continue
            placeholders = ",".join("?" * len(chunk))
            query = f"""
                SELECT DISTINCT tag.name
                FROM main.itemtaglink
                JOIN main.tag ON itemtaglink.tag_id = tag.id
                WHERE itemtaglink.item_id IN ({placeholders})
            """
            cursor = raw_conn.cursor()
            tag_rows = cursor.execute(query, chunk).fetchall()
            dropped_tag_names.update(row[0] for row in tag_rows)

            # Each end is queried on its own: one statement matching either end
            # would bind every id twice and could exceed the variable cap.
            for end in ("child_id", "parent_id"):
                lineage_rows = cursor.execute(
                    f"SELECT child_id, parent_id FROM main.itemparentlink "
                    f"WHERE {end} IN ({placeholders})",
                    chunk,
                ).fetchall()
                lineage_pairs.update(tuple(row) for row in lineage_rows)

        result.dropped_tags = sorted(list(dropped_tag_names))
        result.dropped_lineage = len(lineage_pairs)

        # Step 3: Insert the movable items into the target.
        # The target will assign new ids; we don't carry ids across databases.
        for chunk in chunk_ids(movable):
            if not chunk:
                continue
            placeholders = ",".join("?" * len(chunk))
            insert_query = f"""
                INSERT INTO tgt.item ({ITEM_COLUMNS})
                SELECT {ITEM_COLUMNS} FROM main.item
                WHERE id IN ({placeholders})
            """
            cursor = raw_conn.cursor()
            cursor.execute(insert_query, chunk)

        # Step 4: Remove tag and lineage links for moved items from source.
        # Tag rows remain in the source; only the links are removed. Lineage
        # links go from both ends. The moved ids are reassigned in the target,
        # and SQLite can hand a freed id to a later photo, so a link left behind
        # would make that photo appear derived from something it never was.
        for chunk in chunk_ids(movable):
            if not chunk:
                continue
            placeholders = ",".join("?" * len(chunk))
            cursor = raw_conn.cursor()
            cursor.execute(
                f"DELETE FROM main.itemtaglink WHERE item_id IN ({placeholders})",
                chunk,
            )
            cursor.execute(
                f"DELETE FROM main.itemparentlink WHERE child_id IN ({placeholders})",
                chunk,
            )
            cursor.execute(
                f"DELETE FROM main.itemparentlink WHERE parent_id IN ({placeholders})",
                chunk,
            )

        # Step 5: Remove the moved items from source.
        # Delete by id, never by uri, to avoid the data-loss bug.
        for chunk in chunk_ids(movable):
            if not chunk:
                continue
            placeholders = ",".join("?" * len(chunk))
            delete_items_query = f"""
                DELETE FROM main.item
                WHERE id IN ({placeholders})
            """
            cursor = raw_conn.cursor()
            cursor.execute(delete_items_query, chunk)

        # All operations succeeded; commit the transaction across both databases.
        session.commit()
        result.moved_ids = movable

    except Exception:
        # On any exception: roll back both databases and re-raise.
        # Never swallow — a silent failure here is indistinguishable from success
        # and the user would believe photos had moved when they had not.
        with contextlib.suppress(Exception):
            session.rollback()
        raise

    finally:
        # Detach the target, whether the move succeeded or failed.
        with contextlib.suppress(Exception):
            conn = session.connection()
            conn.exec_driver_sql("DETACH DATABASE tgt")

    return result
