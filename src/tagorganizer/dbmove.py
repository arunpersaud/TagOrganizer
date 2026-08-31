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

from sqlalchemy import text, create_engine as sa_create_engine
from sqlmodel import SQLModel

from .migrations import upgrade_db, stamp_db

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
