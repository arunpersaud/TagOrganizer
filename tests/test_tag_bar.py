"""Behavioural tests for the tag bar's filter buttons.

TagBar builds real QPushButtons, so it needs a QApplication; guarded the same
way as the other Qt-touching test modules.
"""

import os
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    widgets = pytest.importorskip("qtpy.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


class _DummyConfig:
    photos = Path("/photos")
    videos = Path("/videos")


class _DummyMain:
    """Counts refreshes, because how many happen is the point of one test."""

    def __init__(self):
        self.config = _DummyConfig()
        self.update_items_calls = 0

    def update_items(self):
        self.update_items_calls += 1


def _tag_bar():
    from tagorganizer.widgets.tag_bar import TagBar

    return TagBar(_DummyMain())


class TestSetTimeRange:
    def test_sets_both_bounds(self, qapp):
        bar = _tag_bar()
        bar.set_time_range(date(2024, 1, 1), date(2024, 6, 30))

        filters = bar.get_filters()
        assert filters.start_date == date(2024, 1, 1)
        assert filters.end_date == date(2024, 6, 30)

    def test_refreshes_the_view_only_once(self, qapp):
        """Dragging a range must not redraw the whole library twice.

        add_time_tag calls update_items itself, so setting the two bounds with
        two calls costs two full refreshes - visible on a large library.
        """
        bar = _tag_bar()
        bar.main.update_items_calls = 0
        bar.set_time_range(date(2024, 1, 1), date(2024, 6, 30))

        assert bar.main.update_items_calls == 1

    def test_replaces_a_previous_range_rather_than_stacking(self, qapp):
        bar = _tag_bar()
        bar.set_time_range(date(2024, 1, 1), date(2024, 6, 30))
        bar.set_time_range(date(2020, 3, 1), date(2020, 4, 1))

        filters = bar.get_filters()
        assert filters.start_date == date(2020, 3, 1)
        assert filters.end_date == date(2020, 4, 1)

    def test_orders_the_bounds(self, qapp):
        """A drag right-to-left still means the same span."""
        bar = _tag_bar()
        bar.set_time_range(date(2024, 6, 30), date(2024, 1, 1))

        filters = bar.get_filters()
        assert filters.start_date == date(2024, 1, 1)
        assert filters.end_date == date(2024, 6, 30)


class TestClearTimeRange:
    def test_removes_both_bounds(self, qapp):
        bar = _tag_bar()
        bar.set_time_range(date(2024, 1, 1), date(2024, 6, 30))
        bar.clear_time_range()

        filters = bar.get_filters()
        assert filters.start_date is None
        assert filters.end_date is None

    def test_is_quiet_when_no_range_is_set(self, qapp):
        bar = _tag_bar()
        bar.clear_time_range()
        assert bar.get_filters().start_date is None
