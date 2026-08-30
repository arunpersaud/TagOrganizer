"""Tag lookup and the queries behind the maintenance tasks."""

from sqlmodel import Session

from tagorganizer import db
from tagorganizer.models import Item


class TestTagLookupIgnoresCase:
    def test_get_tag_finds_a_differently_cased_name(self, temp_db):
        db.add_tag("iPhone")
        assert db.get_tag("iphone") is not None
        assert db.get_tag("IPHONE") is not None

    def test_names_are_stored_exactly_as_typed(self, temp_db):
        db.add_tag("iPhone")
        assert db.get_tag("iphone").name == "iPhone"

    def test_add_tag_does_not_duplicate_on_case(self, temp_db):
        first = db.add_tag("iPhone")
        second = db.add_tag("IPHONE")
        assert first == second
        assert len(db.get_all_tags()) == 1

    def test_surrounding_whitespace_is_ignored(self, temp_db):
        db.add_tag("Holiday")
        assert db.get_tag("  holiday  ") is not None


class TestItemsUnderNoDate:
    def test_finds_items_regardless_of_whether_they_have_gps(self, temp_db):
        """The old code searched only items with a location, which is backwards."""
        with Session(temp_db) as session:
            session.add(Item(uri="/photos/no-date/a.jpg"))
            session.add(Item(uri="/photos/no-date/b.jpg", longitude=1.0, latitude=2.0))
            session.add(Item(uri="/photos/2024/01/01/c.jpg"))
            session.commit()

        found = {item.uri for item in db.get_items_under_no_date()}
        assert found == {"/photos/no-date/a.jpg", "/photos/no-date/b.jpg"}

    def test_matches_windows_separators(self, temp_db):
        with Session(temp_db) as session:
            session.add(Item(uri=r"C:\photos\no-date\a.jpg"))
            session.commit()
        assert len(db.get_items_under_no_date()) == 1


class TestItemsWithoutLocation:
    def test_either_missing_coordinate_counts_as_missing(self, temp_db):
        """filter_query's no_gps tests latitude, so this must agree with it."""
        with Session(temp_db) as session:
            session.add(Item(uri="/p/both.jpg", longitude=1.0, latitude=2.0))
            session.add(Item(uri="/p/no-lat.jpg", longitude=1.0))
            session.add(Item(uri="/p/no-lon.jpg", latitude=2.0))
            session.add(Item(uri="/p/neither.jpg"))
            session.commit()

        found = {item.uri for item in db.get_items_without_location()}
        assert found == {"/p/no-lat.jpg", "/p/no-lon.jpg", "/p/neither.jpg"}
