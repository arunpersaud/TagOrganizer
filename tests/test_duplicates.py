"""The Duplicates filter: photos with a byte-identical copy in the library.

Copies share a full-file content hash, which the hashing task fills in after
every import. Assertions are on what a real database returns.
"""

from datetime import datetime

import pytest
from sqlmodel import Session

from tagorganizer import db
from tagorganizer.models import Item
from tagorganizer.widgets.tag_bar import Condition, Filters


@pytest.fixture
def library(temp_db):
    """Two copy pairs, a unique photo, and two not hashed yet.

    a1/a2: same content, a2 dated by its filename a day later
    b1/b2: same content, dated in between
    solo:  no copy
    new1/new2: not hashed yet (empty hash)
    """
    rows = [
        ("a1", "aaa", datetime(2020, 1, 1)),
        ("a2", "aaa", datetime(2020, 1, 3)),
        ("b1", "bbb", datetime(2020, 1, 2)),
        ("b2", "bbb", datetime(2020, 1, 2)),
        ("solo", "ccc", datetime(2020, 1, 4)),
        ("new1", "", None),
        ("new2", "", None),
    ]
    with Session(temp_db) as session:
        for name, digest, when in rows:
            session.add(Item(uri=f"/p/{name}.jpg", data_xxhash=digest, date=when))
        session.commit()


def names(filters):
    return [item.uri.split("/")[-1][:-4] for item in db.get_images(0, filters)]


def test_only_photos_with_a_copy_are_shown(library):
    assert sorted(names(Filters(duplicates=True))) == ["a1", "a2", "b1", "b2"]


def test_photos_not_hashed_yet_are_not_copies_of_each_other(library):
    assert "new1" not in names(Filters(duplicates=True))


def test_copies_sit_together_newest_group_first(library):
    """a2 is newer than b1/b2 but a1 is older; the pair stays together."""
    assert names(Filters(duplicates=True)) == ["a1", "a2", "b1", "b2"]


def test_every_paging_query_uses_the_same_order(library):
    """The single view and shift-click ranges page through get_image_range."""
    filters = Filters(duplicates=True)
    paged = [item.uri for item in db.get_image_range(0, 10, filters)]
    assert paged == [item.uri for item in db.get_images(0, filters)]
    dates, _ = db.get_times_and_location_from_images(filters)
    assert dates == [item.date for item in db.get_images(0, filters)]


def test_without_the_filter_the_order_is_by_date(library):
    assert names(Filters())[:3] == ["solo", "a2", "b1"]


def test_it_ors_with_another_condition(library):
    filters = Filters(
        groups=[[Condition("duplicates", True), Condition("no_time", True)]]
    )
    assert sorted(names(filters)) == ["a1", "a2", "b1", "b2", "new1", "new2"]


def test_copies_stay_together_when_the_chip_is_in_a_group(library):
    filters = Filters(groups=[[Condition("duplicates", True)]])
    assert names(filters) == ["a1", "a2", "b1", "b2"]
