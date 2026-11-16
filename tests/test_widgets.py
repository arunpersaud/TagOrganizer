"""
Tests for widget fixes F5, F6, and F9.

Tests cover:
- F5: the delete dialog's photo previews
- F6: tag_view.py's tag menu
- F9: timeline.py histogram bin calculation fix
"""

from datetime import date, datetime

import matplotlib.dates as mdates

from tagorganizer.widgets.timeline import get_histogram_locator_and_bins


class TestF9HistogramLocatorAndBins:
    """Test F9: Timeline histogram bins calculation across different spans."""

    def test_one_week_span(self):
        """One-week span should use DayLocator with reasonable bins."""
        start = datetime(2025, 1, 1)
        end = datetime(2025, 1, 8)

        locator, bins = get_histogram_locator_and_bins(start, end)

        assert isinstance(locator, mdates.DayLocator)
        assert bins >= 1
        assert bins <= 7

    def test_three_month_span(self):
        """Three-month span should use MonthLocator."""
        start = datetime(2025, 1, 1)
        end = datetime(2025, 4, 1)

        locator, bins = get_histogram_locator_and_bins(start, end)

        assert isinstance(locator, mdates.MonthLocator)
        assert bins >= 1
        assert bins <= 365

    def test_three_year_span(self):
        """Three-year span should use MonthLocator."""
        start = datetime(2022, 1, 1)
        end = datetime(2025, 1, 1)

        locator, bins = get_histogram_locator_and_bins(start, end)

        assert isinstance(locator, mdates.MonthLocator)
        assert bins >= 1
        assert bins <= 365

    def test_twenty_year_span(self):
        """Twenty-year span should use YearLocator."""
        start = datetime(2005, 1, 1)
        end = datetime(2025, 3, 15)

        locator, bins = get_histogram_locator_and_bins(start, end)

        assert isinstance(locator, mdates.YearLocator)
        assert bins >= 1
        assert bins <= 365
        # For ~20 years, bins should be around 20
        assert bins >= 19
        assert bins <= 21

    def test_exact_problematic_case_2005_to_2025(self):
        """
        Test the exact case from F9 that was broken.

        2005-01-01 -> 2025-03-15 = 7378 days
        Old code: delta.days = 14 (just day component) -> DayLocator with bins=14
        New code: should use YearLocator with bins ~20
        """
        start = datetime(2005, 1, 1)
        end = datetime(2025, 3, 15)

        locator, bins = get_histogram_locator_and_bins(start, end)

        # Should NOT be DayLocator with 14 bins
        assert not isinstance(locator, mdates.DayLocator)
        assert isinstance(locator, mdates.YearLocator)

        # Verify the total span calculation
        total_days = (end - start).days
        assert total_days == 7378

        # Bins should be reasonable for 20 years
        assert bins >= 19 and bins <= 21

    def test_date_objects_conversion(self):
        """Test that date objects (not datetime) are handled correctly."""
        start_date = date(2025, 1, 1)
        end_date = date(2025, 1, 8)

        locator, bins = get_histogram_locator_and_bins(start_date, end_date)

        assert isinstance(locator, mdates.DayLocator)
        assert bins >= 1

    def test_single_day_span(self):
        """Single day or zero-span should have at least 1 bin."""
        start = datetime(2025, 1, 1)
        end = datetime(2025, 1, 1)

        locator, bins = get_histogram_locator_and_bins(start, end)

        assert bins >= 1

    def test_bins_capped_at_365(self):
        """Bins should never exceed 365 even for very long spans."""
        start = datetime(1900, 1, 1)
        end = datetime(2025, 1, 1)

        locator, bins = get_histogram_locator_and_bins(start, end)

        assert bins <= 365

    def test_boundary_30_days(self):
        """30-day boundary should use DayLocator."""
        start = datetime(2025, 1, 1)
        end = datetime(2025, 1, 31)

        locator, bins = get_histogram_locator_and_bins(start, end)

        assert isinstance(locator, mdates.DayLocator)

    def test_boundary_31_days(self):
        """31-day span should use MonthLocator (just over 30-day boundary)."""
        start = datetime(2025, 1, 1)
        end = datetime(2025, 2, 1)

        locator, bins = get_histogram_locator_and_bins(start, end)

        assert isinstance(locator, mdates.MonthLocator)

    def test_boundary_365_days(self):
        """365-day boundary should use MonthLocator."""
        start = datetime(2024, 1, 1)
        end = datetime(2025, 1, 1)

        locator, bins = get_histogram_locator_and_bins(start, end)

        assert isinstance(locator, mdates.MonthLocator)

    def test_boundary_366_days(self):
        """366-day span should use MonthLocator (just over 365-day boundary)."""
        start = datetime(2024, 1, 1)
        end = datetime(2025, 1, 2)

        locator, bins = get_histogram_locator_and_bins(start, end)

        assert isinstance(locator, mdates.MonthLocator)

    def test_boundary_5_years(self):
        """~4.5 year span should use MonthLocator."""
        start = datetime(2020, 6, 1)
        end = datetime(2025, 1, 1)

        locator, bins = get_histogram_locator_and_bins(start, end)

        assert isinstance(locator, mdates.MonthLocator)

    def test_boundary_5_years_plus_one_day(self):
        """Just over 5 years should use YearLocator."""
        start = datetime(2020, 1, 1)
        end = datetime(2025, 1, 2)

        locator, bins = get_histogram_locator_and_bins(start, end)

        assert isinstance(locator, mdates.YearLocator)


def _photo_file(path):
    from qtpy.QtGui import QImage

    image = QImage(40, 30, QImage.Format.Format_RGB32)
    image.fill(0x804020)
    assert image.save(str(path), "PNG")
    return str(path)


class TestF5DeleteConfirmationPreviews:
    """Each photo named in the delete dialog is previewed, or named if it cannot be.

    The preview used to be loaded with a keyword the loader does not take, which
    made the dialog fail to open at all.
    """

    def test_a_photo_is_previewed_as_a_picture(self, qapp, tmp_path):
        from types import SimpleNamespace

        from qtpy.QtWidgets import QLabel

        from tagorganizer.models import Item
        from tagorganizer.widgets.delete_confirmation_dialog import (
            DeleteConfirmationDialog,
        )

        photo = _photo_file(tmp_path / "p.png")
        main = SimpleNamespace(config=SimpleNamespace(photos=tmp_path))

        dialog = DeleteConfirmationDialog([Item(id=1, uri=photo)], main)

        pictures = [
            label
            for label in dialog.findChildren(QLabel)
            if not label.pixmap().isNull()
        ]
        assert len(pictures) == 1

    def test_a_photo_that_cannot_be_loaded_is_named_instead(self, qapp, tmp_path):
        from types import SimpleNamespace

        from qtpy.QtWidgets import QLabel

        from tagorganizer.models import Item
        from tagorganizer.widgets.delete_confirmation_dialog import (
            DeleteConfirmationDialog,
        )

        missing = str(tmp_path / "gone.jpg")
        main = SimpleNamespace(config=SimpleNamespace(photos=tmp_path))

        dialog = DeleteConfirmationDialog([Item(id=2, uri=missing)], main)

        assert missing in [label.text() for label in dialog.findChildren(QLabel)]


class TestF6TagViewMenuFix:
    """The tag menu is opened from the tag tree itself, and kept while it shows.

    The menu used to be looked up through an attribute the tag tree does not
    have, so right-clicking any tag raised instead of showing its menu.
    """

    def _recording_menus(self, monkeypatch):
        """Replace the menu class so exec records the menu instead of blocking."""
        import tagorganizer.widgets.tag_view as tag_view_module
        from qtpy.QtWidgets import QMenu

        shown = []

        class RecordingMenu(QMenu):
            def exec(self, *args):
                shown.append(self)

        monkeypatch.setattr(tag_view_module, "QMenu", RecordingMenu)
        return shown

    def test_right_clicking_a_tag_shows_its_menu(self, window_for, monkeypatch):
        from qtpy.QtCore import QPoint

        from tagorganizer import db

        window = window_for()
        db.add_tag("beach")
        window.tag_view.update_tags()
        index = window.tag_view.tag_model.index(0, 0)
        monkeypatch.setattr(window.tag_view, "indexAt", lambda position: index)
        shown = self._recording_menus(monkeypatch)

        window.tag_view.show_tag_menu(QPoint(3, 3))

        assert [action.text() for action in shown[0].actions()] == [
            "Remove from selected photos",
            "Delete Tag",
        ]

    def test_the_menu_is_kept_on_the_tag_view_while_it_is_shown(
        self, window_for, monkeypatch
    ):
        """A menu held only by a local name is freed when the call returns."""
        from qtpy.QtCore import QPoint

        from tagorganizer import db

        window = window_for()
        db.add_tag("beach")
        window.tag_view.update_tags()
        index = window.tag_view.tag_model.index(0, 0)
        monkeypatch.setattr(window.tag_view, "indexAt", lambda position: index)
        shown = self._recording_menus(monkeypatch)

        window.tag_view.show_tag_menu(QPoint(3, 3))

        assert window.tag_view.tag_menu is shown[0]

    def test_a_click_on_no_tag_shows_nothing(self, window_for, monkeypatch):
        from qtpy.QtCore import QModelIndex, QPoint

        window = window_for()
        monkeypatch.setattr(window.tag_view, "indexAt", lambda position: QModelIndex())
        shown = self._recording_menus(monkeypatch)

        window.tag_view.show_tag_menu(QPoint(3, 3))

        assert shown == []
