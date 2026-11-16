"""Recording that one photo was derived from others.

A panorama has several sources; an edit has one. Both are the same relationship,
so a photo may have any number of parents and any number of children.
"""

import pytest
from sqlmodel import Session

from tagorganizer import db
from tagorganizer.models import Item


@pytest.fixture
def photos(temp_db):
    with Session(temp_db) as session:
        items = [Item(uri=f"/p/{i}.jpg") for i in range(5)]
        for item in items:
            session.add(item)
        session.commit()
        for item in items:
            session.refresh(item)
        return [item.id for item in items]


class TestSetParents:
    def test_a_panorama_records_several_sources(self, photos):
        db.set_parents(photos[0], photos[1:4])
        assert sorted(db.get_parent_ids(photos[0])) == sorted(photos[1:4])

    def test_an_edit_records_one_source(self, photos):
        db.set_parents(photos[0], [photos[1]])
        assert db.get_parent_ids(photos[0]) == [photos[1]]

    def test_setting_replaces_rather_than_appends(self, photos):
        db.set_parents(photos[0], [photos[1]])
        db.set_parents(photos[0], [photos[2]])
        assert db.get_parent_ids(photos[0]) == [photos[2]]

    def test_an_empty_list_clears_the_lineage(self, photos):
        db.set_parents(photos[0], [photos[1]])
        db.set_parents(photos[0], [])
        assert db.get_parent_ids(photos[0]) == []

    def test_duplicate_parents_are_recorded_once(self, photos):
        db.set_parents(photos[0], [photos[1], photos[1]])
        assert db.get_parent_ids(photos[0]) == [photos[1]]


class TestChildren:
    def test_a_source_knows_what_came_from_it(self, photos):
        db.set_parents(photos[0], [photos[1]])
        db.set_parents(photos[2], [photos[1]])
        assert sorted(db.get_child_ids(photos[1])) == sorted([photos[0], photos[2]])

    def test_a_photo_with_no_children(self, photos):
        assert db.get_child_ids(photos[4]) == []


class TestCycles:
    def test_a_photo_cannot_be_its_own_parent(self, photos):
        with pytest.raises(ValueError, match="itself"):
            db.set_parents(photos[0], [photos[0]])

    def test_a_photo_cannot_be_its_own_ancestor(self, photos):
        """b derives from a; a must not then derive from b.

        Lineage is meant to lead back to an original, so a loop would make
        'where did this come from' unanswerable.
        """
        db.set_parents(photos[1], [photos[0]])
        with pytest.raises(ValueError, match=r"ancestor|descendant|cycle"):
            db.set_parents(photos[0], [photos[1]])

    def test_a_deeper_cycle_is_refused(self, photos):
        db.set_parents(photos[1], [photos[0]])
        db.set_parents(photos[2], [photos[1]])
        with pytest.raises(ValueError, match=r"ancestor|descendant|cycle"):
            db.set_parents(photos[0], [photos[2]])

    def test_a_refused_link_changes_nothing(self, photos):
        db.set_parents(photos[1], [photos[0]])
        with pytest.raises(ValueError):
            db.set_parents(photos[0], [photos[1]])
        assert db.get_parent_ids(photos[0]) == []
        assert db.get_parent_ids(photos[1]) == [photos[0]]

    def test_a_diamond_is_allowed(self, photos):
        """Two edits of one original, then a panorama of both. Not a cycle."""
        db.set_parents(photos[1], [photos[0]])
        db.set_parents(photos[2], [photos[0]])
        db.set_parents(photos[3], [photos[1], photos[2]])
        assert sorted(db.get_parent_ids(photos[3])) == sorted([photos[1], photos[2]])


class TestIndicatorQuery:
    def test_reports_which_of_a_page_have_parents(self, photos):
        """The grid needs this once per page, not once per tile."""
        db.set_parents(photos[0], [photos[1]])
        db.set_parents(photos[2], [photos[1]])

        assert db.get_items_with_parents(photos) == {photos[0], photos[2]}

    def test_empty_input(self, photos):
        assert db.get_items_with_parents([]) == set()


class TestDeletingAPhoto:
    def test_deleting_a_photo_removes_its_lineage_links(self, photos):
        """Otherwise the links dangle and the indicator lies."""
        db.set_parents(photos[0], [photos[1]])
        db.delete_item(photos[1])
        assert db.get_parent_ids(photos[0]) == []


class TestParentSummary:
    def test_maps_each_derived_photo_to_its_source_names(self, photos):
        """The grid needs names for the tooltip, in one query per page."""
        db.set_parents(photos[0], [photos[1], photos[2]])

        summary = db.get_parent_summary(photos)

        assert sorted(summary[photos[0]]) == ["/p/1.jpg", "/p/2.jpg"]

    def test_photos_without_sources_are_absent(self, photos):
        db.set_parents(photos[0], [photos[1]])
        summary = db.get_parent_summary(photos)
        assert photos[3] not in summary

    def test_empty_input(self, photos):
        assert db.get_parent_summary([]) == {}


class TestChoosingTheSources:
    """Deciding what a 'mark as derived' action should do, without Qt."""

    def check(self, current, selected):
        from tagorganizer.main import lineage_targets

        return lineage_targets(current, selected)

    def test_the_selection_becomes_the_sources(self):
        assert self.check(1, [2, 3]) == ([2, 3], None)

    def test_the_current_photo_is_not_its_own_source(self):
        """Selecting everything including the result should still work."""
        assert self.check(1, [1, 2, 3]) == ([2, 3], None)

    def test_refuses_with_no_current_photo(self):
        parents, error = self.check(None, [2, 3])
        assert parents == [] and "photo" in error.lower()

    def test_refuses_with_an_empty_selection(self):
        parents, error = self.check(1, [])
        assert parents == [] and "select" in error.lower()

    def test_refuses_when_only_the_current_photo_is_selected(self):
        """Dropping it leaves nothing, so say so rather than silently clearing."""
        parents, error = self.check(1, [1])
        assert parents == [] and error is not None
