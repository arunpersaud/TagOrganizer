"""Combining filters with OR.

Every assertion here is on the *set of items returned* against a real database,
never on generated SQL. A SQL-shape assertion passes happily while the query
returns the wrong photos, which is the only failure that matters here.
"""

from datetime import datetime

import pytest
from sqlmodel import Session

from tagorganizer import db
from tagorganizer.models import Item, ItemTagLink, Tag
from tagorganizer.widgets.tag_bar import Condition, Filters


@pytest.fixture
def library(temp_db):
    """Four items and three tags, arranged so OR and AND give different answers.

    a: tag A, tag C, lat 1
    b: tag B, tag C, lat 2
    c: tag C,        lat 3
    d: no tags,      lat 50
    """
    with Session(temp_db) as session:
        items = {}
        for name, lat in (("a", 1.0), ("b", 2.0), ("c", 3.0), ("d", 50.0)):
            item = Item(
                uri=f"/p/{name}.jpg",
                latitude=lat,
                longitude=10.0,
                date=datetime(2024, 1, 1),
            )
            session.add(item)
            items[name] = item

        tags = {name: Tag(name=name) for name in ("A", "B", "C")}
        for tag in tags.values():
            session.add(tag)
        session.commit()

        for obj in (*items.values(), *tags.values()):
            session.refresh(obj)

        for item_name, tag_name in (
            ("a", "A"),
            ("b", "B"),
            ("c", "C"),
            ("a", "C"),
            ("b", "C"),
        ):
            session.add(
                ItemTagLink(item_id=items[item_name].id, tag_id=tags[tag_name].id)
            )
        session.commit()

        return {name: item.id for name, item in items.items()}


def names(filters):
    return sorted(item.uri.split("/")[-1][0] for item in db.get_images(0, filters))


class TestGroupsAreDisjunctions:
    def test_a_group_of_two_tags_returns_their_union(self, library):
        filters = Filters(groups=[[Condition("tag", "A"), Condition("tag", "B")]])
        assert names(filters) == ["a", "b"]

    def test_a_group_and_a_flat_filter_intersect(self, library):
        """(A or B) and C -- the example this feature exists for."""
        filters = Filters(
            tags=["C"],
            groups=[[Condition("tag", "A"), Condition("tag", "B")]],
        )
        assert names(filters) == ["a", "b"]

    def test_a_mixed_group_ors_across_chip_kinds(self, library):
        """A tag OR a map area: the point of grouping any chip, not just tags."""
        filters = Filters(
            groups=[
                [
                    Condition("tag", "A"),
                    Condition(
                        "area",
                        {
                            "min_latitude": 45.0,
                            "max_latitude": 55.0,
                            "min_longitude": 0.0,
                            "max_longitude": 20.0,
                        },
                    ),
                ]
            ]
        )
        assert names(filters) == ["a", "d"]

    def test_a_one_member_group_behaves_like_a_plain_filter(self, library):
        assert names(Filters(groups=[[Condition("tag", "A")]])) == ["a"]

    def test_no_groups_changes_nothing(self, library):
        assert names(Filters(groups=[])) == names(Filters())

    def test_two_groups_are_anded_together(self, library):
        """(A or B) and (C or A) -- both groups must hold."""
        filters = Filters(
            groups=[
                [Condition("tag", "A"), Condition("tag", "B")],
                [Condition("tag", "C"), Condition("tag", "A")],
            ]
        )
        assert names(filters) == ["a", "b"]


class TestConditionKindsMatchTheFlatFields:
    """Each extracted condition must return exactly what its flat field does."""

    def test_start_date(self, library):
        flat = Filters(start_date=datetime(2023, 1, 1))
        grouped = Filters(groups=[[Condition("start_date", datetime(2023, 1, 1))]])
        assert names(grouped) == names(flat)

    def test_no_gps(self, library, temp_db):
        with Session(temp_db) as session:
            session.add(Item(uri="/p/e.jpg"))
            session.commit()

        assert names(Filters(groups=[[Condition("no_gps", True)]])) == names(
            Filters(no_gps=True)
        )

    def test_item_ids(self, library):
        wanted = [library["a"], library["c"]]
        assert names(Filters(groups=[[Condition("item_ids", wanted)]])) == names(
            Filters(item_ids=wanted)
        )


class TestItemIdCollision:
    def test_two_id_conditions_raise_rather_than_answering_wrongly(self, library):
        """Both would materialise the same temp table; the second would win.

        Returning a confident wrong answer here is worse than refusing.
        """
        filters = Filters(
            groups=[
                [
                    Condition("item_ids", [library["a"]]),
                    Condition("item_ids", [library["b"]]),
                ]
            ]
        )
        with pytest.raises(ValueError, match="item_ids"):
            db.get_images(0, filters)


class TestFiltersEquality:
    def test_different_groups_compare_unequal(self):
        """update_items compares Filters to decide whether to redraw."""
        assert Filters(groups=[[Condition("tag", "A")]]) != Filters(
            groups=[[Condition("tag", "B")]]
        )

    def test_identical_groups_compare_equal(self):
        assert Filters(groups=[[Condition("tag", "A")]]) == Filters(
            groups=[[Condition("tag", "A")]]
        )
