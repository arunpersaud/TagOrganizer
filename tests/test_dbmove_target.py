"""Tests for target database preparation for cross-profile moves.

This module tests the setup and validation of target databases before any
cross-profile move transaction opens. All checks happen before mutating state,
so a failure leaves both source and target untouched.
"""

import os
import pytest
from sqlalchemy import text, inspect, create_engine as sa_create_engine

from tagorganizer import db
from tagorganizer.config import ConfigManager, ProfileNotFoundError
from tagorganizer.dbmove import journal_mode, prepare_target, TargetUnusable
from tagorganizer.migrations import stamp_db


class TestJournalMode:
    """Tests for reading the journal mode of a database file."""

    def test_journal_mode_returns_delete_for_new_database(self, db_path):
        """journal_mode returns "delete" for a newly created database."""
        # Create a database the way the app does
        db.set_engine(str(db_path))
        os.environ["TAGORGANIZER_DB_URL"] = f"sqlite:///{db_path}"
        db.create_db()
        stamp_db("head")

        # Check journal mode
        mode = journal_mode(db_path)
        assert mode == "delete"

    def test_journal_mode_returns_mode_for_wal_database(self, tmp_path):
        """journal_mode returns "wal" for a database explicitly set to WAL mode."""
        db_path = tmp_path / "wal-test.db"

        # Create a database and switch it to WAL mode
        engine = sa_create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.commit()

        # Check journal mode
        mode = journal_mode(db_path)
        assert mode.lower() == "wal"


class TestPrepareTarget:
    """Tests for prepare_target function."""

    def test_prepare_target_creates_new_database(self, tmp_path):
        """prepare_target creates a new database with full schema when it doesn't exist."""
        target_path = tmp_path / "new-target.db"
        assert not target_path.exists()

        # Prepare the target
        prepare_target(target_path)

        # Verify the database was created
        assert target_path.exists()

        # Verify it has the expected schema (item and tag tables)
        engine = sa_create_engine(f"sqlite:///{target_path}")
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

        assert "item" in table_names
        assert "tag" in table_names
        assert "itemtaglink" in table_names

        # Verify alembic_version table exists and is at head
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchone()
            assert result is not None
            # Latest migration ID
            assert result[0] == "9e42c23d5f4a"

        engine.dispose()

    def test_prepare_target_leaves_current_database_untouched(self, tmp_path):
        """prepare_target on an existing, current database leaves it unchanged."""
        target_path = tmp_path / "existing-target.db"

        # Create and stamp a database
        db.set_engine(str(target_path))
        os.environ["TAGORGANIZER_DB_URL"] = f"sqlite:///{target_path}"
        db.create_db()
        stamp_db("head")

        # Capture file metadata
        stat_before = target_path.stat()
        size_before = stat_before.st_size
        mtime_before = stat_before.st_mtime

        # Wait a bit to ensure time changes if file is modified
        import time

        time.sleep(0.01)

        # Prepare the target again
        prepare_target(target_path)

        # Verify file was not modified
        stat_after = target_path.stat()
        size_after = stat_after.st_size
        mtime_after = stat_after.st_mtime

        assert size_before == size_after
        assert mtime_before == mtime_after

    def test_prepare_target_raises_when_parent_dir_missing(self, tmp_path):
        """prepare_target raises TargetUnusable when parent directory doesn't exist."""
        # Create a path with a non-existent parent
        nonexistent_parent = tmp_path / "does" / "not" / "exist"
        target_path = nonexistent_parent / "target.db"

        with pytest.raises(TargetUnusable) as exc_info:
            prepare_target(target_path)

        # Verify the message names the path
        error_msg = str(exc_info.value)
        assert str(target_path) in error_msg

    def test_prepare_target_raises_when_database_is_wal(self, tmp_path):
        """prepare_target raises TargetUnusable when database is in WAL mode."""
        target_path = tmp_path / "wal-target.db"

        # Create a database and switch it to WAL mode
        engine = sa_create_engine(f"sqlite:///{target_path}")
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE dummy (id INTEGER)"))
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.commit()
        engine.dispose()

        # Attempt to prepare it
        with pytest.raises(TargetUnusable) as exc_info:
            prepare_target(target_path)

        # Verify the message explains why WAL is a problem
        error_msg = str(exc_info.value)
        assert "WAL" in error_msg or "wal" in error_msg.lower()
        assert "atomic" in error_msg.lower() or "transaction" in error_msg.lower()

    def test_prepare_target_migrates_behind_database(self, tmp_path):
        """prepare_target upgrades a database that is behind the migration chain."""
        target_path = tmp_path / "old-target.db"

        # Create a database at the first migration (before geolocation)
        engine = sa_create_engine(f"sqlite:///{target_path}")
        with engine.connect() as conn:
            # Create the schema as it was at the first migration
            conn.execute(
                text("""
                CREATE TABLE item (
                    id INTEGER PRIMARY KEY,
                    uri VARCHAR NOT NULL,
                    uri_md5 VARCHAR DEFAULT '',
                    data_xxhash VARCHAR DEFAULT '',
                    camera VARCHAR,
                    date DATETIME
                )
            """)
            )
            conn.execute(
                text("""
                CREATE TABLE tag (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    parent_id INTEGER,
                    FOREIGN KEY (parent_id) REFERENCES tag (id)
                )
            """)
            )
            conn.execute(
                text("""
                CREATE TABLE itemtaglink (
                    item_id INTEGER,
                    tag_id INTEGER,
                    PRIMARY KEY (item_id, tag_id),
                    FOREIGN KEY (item_id) REFERENCES item (id),
                    FOREIGN KEY (tag_id) REFERENCES tag (id)
                )
            """)
            )
            conn.execute(
                text("""
                CREATE TABLE alembic_version (
                    version_num VARCHAR(32) PRIMARY KEY
                )
            """)
            )
            # Stamp at the initial migration
            conn.execute(
                text(
                    "INSERT INTO alembic_version (version_num) VALUES ('c3c22277f560')"
                )
            )
            conn.commit()
        engine.dispose()

        # Verify it doesn't have geolocation columns yet
        engine = sa_create_engine(f"sqlite:///{target_path}")
        inspector = inspect(engine)
        columns = [col["name"] for col in inspector.get_columns("item")]
        assert "longitude" not in columns
        assert "latitude" not in columns
        engine.dispose()

        # Prepare the target (should upgrade)
        prepare_target(target_path)

        # Verify it now has geolocation columns
        engine = sa_create_engine(f"sqlite:///{target_path}")
        inspector = inspect(engine)
        columns = [col["name"] for col in inspector.get_columns("item")]
        assert "longitude" in columns
        assert "latitude" in columns

        # Verify it's at head
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchone()
            assert result[0] == "9e42c23d5f4a"
        engine.dispose()


class TestGetProfileDatabase:
    """Tests for ConfigManager.get_profile_database."""

    def test_get_profile_database_returns_path_for_known_profile(
        self, tmp_path, monkeypatch
    ):
        """get_profile_database returns the configured path for a known profile."""

        # Create a config file with multiple profiles
        config_file = tmp_path / "config.ini"
        config_file.write_text(
            "[work]\ndatabase = /path/to/work.db\nphoto_path = .\nvideo_path = .\n"
            "[personal]\ndatabase = /path/to/personal.db\nphoto_path = .\nvideo_path = .\n"
        )

        # Create a manager and load the config
        manager = ConfigManager.__new__(ConfigManager)
        manager.config_file = config_file
        manager.profile = "work"

        import configparser

        manager.config = configparser.ConfigParser()
        manager.config.read(config_file)

        # Test getting a known profile
        path = manager.get_profile_database("personal")
        assert str(path) == "/path/to/personal.db"

    def test_get_profile_database_raises_for_unknown_profile(self, tmp_path):
        """get_profile_database raises ProfileNotFoundError for an unknown profile."""
        import configparser

        config_file = tmp_path / "config.ini"
        config_file.write_text(
            "[work]\ndatabase = /path/to/work.db\nphoto_path = .\nvideo_path = .\n"
        )

        manager = ConfigManager.__new__(ConfigManager)
        manager.config_file = config_file
        manager.profile = "work"
        manager.config = configparser.ConfigParser()
        manager.config.read(config_file)

        # Try to get a profile that doesn't exist
        with pytest.raises(ProfileNotFoundError) as exc_info:
            manager.get_profile_database("unknown")

        assert exc_info.value.profile == "unknown"
