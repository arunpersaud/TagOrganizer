"""Two selection filters in one query must each answer for their own set.

A top-level selection and a selection chip inside an OR group both materialise
ids into a temporary table. When they shared one table, whichever was written
last answered for both, so the query returned photos the user had excluded.
"""

from sqlmodel import Session

from tagorganizer import db
from tagorganizer.models import Item
from tagorganizer.widgets.tag_bar import Condition, Filters


def _ids_returned(filters):
    return sorted(item.id for item in db.get_images(0, filters))


def test_a_grouped_selection_does_not_overwrite_the_top_level_one(temp_db):
    with Session(temp_db) as session:
        session.add_all(Item(uri=f"/p/{i}.jpg") for i in range(1, 4))
        session.commit()

    # Item 1 is selected; the group asks for item 2 or a tag that does not
    # exist. Nothing satisfies both, so the answer is empty.
    filters = Filters(
        item_ids=[1],
        groups=[[Condition("item_ids", [2]), Condition("tag", "No such tag")]],
    )
    assert _ids_returned(filters) == []


def test_both_selections_apply_when_they_overlap(temp_db):
    with Session(temp_db) as session:
        session.add_all(Item(uri=f"/p/{i}.jpg") for i in range(1, 4))
        session.commit()

    filters = Filters(
        item_ids=[1, 2],
        groups=[[Condition("item_ids", [2, 3]), Condition("tag", "No such tag")]],
    )
    assert _ids_returned(filters) == [2]
