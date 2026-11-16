"""Item.date holds naive local time and must come back exactly as written.

sqlmodel 0.0.50 maps a plain datetime field to a timezone-aware column that
refuses naive values, and every item date the app writes is naive local time
(see metadata.py). The model therefore declares NaiveDatetime. These tests
pin that a naive date round-trips unchanged and that the column does not
convert it to UTC.
"""

from datetime import datetime

from sqlmodel import Session, select

from tagorganizer.models import Item


def test_a_naive_date_round_trips_unchanged(temp_db):
    when = datetime(2024, 7, 1, 9, 30, 15)
    with Session(temp_db) as session:
        session.add(Item(uri="/p/a.jpg", date=when))
        session.commit()

    with Session(temp_db) as session:
        item = session.exec(select(Item)).one()

    assert item.date == when
    assert item.date.tzinfo is None


def test_the_date_column_has_no_timezone(temp_db):
    assert Item.__table__.c.date.type.timezone is False
