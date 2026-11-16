"""The date filter's end bound is exclusive, because the tag bar labels it "<".

The timeline turns a dragged span into a "before" bound on the day after its
last day, so a photo taken at exactly midnight of that day belongs to the next
span, not this one.
"""

from datetime import date, datetime

from sqlmodel import Session

from tagorganizer import db
from tagorganizer.models import Item
from tagorganizer.widgets.tag_bar import Filters


def _uris(filters):
    return sorted(item.uri for item in db.get_images(0, filters))


def _add(temp_db, *items):
    with Session(temp_db) as session:
        session.add_all(items)
        session.commit()


class TestEndBoundIsExclusive:
    def test_a_datetime_bound_excludes_a_photo_at_its_exact_instant(self, temp_db):
        """The bound is exclusive for any value, not only for dates.

        With "<=" a datetime bound of 1 July 00:00 keeps a photo taken at that
        instant. The app passes dates, which already compare as exclusive, so
        this case is the one that would regress.
        """
        _add(
            temp_db,
            Item(uri="/p/before.jpg", date=datetime(2024, 6, 30, 23, 59)),
            Item(uri="/p/instant.jpg", date=datetime(2024, 7, 1, 0, 0)),
        )

        assert _uris(Filters(end_date=datetime(2024, 7, 1))) == ["/p/before.jpg"]


class TestTimelineEndDate:
    def test_a_photo_at_midnight_of_the_end_day_is_excluded(self, temp_db):
        """A "before 1 July" filter must not include a photo taken at 00:00 on 1 July.

        That photo is the first moment of the day the bound names, so it is not
        before it. Including it put one photo from the next day into every span
        that ended on the day before.
        """
        _add(
            temp_db,
            Item(uri="/p/before.jpg", date=datetime(2024, 6, 30, 23, 59)),
            Item(uri="/p/midnight.jpg", date=datetime(2024, 7, 1, 0, 0)),
        )

        assert _uris(Filters(end_date=date(2024, 7, 1))) == ["/p/before.jpg"]

    def test_photos_later_on_the_end_day_are_excluded(self, temp_db):
        _add(
            temp_db,
            Item(uri="/p/noon.jpg", date=datetime(2024, 7, 1, 12, 0)),
        )

        assert _uris(Filters(end_date=date(2024, 7, 1))) == []

    def test_the_start_of_a_range_stays_inclusive(self, temp_db):
        """Only the upper bound changes: a photo at the start instant is kept."""
        _add(
            temp_db,
            Item(uri="/p/start.jpg", date=datetime(2024, 6, 1, 0, 0)),
            Item(uri="/p/earlier.jpg", date=datetime(2024, 5, 31, 23, 59)),
        )

        filters = Filters(start_date=date(2024, 6, 1), end_date=date(2024, 7, 1))
        assert _uris(filters) == ["/p/start.jpg"]
