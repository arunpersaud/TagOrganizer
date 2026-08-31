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

from sqlalchemy import text, create_engine as sa_create_engine
from sqlmodel import SQLModel, Session

from .migrations import upgrade_db, stamp_db
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


def prepare_target(path: Path) -> None:
    """Make a target database safe to move rows into, or refuse.

    Checked in this order, all before any transaction: the parent directory is
    reachable (an unmounted drive must fail here, not midway); the database is
    created and stamped at head if absent, exactly as switching to that profile
    would; migrated if behind; refused if AHEAD of the migration chain this
    build knows, because writing to a schema we do not understand is how a
    library gets corrupted; and refused if it is in WAL mode, because SQLite's
    atomic multi-database commit guarantee does not hold there and the move
    would silently degrade to a non-atomic copy-then-delete.

    This is the only feature in the application that can destroy photos.
    Every failure path here leaves the source database completely untouched.
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

    # If the database doesn't exist yet, create it with the full schema,
    # exactly as switching to a new profile would.
    is_new = not path.exists()

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

    # At this point the database exists and has the schema at least at the
    # initial migration. Check if it needs upgrading.
    if not is_new:
        # For existing databases, run upgrade to apply any pending migrations.
        # This temporarily points ALEMBIC_CFG at the target. Again, preserve
        # the currently loaded database's environment.
        old_env = os.environ.get("TAGORGANIZER_DB_URL")
        try:
            os.environ["TAGORGANIZER_DB_URL"] = f"sqlite:///{path}"
            upgrade_db()
        finally:
            if old_env is not None:
                os.environ["TAGORGANIZER_DB_URL"] = old_env
            else:
                os.environ.pop("TAGORGANIZER_DB_URL", None)

    # Final check: the database must be in delete (rollback-journal) mode.
    # SQLite's atomic multi-database commit guarantee applies only in rollback
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


@dataclass
class MoveResult:
    """Result of moving items to another profile's database.

    Attributes:
        moved_ids: IDs of items successfully moved.
        skipped_ids: IDs of items not moved because they already exist in the target.
        dropped_tags: Names of tags linked to moved items (these links are removed).
    """

    moved_ids: list[int] = field(default_factory=list)
    skipped_ids: list[int] = field(default_factory=list)
    dropped_tags: list[str] = field(default_factory=list)


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

    try:
        # Begin transaction and attach the target database.
        # All operations below occur in this one transaction; if any step fails,
        # SQLite rolls back changes to both databases simultaneously.
        conn = session.connection()
        conn.exec_driver_sql(f"ATTACH DATABASE '{target_path}' AS tgt")

        # Step 1: Determine which items can be moved (those not already in target by uri).
        # Membership is decided once; both insert and delete act on exactly this set.
        # Use a set to track movable ids, then convert to list to preserve order.
        movable_set = set()
        raw_conn = conn.connection
        for chunk in chunk_ids(item_ids):
            if not chunk:
                continue
            placeholders = ",".join("?" * len(chunk))
            query = f"""
                SELECT id FROM main.item
                WHERE id IN ({placeholders})
                AND uri NOT IN (SELECT uri FROM tgt.item)
            """
            cursor = raw_conn.cursor()
            result_rows = cursor.execute(query, chunk).fetchall()
            movable_set.update([row[0] for row in result_rows])

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

        # Step 2: Collect the distinct tag names linked to movable items, for reporting.
        # We query for tags linked to these items so we can report which tags lose links.
        dropped_tag_names = set()
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

        result.dropped_tags = sorted(list(dropped_tag_names))

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

        # Step 4: Remove tag links for moved items from source.
        # Tag rows remain in the source; only the links are removed.
        for chunk in chunk_ids(movable):
            if not chunk:
                continue
            placeholders = ",".join("?" * len(chunk))
            delete_links_query = f"""
                DELETE FROM main.itemtaglink
                WHERE item_id IN ({placeholders})
            """
            cursor = raw_conn.cursor()
            cursor.execute(delete_links_query, chunk)

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
