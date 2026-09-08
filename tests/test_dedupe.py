"""Finding and merging records that describe the same thing.

Two rows for one file means tagging one of them leaves the other untagged, and
the grid shows the photo twice. Merging is destructive and has no undo, so
these assert on the resulting rows rather than on return values alone.
"""

from datetime import datetime

import pytest
from sqlmodel import Session, select

from tagorganizer import db
from tagorganizer.models import Item, ItemParentLink, ItemTagLink, Tag


@pytest.fixture
def library(temp_db):
    """Two rows for /p/a.jpg, one for /p/b.jpg, and two tags."""
    with Session(temp_db) as session:
        first = Item(uri="/p/a.jpg")
        second = Item(uri="/p/a.jpg")
        other = Item(uri="/p/b.jpg")
        for item in (first, second, other):
            session.add(item)

        beach = Tag(name="Beach")
        surf = Tag(name="Surf")
        for tag in (beach, surf):
            session.add(tag)
        session.commit()
        for obj in (first, second, other, beach, surf):
            session.refresh(obj)

        session.add(ItemTagLink(item_id=first.id, tag_id=beach.id))
        session.add(ItemTagLink(item_id=second.id, tag_id=surf.id))
        session.commit()

        return {
            "first": first.id,
            "second": second.id,
            "other": other.id,
            "beach": beach.id,
            "surf": surf.id,
        }


def tags_on(item_id):
    with db.new_session() as session:
        return sorted(
            session.exec(
                select(ItemTagLink.tag_id).where(ItemTagLink.item_id == item_id)
            ).all()
        )


class TestFindDuplicateUris:
    def test_reports_a_uri_held_by_two_items(self, library):
        found = db.find_duplicate_uris()
        assert list(found) == ["/p/a.jpg"]

    def test_the_ids_come_back_oldest_first(self, library):
        """The lowest id is the one that survives, so order is not cosmetic."""
        found = db.find_duplicate_uris()
        assert found["/p/a.jpg"] == sorted([library["first"], library["second"]])

    def test_a_unique_uri_is_not_reported(self, library):
        assert "/p/b.jpg" not in db.find_duplicate_uris()

    def test_a_clean_library_reports_nothing(self, temp_db):
        with Session(temp_db) as session:
            session.add(Item(uri="/p/only.jpg"))
            session.commit()
        assert db.find_duplicate_uris() == {}


class TestMergeItems:
    def test_the_tags_of_both_end_up_on_the_survivor(self, library):
        db.merge_items(library["first"], [library["second"]])
        assert tags_on(library["first"]) == sorted([library["beach"], library["surf"]])

    def test_the_duplicate_is_gone(self, library):
        db.merge_items(library["first"], [library["second"]])
        assert db.get_items_by_ids([library["second"]]) == []

    def test_the_survivor_remains(self, library):
        db.merge_items(library["first"], [library["second"]])
        assert db.get_items_by_ids([library["first"]])[0].uri == "/p/a.jpg"

    def test_a_tag_held_by_both_ends_as_one_link(self, library, temp_db):
        """ItemTagLink has a composite primary key, so a blind repoint would
        violate it when both rows already carry the same tag."""
        with Session(temp_db) as session:
            session.add(ItemTagLink(item_id=library["second"], tag_id=library["beach"]))
            session.commit()

        db.merge_items(library["first"], [library["second"]])
        links = tags_on(library["first"])
        assert len(links) == len(set(links))

    def test_it_reports_what_it_did(self, library):
        moved, removed = db.merge_items(library["first"], [library["second"]])
        assert (moved, removed) == (1, 1)


class TestMergeFillsInGaps:
    """The duplicate may know things the survivor does not."""

    def test_a_missing_date_is_taken_from_the_duplicate(self, library, temp_db):
        with Session(temp_db) as session:
            duplicate = session.get(Item, library["second"])
            duplicate.date = datetime(2021, 3, 7)
            session.add(duplicate)
            session.commit()

        db.merge_items(library["first"], [library["second"]])
        assert db.get_items_by_ids([library["first"]])[0].date == datetime(2021, 3, 7)

    def test_a_date_the_survivor_already_has_is_kept(self, library, temp_db):
        with Session(temp_db) as session:
            keeper = session.get(Item, library["first"])
            keeper.date = datetime(2020, 1, 1)
            duplicate = session.get(Item, library["second"])
            duplicate.date = datetime(2021, 3, 7)
            session.add(keeper)
            session.add(duplicate)
            session.commit()

        db.merge_items(library["first"], [library["second"]])
        assert db.get_items_by_ids([library["first"]])[0].date == datetime(2020, 1, 1)

    def test_a_missing_location_is_taken_from_the_duplicate(self, library, temp_db):
        with Session(temp_db) as session:
            duplicate = session.get(Item, library["second"])
            duplicate.latitude, duplicate.longitude = 40.7128, -74.0060
            session.add(duplicate)
            session.commit()

        db.merge_items(library["first"], [library["second"]])
        keeper = db.get_items_by_ids([library["first"]])[0]
        assert (keeper.latitude, keeper.longitude) == (40.7128, -74.0060)


class TestMergeMovesLineage:
    def test_a_parent_link_follows_the_survivor(self, library):
        db.set_parents(library["second"], [library["other"]])
        db.merge_items(library["first"], [library["second"]])
        assert db.get_parent_ids(library["first"]) == [library["other"]]

    def test_a_child_link_follows_the_survivor(self, library):
        db.set_parents(library["other"], [library["second"]])
        db.merge_items(library["first"], [library["second"]])
        assert db.get_parent_ids(library["other"]) == [library["first"]]

    def test_merging_does_not_make_an_item_its_own_parent(self, library):
        """The survivor and the duplicate are the same photo."""
        db.set_parents(library["second"], [library["first"]])
        db.merge_items(library["first"], [library["second"]])
        assert db.get_parent_ids(library["first"]) == []

    def test_no_lineage_rows_point_at_the_removed_item(self, library):
        db.set_parents(library["second"], [library["other"]])
        db.merge_items(library["first"], [library["second"]])
        with db.new_session() as session:
            rows = session.exec(select(ItemParentLink)).all()
        gone = library["second"]
        assert all(gone not in (r.child_id, r.parent_id) for r in rows)


class TestRefusals:
    def test_an_item_cannot_be_merged_into_itself(self, library):
        with pytest.raises(ValueError, match="itself"):
            db.merge_items(library["first"], [library["first"]])

    def test_merging_nothing_changes_nothing(self, library):
        assert db.merge_items(library["first"], []) == (0, 0)
        assert tags_on(library["first"]) == [library["beach"]]


class TestFindDuplicateTagNames:
    """get_tag folds case, so 'Beach' and 'beach' are one tag to every lookup
    but two rows in the table - and which one a query finds is arbitrary."""

    def test_names_differing_only_in_case_are_duplicates(self, temp_db):
        with Session(temp_db) as session:
            session.add(Tag(name="Beach"))
            session.add(Tag(name="beach"))
            session.commit()

        found = db.find_duplicate_tag_names()
        assert list(found) == ["beach"]

    def test_the_ids_come_back_oldest_first(self, temp_db):
        with Session(temp_db) as session:
            first = Tag(name="Beach")
            second = Tag(name="BEACH")
            session.add(first)
            session.add(second)
            session.commit()
            session.refresh(first)
            session.refresh(second)
            expected = [first.id, second.id]

        assert db.find_duplicate_tag_names()["beach"] == expected

    def test_distinct_names_are_not_duplicates(self, temp_db):
        with Session(temp_db) as session:
            session.add(Tag(name="Beach"))
            session.add(Tag(name="Surf"))
            session.commit()

        assert db.find_duplicate_tag_names() == {}

    def test_surrounding_space_counts_as_the_same_name(self, temp_db):
        """add_tag strips before storing, so a stored ' Beach' is the same tag."""
        with Session(temp_db) as session:
            session.add(Tag(name="Beach"))
            session.add(Tag(name=" beach "))
            session.commit()

        assert list(db.find_duplicate_tag_names()) == ["beach"]
