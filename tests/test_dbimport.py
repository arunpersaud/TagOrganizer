"""Tests for F-Spot database import functionality.

Tests cover:
- F18: Preservation of photo timestamps from F-Spot
- F20: Preventing F-Spot table definitions from polluting SQLModel.metadata
- Transaction efficiency improvements
"""

import time
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine as sa_create_engine, text
from sqlmodel import Session, select, SQLModel

from tagorganizer import db
from tagorganizer.DBimport import import_f_spot
from tagorganizer.models import Item, ItemTagLink, Tag


def create_fspot_database(db_path, image_dir):
    """Create a synthetic F-Spot database with test data.

    Creates a minimal F-Spot database structure with:
    - Tags table with parent-child hierarchy
    - Photos table with timestamps
    - Photo_tags link table
    """
    engine = sa_create_engine(f"sqlite:///{db_path}")

    with engine.connect() as connection:
        # Create tags table
        connection.execute(
            text(
                """
            CREATE TABLE tags (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                category_id INTEGER,
                is_category BOOLEAN,
                sort_priority INTEGER,
                icon TEXT
            )
        """
            )
        )

        # Create photos table
        connection.execute(
            text(
                """
            CREATE TABLE photos (
                id INTEGER PRIMARY KEY,
                time INTEGER,
                base_uri TEXT,
                filename TEXT,
                description TEXT,
                roll_id INTEGER,
                default_version_id INTEGER,
                rating INTEGER
            )
        """
            )
        )

        # Create photo_tags table
        connection.execute(
            text(
                """
            CREATE TABLE photo_tags (
                photo_id INTEGER,
                tag_id INTEGER,
                PRIMARY KEY (photo_id, tag_id)
            )
        """
            )
        )

        # Insert tags: Travel (parent) and Japan (child)
        connection.execute(
            text(
                "INSERT INTO tags (id, name, category_id, is_category) VALUES (1, 'Travel', NULL, 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO tags (id, name, category_id, is_category) VALUES (2, 'Japan', 1, 0)"
            )
        )

        # Insert photos with Unix timestamps
        # 2020-01-01 00:00:00 UTC = 1577836800
        # 2020-01-02 00:00:00 UTC = 1577923200
        # Photo 3 has timestamp 0 (should result in date=None)
        base_uri = f"file://{image_dir}"
        connection.execute(
            text(
                f"INSERT INTO photos (id, time, base_uri, filename) VALUES (1, 1577836800, '{base_uri}', 'photo1.jpg')"
            )
        )
        connection.execute(
            text(
                f"INSERT INTO photos (id, time, base_uri, filename) VALUES (2, 1577923200, '{base_uri}', 'photo2.jpg')"
            )
        )
        connection.execute(
            text(
                f"INSERT INTO photos (id, time, base_uri, filename) VALUES (3, 0, '{base_uri}', 'photo3.jpg')"
            )
        )

        # Insert photo-tag links
        connection.execute(
            text("INSERT INTO photo_tags (photo_id, tag_id) VALUES (1, 1)")
        )
        connection.execute(
            text("INSERT INTO photo_tags (photo_id, tag_id) VALUES (2, 2)")
        )

        connection.commit()

    engine.dispose()


@pytest.fixture
def new_york(monkeypatch):
    """Pin the local timezone, so the expected local times are fixed.

    F-Spot stores Unix times. The importer reads them as local time, which
    depends on the machine running the test unless the zone is pinned.
    """
    if not hasattr(time, "tzset"):
        pytest.skip("this platform cannot change the timezone at runtime")
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.delenv("TZ", raising=False)
    time.tzset()


@pytest.fixture
def fspot_setup(tmp_path):
    """Setup F-Spot database and image files for testing."""
    # Create actual image files so import doesn't skip them
    for i in range(1, 4):
        (tmp_path / f"photo{i}.jpg").write_bytes(b"fake image data")

    # Create F-Spot database
    db_path = tmp_path / "fspot.db"
    create_fspot_database(db_path, tmp_path)

    return db_path


class TestImportFSpotTimestamps:
    """Test F18: F-Spot import preserves photo timestamps."""

    def test_import_preserves_unix_timestamps(self, temp_db, fspot_setup, new_york):
        """Test that Unix timestamps from F-Spot are converted to datetime.

        F-Spot stores photo times as Unix timestamps (seconds since 1970-01-01 UTC).
        This test verifies that these timestamps are correctly converted to datetime
        objects when importing items.
        """
        with pytest.raises(SystemExit) as exc_info:
            import_f_spot(fspot_setup)

        assert exc_info.value.code == 0

        # Verify items were imported with correct dates
        with Session(db.engine) as session:
            items = session.exec(select(Item).order_by(Item.id)).all()

            assert len(items) == 3

            # photo1: 1577836800 = 2020-01-01 00:00:00 UTC = 2019-12-31 19:00 in
            # New York. Dates are stored as naive local time, like EXIF dates.
            assert items[0].date == datetime(2019, 12, 31, 19, 0, 0)

            # photo2: 1577923200 = 2020-01-02 00:00:00 UTC = 2020-01-01 19:00 local
            assert items[1].date == datetime(2020, 1, 1, 19, 0, 0)

            # photo3: 0 timestamp should result in date=None (not 1970-01-01)
            assert items[2].date is None

    def test_import_handles_zero_timestamp(self, temp_db, fspot_setup):
        """Test that zero timestamp results in date=None, not 1970-01-01.

        This is important because F-Spot may have rows with time=0 for items
        without a recorded date. We should not convert this to 1970-01-01.
        """
        with pytest.raises(SystemExit):
            import_f_spot(fspot_setup)

        with Session(db.engine) as session:
            # Find the item created from photo3 (time=0)
            items = session.exec(select(Item).order_by(Item.uri)).all()
            photo3 = next((i for i in items if "photo3" in i.uri), None)

            assert photo3 is not None
            assert photo3.date is None


class TestImportFSpotMetadata:
    """Test F20: F-Spot table definitions don't pollute SQLModel.metadata."""

    def test_no_new_metadata_tables_added(self, temp_db, fspot_setup):
        """Test that F-Spot tables don't register in SQLModel.metadata.

        The original implementation declared F-Spot table classes with table=True,
        which registered them in the shared SQLModel.metadata. This test verifies
        that the fixed implementation uses raw SQL and doesn't pollute metadata.
        """
        # Record tables before import
        tables_before = set(SQLModel.metadata.tables.keys())

        with pytest.raises(SystemExit):
            import_f_spot(fspot_setup)

        # Record tables after import
        tables_after = set(SQLModel.metadata.tables.keys())

        # Verify no new F-Spot tables were added
        assert tables_after == tables_before, (
            f"New tables added to metadata: {tables_after - tables_before}. "
            f"Expected no 'tags', 'photos', or 'photo_tags' entries."
        )


class TestImportFSpotHierarchy:
    """Test that tag hierarchy is preserved during import."""

    def test_tag_hierarchy_preserved(self, temp_db, fspot_setup):
        """Test that parent-child tag relationships are maintained."""
        with pytest.raises(SystemExit):
            import_f_spot(fspot_setup)

        with Session(db.engine) as session:
            parent = session.exec(select(Tag).where(Tag.name == "Travel")).first()
            child = session.exec(select(Tag).where(Tag.name == "Japan")).first()

            assert parent is not None, "Parent tag 'Travel' not imported"
            assert child is not None, "Child tag 'Japan' not imported"
            assert child.parent_id == parent.id, (
                f"Child tag parent_id={child.parent_id}, " f"expected {parent.id}"
            )


class TestImportFSpotLinks:
    """Test that item-tag links are created during import."""

    def test_photo_tag_links_created(self, temp_db, fspot_setup):
        """Test that photo-tag associations are created in the main database."""
        with pytest.raises(SystemExit):
            import_f_spot(fspot_setup)

        with Session(db.engine) as session:
            links = session.exec(select(ItemTagLink)).all()

            # Should have 2 links from our test data
            assert len(links) == 2, f"Expected 2 links, got {len(links)}"


class TestImportFSpotErrors:
    """Test error handling in import_f_spot."""

    def test_missing_database_exits_with_code_2(self):
        """Test that importing a non-existent database exits with code 2."""
        missing_db = Path("/nonexistent/fspot-12345.db")

        with pytest.raises(SystemExit) as exc_info:
            import_f_spot(missing_db)

        assert exc_info.value.code == 2


class TestImportFSpotEndToEnd:
    """End-to-end integration test for F-Spot import."""

    def test_complete_import_workflow(self, temp_db, fspot_setup, new_york):
        """Test the complete import workflow with all components working together.

        This test verifies:
        - Items are imported with correct dates (F18)
        - Metadata is not polluted (F20)
        - Tag hierarchy is preserved
        - Links are created
        - Import completes with sys.exit(0)
        """
        tables_before = set(SQLModel.metadata.tables.keys())

        with pytest.raises(SystemExit) as exc_info:
            import_f_spot(fspot_setup)

        assert exc_info.value.code == 0

        # Verify metadata was not polluted (F20)
        tables_after = set(SQLModel.metadata.tables.keys())
        assert tables_after == tables_before

        with Session(db.engine) as session:
            # Verify items exist with correct dates (F18)
            items = session.exec(select(Item)).all()
            assert len(items) == 3

            # Verify we can find specific items
            photo1 = next((i for i in items if "photo1" in i.uri), None)
            assert photo1 is not None
            assert photo1.date == datetime(2019, 12, 31, 19, 0, 0)

            # Verify tags exist with hierarchy
            travel = session.exec(select(Tag).where(Tag.name == "Travel")).first()
            japan = session.exec(select(Tag).where(Tag.name == "Japan")).first()
            assert travel is not None
            assert japan is not None
            assert japan.parent_id == travel.id

            # Verify links exist
            links = session.exec(select(ItemTagLink)).all()
            assert len(links) == 2


def _add_fspot_rows(db_path, sql):
    engine = sa_create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(text(sql))
    engine.dispose()


class TestImportFSpotRobustness:
    """Malformed or unusual F-Spot data must not abort the whole import."""

    def test_percent_encoded_names_are_decoded_completely(self, temp_db, fspot_setup):
        """F-Spot escapes every unsafe character, not only spaces and ampersands."""
        image_dir = fspot_setup.parent
        (image_dir / "my photo+é.jpg").write_bytes(b"fake")
        _add_fspot_rows(
            fspot_setup,
            f"INSERT INTO photos (id, time, base_uri, filename) VALUES "
            f"(9, 0, 'file://{image_dir}', 'my%20photo%2B%C3%A9.jpg')",
        )

        with pytest.raises(SystemExit):
            import_f_spot(fspot_setup)

        with Session(db.engine) as session:
            uris = session.exec(select(Item.uri)).all()
        assert str(image_dir / "my photo+é.jpg") in uris

    def test_a_category_missing_from_the_tags_is_skipped_not_fatal(
        self, temp_db, fspot_setup
    ):
        _add_fspot_rows(
            fspot_setup,
            "INSERT INTO tags (id, name, category_id) VALUES (3, 'Orphan', 99)",
        )

        with pytest.raises(SystemExit) as exc_info:
            import_f_spot(fspot_setup)

        assert exc_info.value.code == 0
        assert db.get_tag("Orphan") is not None
        assert db.get_tag("Orphan").parent_id is None

    def test_a_category_loop_in_fspot_is_not_nested(self, temp_db, fspot_setup):
        """Travel under Japan, and Japan under Travel, cannot both hold."""
        _add_fspot_rows(fspot_setup, "UPDATE tags SET category_id = 2 WHERE id = 1")

        with pytest.raises(SystemExit) as exc_info:
            import_f_spot(fspot_setup)

        assert exc_info.value.code == 0
        assert db.get_tag("Japan").parent_id is None
        assert db.get_tag("Travel").parent_id == db.get_tag("Japan").id
