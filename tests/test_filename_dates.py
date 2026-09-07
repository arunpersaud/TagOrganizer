"""Reading a date out of a filename, when the file carries none itself.

This is the last resort in the date chain and the only one that is a guess, so
these tests lean hard on what it must refuse.
"""

from datetime import datetime

import pytest

from tagorganizer.metadata import date_from_filename


class TestCommonCameraPatterns:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("IMG_20210307_142530.jpg", datetime(2021, 3, 7, 14, 25, 30)),
            ("VID_20210307_142530.mp4", datetime(2021, 3, 7, 14, 25, 30)),
            ("20210307_142530.jpg", datetime(2021, 3, 7, 14, 25, 30)),
            ("IMG-20210307-WA0001.jpg", datetime(2021, 3, 7)),
            ("2021-03-07 12.34.56.png", datetime(2021, 3, 7, 12, 34, 56)),
            ("2021-03-07.jpg", datetime(2021, 3, 7)),
            ("Screenshot 2021-03-07 at 14.25.30.png", datetime(2021, 3, 7, 14, 25, 30)),
            ("PXL_20210307_142530123.jpg", datetime(2021, 3, 7, 14, 25, 30)),
        ],
    )
    def test_recognised_patterns(self, name, expected):
        assert date_from_filename(name) == expected


class TestRejections:
    @pytest.mark.parametrize(
        "name",
        [
            "holiday.jpg",
            "IMG_1234.jpg",
            "20213307_142530.jpg",  # month 33
            "20210332_142530.jpg",  # day 32
            "12345678.jpg",  # digits, but month 56
            "",
        ],
    )
    def test_nothing_is_invented(self, name):
        """A wrong date silently misfiles a photo, so refuse when unsure."""
        assert date_from_filename(name) is None

    def test_an_implausible_year_is_refused(self):
        assert date_from_filename("IMG_18010307_142530.jpg") is None

    def test_a_future_year_is_refused(self):
        assert date_from_filename("IMG_29900307_142530.jpg") is None

    def test_an_impossible_time_falls_back_to_the_date_alone(self):
        """The trailing digits are not a time, but the date is still a date.

        Same shape as IMG-20210307-WA0001, where the suffix is a sequence
        number rather than a clock. Dropping the whole name over it would lose
        a date that is plainly there.
        """
        assert date_from_filename("IMG_20210307_992530.jpg") == datetime(2021, 3, 7)


class TestAmbiguity:
    def test_the_first_plausible_date_wins(self):
        """Deterministic when a name carries two dates."""
        assert date_from_filename("2021-03-07_copy_2022-05-09.jpg") == datetime(
            2021, 3, 7
        )

    def test_a_time_is_preferred_over_the_bare_date(self):
        """The more precise reading of the same name, not an earlier match."""
        assert date_from_filename("20210307_142530.jpg") == datetime(
            2021, 3, 7, 14, 25, 30
        )
