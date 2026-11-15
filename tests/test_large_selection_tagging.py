"""Tagging a selection larger than SQLite's bound-variable cap.

SQLite refuses a statement with more than 32766 bound variables, and a single
IN clause over a selection binds one variable per id. A map "select visible"
on a big library can produce such a selection, so tagging has to work in
chunks. Each test uses 33,000 items, just over the cap.
"""

import pytest
from sqlalchemy import insert
from sqlmodel import Session, select

from tagorganizer import db
from tagorganizer.models import Item, ItemTagLink

COUNT = 33_000


@pytest.fixture
def library(temp_db):
    with Session(temp_db) as session:
        session.execute(
            insert(Item.__table__),
            [{"uri": f"/p/{i}.jpg"} for i in range(COUNT)],
        )
        session.commit()
        ids = session.exec(select(Item.id)).all()
    return [Item(id=i) for i in ids]


def _link_count(engine):
    with Session(engine) as session:
        return len(session.exec(select(ItemTagLink)).all())


def test_set_tags_reaches_every_item_in_a_large_selection(library, temp_db):
    db.add_tag("Beach")
    beach = db.get_tag("Beach")

    db.set_tags(library, [beach])

    assert _link_count(temp_db) == COUNT


def test_get_common_tags_sees_every_item_in_a_large_selection(library, temp_db):
    db.add_tag("Beach")
    db.set_tags(library, [db.get_tag("Beach")])

    assert db.get_common_tags(library) == ["Beach"]


def test_remove_tags_takes_every_link_off_a_large_selection(library, temp_db):
    db.add_tag("Beach")
    beach = db.get_tag("Beach")
    db.set_tags(library, [beach])

    removed = db.remove_tags(library, [beach])

    assert removed == COUNT
    assert _link_count(temp_db) == 0
