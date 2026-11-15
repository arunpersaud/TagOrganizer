"""Tag hierarchies must stay trees.

A tag that is its own ancestor makes filtering recurse forever and merging
loop. Writes refuse to create one. Reads must also survive one, because
databases written before the refusal existed can already hold a cycle.
"""

import pytest
from sqlalchemy import text

from tagorganizer import db


def _parent_of(engine, name):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT parent_id FROM tag WHERE name = :n"), {"n": name}
        ).one()
        return row[0]


def _id_of(name):
    return db.get_tag(name).id


def _loaded(name):
    """A tag as the UI holds it: loaded from the database, detached."""
    return db.get_tag(name)


def _force_parent(engine, child_name, parent_id):
    """Write a parent link directly, bypassing the checks under test."""
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE tag SET parent_id = :p WHERE name = :n"),
            {"p": parent_id, "n": child_name},
        )


class TestPlacingATag:
    def test_a_tag_can_be_placed_under_another(self, temp_db):
        db.add_tag("Travel")
        db.add_tag("Japan")
        db.set_parent_tag(_loaded("Japan"), _loaded("Travel"))
        assert _parent_of(temp_db, "Japan") == _id_of("Travel")

    def test_none_makes_a_tag_top_level(self, temp_db):
        """The tag view calls this for a drop at top level."""
        travel, japan = db.add_tag("Travel"), db.add_tag("Japan")
        db.set_parent_tag_by_id(japan, travel)
        db.set_parent_tag(_loaded("Japan"), None)
        assert _parent_of(temp_db, "Japan") is None

    def test_by_id_none_makes_a_tag_top_level(self, temp_db):
        travel, japan = db.add_tag("Travel"), db.add_tag("Japan")
        db.set_parent_tag_by_id(japan, travel)
        db.set_parent_tag_by_id(japan, None)
        assert _parent_of(temp_db, "Japan") is None

    def test_a_tag_cannot_be_its_own_parent(self, temp_db):
        travel = db.add_tag("Travel")
        with pytest.raises(ValueError):
            db.set_parent_tag_by_id(travel, travel)

    def test_a_tag_cannot_go_under_its_own_descendant(self, temp_db):
        travel, japan = db.add_tag("Travel"), db.add_tag("Japan")
        db.set_parent_tag_by_id(japan, travel)
        with pytest.raises(ValueError):
            db.set_parent_tag_by_id(travel, japan)
        assert _parent_of(temp_db, "Travel") is None

    def test_a_cycle_through_several_levels_is_refused(self, temp_db):
        a, b, c = db.add_tag("A"), db.add_tag("B"), db.add_tag("C")
        db.set_parent_tag_by_id(b, a)
        db.set_parent_tag_by_id(c, b)
        with pytest.raises(ValueError):
            db.set_parent_tag(_loaded("A"), _loaded("C"))
        assert _parent_of(temp_db, "A") is None


class TestReadingAHierarchyThatAlreadyHasACycle:
    @pytest.fixture
    def cyclic(self, temp_db):
        db.add_tag("a")
        db.add_tag("b")
        db.add_tag("unrelated")
        _force_parent(temp_db, "a", _id_of("b"))
        _force_parent(temp_db, "b", _id_of("a"))
        return temp_db

    def test_get_all_tag_ids_terminates_and_finds_the_cycle(self, cyclic):
        assert sorted(db.get_all_tag_ids(["a"])) == sorted([_id_of("a"), _id_of("b")])

    def test_a_filter_on_a_cyclic_tag_returns(self, cyclic):
        from tagorganizer.widgets.tag_bar import Filters

        assert db.get_number_of_items(Filters(tags=["a"])) == 0

    def test_merging_a_tag_out_of_a_cycle_terminates(self, cyclic):
        db.merge_tags(_id_of("a"), _id_of("unrelated"))
        assert db.get_tag("a") is None
        assert _parent_of(cyclic, "b") == _id_of("unrelated")


class TestAHealthyHierarchyStillExpands:
    def test_children_are_included_at_any_depth(self, temp_db):
        a, b, c = db.add_tag("A"), db.add_tag("B"), db.add_tag("C")
        db.set_parent_tag_by_id(b, a)
        db.set_parent_tag_by_id(c, b)
        assert sorted(db.get_all_tag_ids(["A"])) == sorted([a, b, c])
