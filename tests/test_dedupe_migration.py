"""The migration that cleans up duplicates and then forbids them.

This one carries more risk than any other in the project. A unique-constraint
migration that assumes a clean database aborts the upgrade on a machine that
is not clean, and the application then will not open at all - on the machine
holding the photos. So the migration deduplicates first, in the same
transaction, and these tests run it against deliberately dirty databases.

Migrations use raw SQL against the tables as they were at that revision, never
the models, because the models keep changing underneath old migrations.
"""

import os
import pathlib
import sqlite3

import pytest
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory

from tagorganizer import db, migrations

DEDUPE_REVISION = "33cc0c0a76e3"  # the revision this migration follows


def _alembic_config():
    root = pathlib.Path(migrations.__file__).parent
    config = AlembicConfig(str(root.parent / "alembic.ini"))
    config.set_main_option("script_location", str(root))
    return config


def head_revision():
    return ScriptDirectory.from_config(_alembic_config()).get_current_head()


@pytest.fixture
def dirty_library(tmp_path):
    """A database at the previous revision, holding duplicates.

    Two rows for /p/a.jpg with tags on each and lineage pointing at one of
    them, plus two tags that differ only in case.
    """
    path = tmp_path / "library.db"
    db.set_engine(str(path))
    os.environ["TAGORGANIZER_DB_URL"] = f"sqlite:///{path}"
    migrations.upgrade_db(DEDUPE_REVISION)
    db.engine.dispose()

    connection = sqlite3.connect(path)
    connection.executescript(
        """
        INSERT INTO item (id, uri, uri_md5, data_xxhash, date, latitude, longitude)
        VALUES (1, '/p/a.jpg', '', '', NULL, NULL, NULL),
               (2, '/p/a.jpg', 'abc', '', '2021-03-07 00:00:00', 40.7, -74.0),
               (3, '/p/b.jpg', '', '', NULL, NULL, NULL);

        INSERT INTO tag (id, name, parent_id)
        VALUES (1, 'Beach', NULL), (2, 'beach', NULL), (3, 'Surf', 1);

        -- (1,1) and (2,1) put the same tag on both duplicate rows: after the
        -- merge both become (1,1), which violates the composite primary key
        -- unless the rebuild collapses them.
        INSERT INTO itemtaglink (item_id, tag_id)
        VALUES (1, 1), (2, 1), (2, 2), (2, 3), (3, 1);

        INSERT INTO itemparentlink (child_id, parent_id)
        VALUES (3, 2), (2, 1);
        """
    )
    connection.commit()
    connection.close()
    return path


def rows(path, sql):
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


class TestUpgradingADirtyLibrary:
    def test_the_upgrade_succeeds(self, dirty_library):
        """The whole point: a machine with duplicates must still start."""
        db.set_engine(str(dirty_library))
        migrations.upgrade_db()
        db.engine.dispose()

        assert rows(dirty_library, "SELECT version_num FROM alembic_version") == [
            (head_revision(),)
        ]

    def test_only_one_row_survives_per_uri(self, dirty_library):
        db.set_engine(str(dirty_library))
        migrations.upgrade_db()
        db.engine.dispose()

        assert rows(dirty_library, "SELECT id, uri FROM item ORDER BY id") == [
            (1, "/p/a.jpg"),
            (3, "/p/b.jpg"),
        ]

    def test_the_oldest_row_is_the_one_kept(self, dirty_library):
        db.set_engine(str(dirty_library))
        migrations.upgrade_db()
        db.engine.dispose()

        assert rows(dirty_library, "SELECT id FROM item WHERE uri='/p/a.jpg'") == [(1,)]

    def test_the_survivor_gains_what_the_duplicate_knew(self, dirty_library):
        """Row 2 had the date, hash and coordinates; row 1 had none."""
        db.set_engine(str(dirty_library))
        migrations.upgrade_db()
        db.engine.dispose()

        found = rows(
            dirty_library,
            "SELECT date, latitude, longitude, uri_md5 FROM item WHERE id=1",
        )[0]
        assert found[0] is not None
        assert (found[1], found[2]) == (40.7, -74.0)
        assert found[3] == "abc"

    def test_tags_from_both_rows_end_up_on_the_survivor(self, dirty_library):
        db.set_engine(str(dirty_library))
        migrations.upgrade_db()
        db.engine.dispose()

        found = rows(
            dirty_library,
            "SELECT DISTINCT tag_id FROM itemtaglink WHERE item_id=1 ORDER BY tag_id",
        )
        # Tag 2 was merged into tag 1, so both rows' tags fold to 1 and 3.
        assert found == [(1,), (3,)]

    def test_lineage_follows_the_survivor(self, dirty_library):
        """Item 3 derived from item 2, which is now item 1."""
        db.set_engine(str(dirty_library))
        migrations.upgrade_db()
        db.engine.dispose()

        assert rows(
            dirty_library, "SELECT child_id, parent_id FROM itemparentlink"
        ) == [(3, 1)]

    def test_no_item_becomes_its_own_parent(self, dirty_library):
        """Item 2 derived from item 1, and they are the same photo."""
        db.set_engine(str(dirty_library))
        migrations.upgrade_db()
        db.engine.dispose()

        assert rows(
            dirty_library,
            "SELECT COUNT(*) FROM itemparentlink WHERE child_id = parent_id",
        ) == [(0,)]

    def test_tags_differing_only_in_case_are_merged(self, dirty_library):
        db.set_engine(str(dirty_library))
        migrations.upgrade_db()
        db.engine.dispose()

        assert rows(dirty_library, "SELECT id, name FROM tag ORDER BY id") == [
            (1, "Beach"),
            (3, "Surf"),
        ]

    def test_a_child_tag_keeps_its_parent(self, dirty_library):
        db.set_engine(str(dirty_library))
        migrations.upgrade_db()
        db.engine.dispose()

        assert rows(dirty_library, "SELECT parent_id FROM tag WHERE id=3") == [(1,)]


class TestTheConstraintsAreEnforced:
    def test_a_second_row_for_a_uri_is_refused(self, dirty_library):
        db.set_engine(str(dirty_library))
        migrations.upgrade_db()
        db.engine.dispose()

        connection = sqlite3.connect(dirty_library)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO item (uri, uri_md5, data_xxhash) "
                    "VALUES ('/p/a.jpg', '', '')"
                )
        finally:
            connection.close()

    def test_a_second_tag_with_the_same_name_is_refused(self, dirty_library):
        db.set_engine(str(dirty_library))
        migrations.upgrade_db()
        db.engine.dispose()

        connection = sqlite3.connect(dirty_library)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO tag (name) VALUES ('Beach')")
        finally:
            connection.close()


class TestACleanLibrary:
    def test_a_library_with_no_duplicates_upgrades_untouched(self, tmp_path):
        path = tmp_path / "clean.db"
        db.set_engine(str(path))
        os.environ["TAGORGANIZER_DB_URL"] = f"sqlite:///{path}"
        migrations.upgrade_db(DEDUPE_REVISION)
        db.engine.dispose()

        connection = sqlite3.connect(path)
        connection.executescript(
            """
            INSERT INTO item (id, uri, uri_md5, data_xxhash)
            VALUES (1, '/p/a.jpg', '', ''), (2, '/p/b.jpg', '', '');
            INSERT INTO tag (id, name, parent_id) VALUES (1, 'Beach', NULL);
            INSERT INTO itemtaglink (item_id, tag_id) VALUES (1, 1);
            """
        )
        connection.commit()
        connection.close()

        db.set_engine(str(path))
        migrations.upgrade_db()
        db.engine.dispose()

        assert rows(path, "SELECT COUNT(*) FROM item") == [(2,)]
        assert rows(path, "SELECT COUNT(*) FROM itemtaglink") == [(1,)]

    def test_an_empty_library_upgrades(self, tmp_path):
        path = tmp_path / "empty.db"
        db.set_engine(str(path))
        os.environ["TAGORGANIZER_DB_URL"] = f"sqlite:///{path}"
        migrations.upgrade_db()
        db.engine.dispose()

        assert rows(path, "SELECT version_num FROM alembic_version") == [
            (head_revision(),)
        ]
