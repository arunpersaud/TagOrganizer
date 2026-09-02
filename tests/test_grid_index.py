"""Tests for ImageGridWidget index calculations.

This module tests the widget index calculation to ensure that the frame
highlight and current_item always point to the same widget, across various
page and item count combinations.

The index calculation is extracted as a pure function to avoid GUI dependencies.
"""

import textwrap

import pytest

from tagorganizer.widgets.image_grid_widget import ImageGridWidget


def get_widget_index(highlight, N, widget_count):
    """Calculate the widget index for a given highlight position.

    Args:
        highlight: The global highlight position
        N: The page size (columns * rows)
        widget_count: The number of widgets currently displayed

    Returns:
        The index of the widget on the current page (0-based)
    """
    if widget_count == 0:
        return 0
    n = highlight % N
    return min(n, widget_count - 1)


class TestWidgetIndexCalculation:
    """Test the widget index calculation logic."""

    def test_get_widget_index_empty(self):
        """Test with no widgets."""
        result = get_widget_index(highlight=0, N=25, widget_count=0)
        assert result == 0

    def test_get_widget_index_full_page(self):
        """Test on a full page (25 items shown, 25 item page size)."""
        N = 25
        widget_count = 25
        for highlight in range(25):
            result = get_widget_index(highlight, N, widget_count)
            # On a full first page, highlight should directly map
            assert result == highlight

    def test_get_widget_index_full_page_page2(self):
        """Test on a full second page (items 25-49)."""
        N = 25
        widget_count = 25
        # On page 2, global highlights 25-49 should map to local indices 0-24
        for local_idx in range(25):
            highlight = 25 + local_idx
            result = get_widget_index(highlight, N, widget_count)
            assert (
                result == local_idx
            ), f"highlight={highlight}, expected {local_idx}, got {result}"

    def test_get_widget_index_short_page(self):
        """Test on a short final page (12 items shown, 25 item page size).

        This is the critical case from the bug report:
        37 items, page 1, 12 widgets on screen.
        """
        N = 25
        widget_count = 12
        # Page 1, highlight 25-36 should map to indices 0-11
        for local_idx in range(12):
            highlight = 25 + local_idx
            result = get_widget_index(highlight, N, widget_count)
            assert result == local_idx

    def test_get_widget_index_37_items_critical_cases(self):
        """Test the specific failing cases from the bug report.

        37 items total, 25-item pages, 12 widgets on final page.
        - highlight=28: should be widget[3]
        - highlight=29: should be widget[4]
        - highlight=33: should be widget[8]
        """
        N = 25
        widget_count = 12
        cases = [
            (28, 3),
            (29, 4),
            (33, 8),
        ]
        for highlight, expected_idx in cases:
            result = get_widget_index(highlight, N, widget_count)
            assert (
                result == expected_idx
            ), f"highlight={highlight}: expected widget[{expected_idx}], got widget[{result}]"

    def test_get_widget_index_clamping(self):
        """Test that indices are clamped to available widgets."""
        N = 25
        widget_count = 5  # Only 5 widgets displayed
        # highlight=24 (last position on page 0) maps to 24 % 25 = 24, clamped to min(24, 4) = 4
        result = get_widget_index(24, N, widget_count)
        assert result == 4
        # highlight=25 (first position on page 1) maps to 25 % 25 = 0, clamped to min(0, 4) = 0
        result = get_widget_index(25, N, widget_count)
        assert result == 0

    @pytest.mark.parametrize(
        "total_items,page_size,highlight",
        [
            (10, 5, 0),
            (10, 5, 4),
            (10, 5, 5),
            (10, 5, 9),
            (37, 25, 0),
            (37, 25, 24),
            (37, 25, 25),
            (37, 25, 36),
            (100, 25, 0),
            (100, 25, 50),
            (100, 25, 99),
            (1000, 30, 0),
            (1000, 30, 100),
            (1000, 30, 999),
        ],
    )
    def test_index_consistency_within_page(self, total_items, page_size, highlight):
        """Test that index calculation is consistent for any highlight within total items.

        Given a page size N and a total number of items, verify that:
        - The calculated index is always valid (0 <= index < widget_count)
        - Within a page, the index changes smoothly
        """
        # Simulate a full page
        widget_count = min(
            page_size, total_items - (highlight // page_size) * page_size
        )
        if widget_count == 0:
            widget_count = 1  # At least one widget exists

        result = get_widget_index(highlight, page_size, widget_count)
        assert 0 <= result < widget_count, (
            f"Invalid index {result} for widget_count={widget_count}, "
            f"highlight={highlight}, page_size={page_size}"
        )

    def test_consistency_table_driven(self):
        """Table-driven test over many (total, page, N, highlight) combinations."""
        test_cases = [
            # (total_items, page_size, num_widgets_on_page, highlight, expected_index)
            # Full first page (25 items, page size 25)
            (25, 25, 25, 0, 0),
            (25, 25, 25, 12, 12),
            (25, 25, 25, 24, 24),
            # Full second page
            (50, 25, 25, 25, 0),
            (50, 25, 25, 37, 12),
            (50, 25, 25, 49, 24),
            # Short final page (37 items, page 1)
            (37, 25, 12, 25, 0),
            (37, 25, 12, 28, 3),
            (37, 25, 12, 29, 4),
            (37, 25, 12, 33, 8),
            (37, 25, 12, 36, 11),
            # 10 items total, page size 5
            (10, 5, 5, 0, 0),
            (10, 5, 5, 4, 4),
            (10, 5, 5, 5, 0),
            (10, 5, 5, 9, 4),
            # Varying page sizes and short pages
            (12, 10, 10, 0, 0),
            (12, 10, 10, 9, 9),
            (12, 10, 2, 10, 0),
            (12, 10, 2, 11, 1),
            # Edge case: 100 items, page size 30
            (100, 30, 30, 0, 0),
            (100, 30, 30, 29, 29),
            (100, 30, 30, 30, 0),
            (100, 30, 30, 59, 29),
            (100, 30, 10, 60, 0),  # Short page
            (100, 30, 10, 69, 9),  # Short page
            # Edge case: single widget
            (1, 25, 1, 0, 0),
            # Edge case: more widgets than items
            (5, 10, 5, 0, 0),
            (5, 10, 5, 4, 4),
        ]
        for total, N, widget_count, highlight, expected in test_cases:
            result = get_widget_index(highlight, N, widget_count)
            assert result == expected, (
                f"Failed for total={total}, N={N}, widget_count={widget_count}, "
                f"highlight={highlight}: expected {expected}, got {result}"
            )

    def test_frame_and_current_item_agree_conceptually(self):
        """Verify the formula matches between decorator and current_item.

        This test documents the correct formula:
        - Position within page: highlight % N
        - Clamp to available widgets: min(position, widget_count - 1)
        """
        test_cases = [
            # (N, widget_count, highlight, expected_index)
            (25, 25, 0, 0),
            (25, 25, 24, 24),
            (25, 25, 25, 0),  # wraps to next page
            (25, 25, 49, 24),
            (25, 12, 25, 0),  # short page
            (25, 12, 28, 3),
            (25, 12, 36, 11),
        ]
        for N, widget_count, highlight, expected in test_cases:
            idx = get_widget_index(highlight, N, widget_count)
            assert idx == expected, (
                f"Formula mismatch: N={N}, widget_count={widget_count}, "
                f"highlight={highlight}: expected {expected}, got {idx}"
            )


class TestGridIndexEdgeCases:
    """Additional edge case tests."""

    def test_zero_widget_count(self):
        """Test graceful handling of zero widgets."""
        result = get_widget_index(10, 25, 0)
        assert result == 0

    def test_highlight_zero_various_sizes(self):
        """Test highlight=0 with various page and widget sizes."""
        cases = [(25, 25), (25, 10), (30, 30), (30, 5), (10, 10)]
        for N, widget_count in cases:
            result = get_widget_index(0, N, widget_count)
            assert result == 0

    def test_single_widget_various_highlights(self):
        """Test with only one widget displayed."""
        for highlight in [0, 1, 10, 24, 25, 26, 50]:
            result = get_widget_index(highlight, 25, 1)
            assert result == 0

    def test_large_page_size_small_content(self):
        """Test page size larger than item count."""
        # 10 items, page size 30
        result = get_widget_index(5, 30, 10)
        assert result == 5
        result = get_widget_index(9, 30, 10)
        assert result == 9

    def test_highlight_beyond_total(self):
        """Test highlight value beyond total item count (boundary condition)."""
        # This can happen if filter changes drastically
        N = 25
        widget_count = 5
        # highlight=100 on a page with only 5 widgets
        result = get_widget_index(100, N, widget_count)
        # 100 % 25 = 0, min(0, 4) = 0
        assert result == 0


class TestHighlightForDoubleClick:
    """Double-clicking tile `index` on `page` must select that global position."""

    def test_first_tile_on_first_page(self):
        assert ImageGridWidget.highlight_for(page=0, N=25, index=0) == 0

    def test_last_tile_on_first_page(self):
        assert ImageGridWidget.highlight_for(page=0, N=25, index=24) == 24

    def test_first_tile_on_third_page(self):
        assert ImageGridWidget.highlight_for(page=2, N=25, index=0) == 50

    def test_round_trips_through_get_widget_index(self):
        """The frame must land on the tile that was actually clicked."""
        for page in range(4):
            for index in range(25):
                highlight = ImageGridWidget.highlight_for(page, 25, index)
                assert ImageGridWidget._get_widget_index(highlight, 25, 25) == index


class TestRangeBounds:
    """Shift-click selects an inclusive span between the anchor and the click."""

    def test_forward_range(self):
        assert ImageGridWidget.range_bounds(anchor=3, clicked=7) == (3, 5)

    def test_backward_range(self):
        """Dragging backwards selects the same span."""
        assert ImageGridWidget.range_bounds(anchor=7, clicked=3) == (3, 5)

    def test_single_item_range(self):
        assert ImageGridWidget.range_bounds(anchor=4, clicked=4) == (4, 1)

    def test_spans_pages(self):
        """The span is in global positions, so it crosses page boundaries."""
        start, count = ImageGridWidget.range_bounds(anchor=10, clicked=60)
        assert (start, count) == (10, 51)


class TestLineageWiring:
    """show_images must feed the indicator, once per page rather than per tile."""

    def _show_images_source(self):
        import ast
        import inspect

        from tagorganizer.widgets import image_grid_widget

        source = inspect.getsource(image_grid_widget.ImageGridWidget.show_images)
        return ast.parse(textwrap.dedent(source))

    def _calls(self, tree, name):
        import ast

        return [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == name
        ]

    def test_asks_the_database_which_photos_are_derived(self):
        assert self._calls(self._show_images_source(), "get_parent_summary")

    def test_asks_once_per_page_not_once_per_tile(self):
        """A query per tile would be 25 round trips a page."""
        import ast

        tree = self._show_images_source()
        loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)]
        in_loop = [
            call
            for loop in loops
            for call in self._calls(
                ast.Module(body=loop.body, type_ignores=[]), "get_parent_summary"
            )
        ]
        assert in_loop == []

    def test_passes_the_source_names_to_each_tile(self):
        assert self._calls(self._show_images_source(), "set_parent_names")
