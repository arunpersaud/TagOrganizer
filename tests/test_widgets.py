"""
Tests for widget fixes F5, F6, and F9.

Tests cover:
- F5: delete_confirmation_dialog.py keyword argument fix
- F6: tag_view.py self.tag_view attribute fix
- F9: timeline.py histogram bin calculation fix
"""

import ast
from datetime import datetime, date
from pathlib import Path

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


class TestF5DeleteConfirmationDialogSignature:
    """Test F5: Verify delete_confirmation_dialog uses correct keyword argument."""

    def test_load_pixmap_call_uses_correct_keyword(self):
        """
        Verify that the load_pixmap call in delete_confirmation_dialog
        uses the correct keyword argument 'photos_path' not 'photos_dir'.
        """
        # Read the delete_confirmation_dialog.py source
        dialog_path = (
            Path(__file__).parent.parent
            / "src/tagorganizer/widgets/delete_confirmation_dialog.py"
        )
        with open(dialog_path) as f:
            source = f.read()

        # Parse and check for load_pixmap call
        tree = ast.parse(source)

        found_correct_call = False
        found_incorrect_call = False

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check if this is a load_pixmap call
                if isinstance(node.func, ast.Name) and node.func.id == "load_pixmap":
                    # Check keyword arguments
                    for keyword in node.keywords:
                        if keyword.arg == "photos_path":
                            found_correct_call = True
                        if keyword.arg == "photos_dir":
                            found_incorrect_call = True

        assert found_correct_call, "load_pixmap should use 'photos_path' keyword"
        assert (
            not found_incorrect_call
        ), "load_pixmap should NOT use 'photos_dir' keyword"

    def test_pixmap_none_guard_present(self):
        """Verify that setPixmap is guarded against None pixmap."""
        dialog_path = (
            Path(__file__).parent.parent
            / "src/tagorganizer/widgets/delete_confirmation_dialog.py"
        )
        with open(dialog_path) as f:
            source = f.read()

        # Check that there's a guard for None pixmap
        assert (
            "if pixmap:" in source or "if pixmap is not None:" in source
        ), "setPixmap call should be guarded against None"


class TestF6TagViewMenuFix:
    """Test F6: Verify tag_view.py no longer references self.tag_view in show_tag_menu."""

    def test_show_tag_menu_no_self_tag_view_reference(self):
        """
        Verify that show_tag_menu method doesn't reference self.tag_view.
        TagView IS the QTreeView and should use self directly.
        """
        tag_view_path = (
            Path(__file__).parent.parent / "src/tagorganizer/widgets/tag_view.py"
        )
        with open(tag_view_path) as f:
            source = f.read()

        # Parse and find show_tag_menu method
        tree = ast.parse(source)

        show_tag_menu_found = False
        tag_view_reference_found = False

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "show_tag_menu":
                show_tag_menu_found = True

                # Check the function body for self.tag_view references
                for child in ast.walk(node):
                    if isinstance(child, ast.Attribute):
                        if isinstance(child.value, ast.Attribute):
                            # Check for self.tag_view
                            if (
                                isinstance(child.value.value, ast.Name)
                                and child.value.value.id == "self"
                                and child.value.attr == "tag_view"
                            ):
                                tag_view_reference_found = True

        assert show_tag_menu_found, "show_tag_menu method should exist"
        assert (
            not tag_view_reference_found
        ), "show_tag_menu should NOT reference self.tag_view"

    def test_show_tag_menu_uses_self_directly(self):
        """Verify that show_tag_menu uses self.indexAt and self.viewport."""
        tag_view_path = (
            Path(__file__).parent.parent / "src/tagorganizer/widgets/tag_view.py"
        )
        with open(tag_view_path) as f:
            source = f.read()

        # Simple string check for the correct method calls
        assert (
            "self.indexAt(position)" in source
        ), "show_tag_menu should call self.indexAt(position)"
        assert "self.viewport()" in source, "show_tag_menu should call self.viewport()"

    def test_tag_menu_reference_stored(self):
        """Verify that QMenu is stored as self.tag_menu to avoid garbage collection."""
        tag_view_path = (
            Path(__file__).parent.parent / "src/tagorganizer/widgets/tag_view.py"
        )
        with open(tag_view_path) as f:
            source = f.read()

        # Check that menu is assigned to self.tag_menu
        assert (
            "self.tag_menu = QMenu()" in source
        ), "QMenu should be assigned to self.tag_menu to keep a reference"
