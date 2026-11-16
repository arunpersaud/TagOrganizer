"""Tests for database schema and initialization.

Covers database creation, migrations, and model constraints.
"""

from sqlalchemy import inspect, text, select, create_engine as sa_create_engine
from sqlmodel import Session, SQLModel

from tagorganizer import db
from tagorganizer.models import Item
from tagorganizer.migrations import upgrade_db, stamp_db

from conftest import alembic_head


class TestDatabaseCreationF1:
    """Tests for F1: Creating a new database from scratch.

    Ensures that creating a brand-new database doesn't crash due to
    alembic trying to re-apply migrations on an already-complete schema.
    """

    def test_new_database_creation_succeeds(self, db_path, monkeypatch):
        """Creating a new database from scratch succeeds without errors.

        This is the regression test for F1. A new database should:
        1. Have all tables created
        2. Have the alembic_version table pointing to head
        3. Not crash with "duplicate column name" errors

        The fix works by detecting that the database file doesn't exist yet,
        calling create_db() to build the schema, then calling stamp_db("head")
        instead of upgrade_db() to mark the schema as current without
        re-running migrations.
        """
        # Set up the database engine and environment
        db.set_engine(str(db_path))
        monkeypatch.setenv("TAGORGANIZER_DB_URL", f"sqlite:///{db_path}")

        # Verify the database file doesn't exist yet
        assert not db_path.exists()

        # This is what read_config() does - create the schema and stamp at head
        db.create_db()
        stamp_db("head")

        # Verify the database file was created
        assert db_path.exists()

        # Verify we can query the database without errors
        with Session(db.engine) as session:
            # Should be able to query without errors
            items = session.exec(select(Item)).all()
            assert items == []

        # Verify alembic_version table exists and is at head
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        assert "alembic_version" in tables

        # Get the current alembic version
        with Session(db.engine) as session:
            result = session.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchone()
            # Should be at the latest migration
            assert result is not None
            assert result[0] == alembic_head()

    def test_upgrade_old_database_without_geolocation(self, db_path, monkeypatch):
        """An older database that lacks longitude/latitude still upgrades cleanly.

        This tests that existing databases created before the geolocation
        migration still work with the upgrade path.
        """
        # Set up a fresh database
        db.set_engine(str(db_path))
        monkeypatch.setenv("TAGORGANIZER_DB_URL", f"sqlite:///{db_path}")

        # Create the basic schema without geolocation columns
        engine = sa_create_engine(f"sqlite:///{db_path}")

        # Create only the minimal item table (no geolocation)
        with engine.connect() as conn:
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
                CREATE TABLE alembic_version (
                    version_num VARCHAR(32) PRIMARY KEY
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
                INSERT INTO alembic_version (version_num) VALUES ('c3c22277f560')
            """)
            )
            conn.commit()

        # Point the global engine to this database
        db.engine = engine

        # Now run upgrade
        upgrade_db()

        # Verify the columns were added
        inspector = inspect(db.engine)
        columns = [col["name"] for col in inspector.get_columns("item")]
        assert "longitude" in columns
        assert "latitude" in columns

        # Verify indexes were added
        indexes = inspector.get_indexes("item")
        index_columns = [idx["column_names"] for idx in indexes]
        assert any("uri" in cols for cols in index_columns)

        # Verify alembic version was updated to latest
        with Session(db.engine) as session:
            result = session.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchone()
            assert result[0] == alembic_head()


class TestItemHashF16:
    """Tests for F16: Item.__hash__ returns integer even for unsaved items."""

    def test_hash_unsaved_item_does_not_raise(self):
        """hash() on an unsaved Item should not raise TypeError."""
        # Create an unsaved item
        item = Item(uri="/photos/test.jpg")

        # This should not raise TypeError: __hash__ method should return an integer
        h = hash(item)

        # The hash should be an integer
        assert isinstance(h, int)

    def test_hash_saved_item_consistent(self, temp_db):
        """Two saved Items with the same id are equal and hash equal.

        The exact hash value is an implementation detail; what callers rely on
        is that equal items collapse in sets, dicts and lru_cache.
        """
        with Session(temp_db) as session:
            item = Item(uri="/photos/test.jpg")
            session.add(item)
            session.commit()
            session.refresh(item)

            same = Item(id=item.id, uri="/photos/renamed.jpg")

            assert isinstance(hash(item), int)
            assert item == same
            assert hash(item) == hash(same)
            assert len({item, same}) == 1

    def test_equality_consistency_with_hash(self, temp_db):
        """Verify that __eq__ and __hash__ are consistent."""
        with Session(temp_db) as session:
            item1 = Item(uri="/photos/test1.jpg")
            item2 = Item(uri="/photos/test2.jpg")

            session.add(item1)
            session.add(item2)
            session.commit()
            session.refresh(item1)
            session.refresh(item2)

            # Different IDs should not be equal
            assert item1 != item2
            # And should have different hashes
            assert hash(item1) != hash(item2)

            # Same item loaded twice should be equal
            item1_copy = session.get(Item, item1.id)
            assert item1 == item1_copy
            assert hash(item1) == hash(item1_copy)

    def test_unsaved_items_different_hashes(self):
        """Two unsaved items should have different hashes (based on memory address)."""
        item1 = Item(uri="/photos/test1.jpg")
        item2 = Item(uri="/photos/test2.jpg")

        h1 = hash(item1)
        h2 = hash(item2)

        # Should both be integers
        assert isinstance(h1, int)
        assert isinstance(h2, int)

        # Should be different (based on memory address id())
        assert h1 != h2

    def test_unsaved_items_compare_by_identity(self):
        """Distinct unsaved items must not be equal to each other.

        Comparing id to id would make every unsaved item equal to every other
        one (None == None), while their hashes differ because they fall back to
        identity. That combination breaks the hash/eq invariant, so unsaved
        items compare by identity instead.
        """
        item1 = Item(uri="/photos/test1.jpg")
        item2 = Item(uri="/photos/test2.jpg")

        assert item1 != item2
        assert item1 == item1
        assert len({item1, item2}) == 2

    def test_hash_eq_invariant_holds(self, temp_db):
        """Anything that compares equal must hash equal."""
        saved = Item(id=7, uri="/photos/a.jpg")
        same_id = Item(id=7, uri="/photos/b.jpg")
        unsaved = Item(uri="/photos/c.jpg")

        for left in (saved, same_id, unsaved):
            for right in (saved, same_id, unsaved):
                if left == right:
                    assert hash(left) == hash(right)


class TestIndexesF17:
    """Tests for F17: Indexes on uri and data_xxhash columns."""

    def test_uri_index_exists(self, temp_db):
        """The uri column should have an index."""
        inspector = inspect(temp_db)
        indexes = inspector.get_indexes("item")
        index_columns = [idx["column_names"] for idx in indexes]

        # Check that at least one index includes 'uri'
        assert any(
            "uri" in cols for cols in index_columns
        ), f"No index found for uri column. Existing indexes: {index_columns}"

    def test_data_xxhash_index_exists(self, temp_db):
        """The data_xxhash column should have an index."""
        inspector = inspect(temp_db)
        indexes = inspector.get_indexes("item")
        index_columns = [idx["column_names"] for idx in indexes]

        # Check that at least one index includes 'data_xxhash'
        assert any(
            "data_xxhash" in cols for cols in index_columns
        ), f"No index found for data_xxhash column. Existing indexes: {index_columns}"

    def test_fresh_database_has_indexes(self, db_path, tmp_path, monkeypatch):
        """A freshly created database should include the uri and data_xxhash indexes."""
        # Set up a new database
        db.set_engine(str(db_path))
        monkeypatch.setenv("TAGORGANIZER_DB_URL", f"sqlite:///{db_path}")

        # Create and stamp the database
        SQLModel.metadata.create_all(db.engine)
        stamp_db("head")

        # Verify indexes exist
        inspector = inspect(db.engine)
        indexes = inspector.get_indexes("item")
        index_columns = [idx["column_names"] for idx in indexes]

        # Should have indexes on uri and data_xxhash
        uri_indexed = any("uri" in cols for cols in index_columns)
        xxhash_indexed = any("data_xxhash" in cols for cols in index_columns)

        assert uri_indexed, f"No index on uri. Indexes: {index_columns}"
        assert xxhash_indexed, f"No index on data_xxhash. Indexes: {index_columns}"

    def test_uri_index_named_correctly(self, temp_db):
        """The uri index should follow naming convention."""
        inspector = inspect(temp_db)
        indexes = inspector.get_indexes("item")

        uri_index = None
        for idx in indexes:
            if "uri" in idx["column_names"]:
                uri_index = idx
                break

        assert uri_index is not None
        # Alembic naming convention: ix_<table>_<column>
        assert "uri" in uri_index["name"].lower()
