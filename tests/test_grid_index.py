"""Tests for ImageGridWidget index calculations.

This module tests the widget index calculation to ensure that the frame
highlight and current_item always point to the same widget, across various
page and item count combinations.

The index calculation is a staticmethod on the widget, so it can be called
directly without a GUI.
"""

import pytest

from tagorganizer.widgets.image_grid_widget import ImageGridWidget


# The real method, not a copy of it. This file used to define its own version
# with the same body and test that: the tests then agreed with themselves
# while the widget was free to drift, which is exactly how a broken
# move_items once stayed green for a whole round of work.
get_widget_index = ImageGridWidget._get_widget_index


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
            assert result == local_idx, (
                f"highlight={highlight}, expected {local_idx}, got {result}"
            )

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
            assert result == expected_idx, (
                f"highlight={highlight}: expected widget[{expected_idx}], got widget[{result}]"
            )

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
    """show_images marks derived photos, asking the database once per page.

    These run a real grid over a real database: the marks are read off the tiles
    the grid actually built.
    """

    @pytest.fixture
    def grid(self, qapp, temp_db, tmp_path):
        from types import SimpleNamespace

        from tagorganizer.widgets.image_grid_widget import ImageGridWidget

        main = SimpleNamespace(
            config=SimpleNamespace(photos=tmp_path, profile="A"),
            selection=set(),
            single_item=object(),
        )
        grid = ImageGridWidget(main)
        main.tabs = SimpleNamespace(currentWidget=lambda: None)
        yield grid
        grid.preloader.stop()

    @pytest.fixture
    def library(self, temp_db):
        """A parent, a photo derived from it, and an unrelated photo."""
        from tagorganizer import db
        from tagorganizer.widgets.tag_bar import Filters

        db.add_images(["/p/parent.jpg", "/p/child.jpg", "/p/plain.jpg"])
        ids = {item.uri: item.id for item in db.get_all_items()}
        db.set_parents(ids["/p/child.jpg"], [ids["/p/parent.jpg"]])
        return db.get_images(0, Filters())

    def test_a_derived_photo_is_marked_and_names_its_source(self, grid, library):
        grid.show_images(library)
        tiles = {tile.item.uri: tile for tile in grid.widgets}

        assert tiles["/p/child.jpg"].has_parents()
        assert "parent.jpg" in tiles["/p/child.jpg"].toolTip()
        assert not tiles["/p/plain.jpg"].has_parents()

    def test_the_database_is_asked_once_for_the_whole_page(
        self, grid, library, monkeypatch
    ):
        """A query per tile would be a round trip for each of the 25 on a page."""
        from tagorganizer import db

        asked = []
        real = db.get_parent_summary

        def counting(item_ids):
            asked.append(list(item_ids))
            return real(item_ids)

        monkeypatch.setattr(db, "get_parent_summary", counting)

        grid.show_images(library)

        assert len(asked) == 1
        assert sorted(asked[0]) == sorted(item.id for item in library)


class TestPreloadNeverDecodesOnTheGuiThread:
    def test_the_full_size_decode_runs_on_a_pool_thread(
        self, qapp, temp_db, tmp_path, monkeypatch
    ):
        """A decode on the GUI thread is what used to stall the window while the
        preloader ran. The decode is recorded where it happens, and the loader
        is waited on: a decode that never arrives fails the test, rather than
        passing for want of one.
        """
        import threading
        import time
        from types import SimpleNamespace

        from tagorganizer import db
        from tagorganizer.widgets import helper, image_grid_widget
        from tagorganizer.widgets.image_grid_widget import ImageGridWidget
        from tagorganizer.widgets.tag_bar import Filters

        on_gui_thread = []

        def record_decode(file):
            on_gui_thread.append(threading.current_thread() is threading.main_thread())
            return None

        monkeypatch.setattr(helper, "load_full_image", record_decode)
        monkeypatch.setattr(
            image_grid_widget,
            "get_thumbnail_loader",
            lambda: SimpleNamespace(load=lambda *args: None),
        )
        db.add_images([str(tmp_path / "a.jpg")])
        main = SimpleNamespace(
            config=SimpleNamespace(photos=tmp_path, profile="A"),
            selection=set(),
            single_item=object(),
            tag_bar=SimpleNamespace(get_filters=lambda: Filters()),
        )
        grid = ImageGridWidget(main)
        main.tabs = SimpleNamespace(currentWidget=lambda: grid)

        try:
            grid.preload_items()

            deadline = time.monotonic() + 5
            while not on_gui_thread and time.monotonic() < deadline:
                time.sleep(0.01)
            assert on_gui_thread, "the full-size photo was never decoded"
            assert on_gui_thread == [False], "a decode ran on the GUI thread"
        finally:
            grid.preloader.stop()


class TestClampHighlight:
    """Moving the red frame on a page with nothing on it must not go negative."""

    def test_an_empty_view_keeps_the_frame_at_zero(self):
        assert ImageGridWidget.clamp_highlight(1, 0) == 0
        assert ImageGridWidget.clamp_highlight(0, 0) == 0

    def test_the_cursor_keys_leave_an_empty_view_at_zero(self):
        """Through the real decorated move, not just the helper."""
        from types import SimpleNamespace

        grid = SimpleNamespace(
            widgets=[],
            highlight=0,
            N=25,
            columns=5,
            main=SimpleNamespace(
                numbers=[0, 0, 0],
                tabs=SimpleNamespace(currentWidget=lambda: "grid"),
                single_item="single",
            ),
        )

        ImageGridWidget.move_right(grid)
        assert grid.highlight == 0
        # Checked after each key: a later move can clamp an earlier bad value
        # back into range, which would hide it.
        ImageGridWidget.move_down(grid)
        assert grid.highlight == 0

    def test_a_position_past_the_end_is_brought_back_to_the_last_item(self):
        assert ImageGridWidget.clamp_highlight(7, 3) == 2

    def test_a_negative_position_is_brought_back_to_zero(self):
        assert ImageGridWidget.clamp_highlight(-1, 3) == 0

    def test_a_position_inside_the_view_is_unchanged(self):
        assert ImageGridWidget.clamp_highlight(2, 3) == 2


class _PreloadTabs:
    def __init__(self, grid):
        self.grid = grid

    def currentWidget(self):
        return self.grid


class _PreloadRecorder:
    """Stands in for the database and both decoders, and records what is asked."""

    def __init__(self, monkeypatch, grid_module):
        from types import SimpleNamespace

        from tagorganizer.models import Item

        self.full = []
        self.sizes = []
        self.items = [Item(id=1, uri="/photos/a.jpg")]
        self.grid_module = grid_module
        monkeypatch.setattr(
            grid_module,
            "db",
            SimpleNamespace(
                get_number_of_items=lambda filters: 1,
                get_images=lambda page, filters: self.items,
                get_image_range=lambda start, count, filters: self.items,
            ),
        )
        monkeypatch.setattr(
            grid_module,
            "get_full_image_loader",
            lambda: SimpleNamespace(warm=lambda file: self.full.append(file)),
        )
        monkeypatch.setattr(
            grid_module,
            "get_thumbnail_loader",
            lambda: SimpleNamespace(
                load=lambda item, size, photos: self.sizes.append(size)
            ),
        )

    def reset(self):
        self.full.clear()
        self.sizes.clear()


def _preloading_grid(recorder_filters, profile):
    from pathlib import Path
    from types import SimpleNamespace

    grid = SimpleNamespace(
        page=0,
        highlight=0,
        N=25,
        widgets=[],
        _last_preload_position=None,
        _preload_complete=False,
    )
    grid.main = SimpleNamespace(
        tabs=_PreloadTabs(grid),
        tag_bar=SimpleNamespace(get_filters=lambda: recorder_filters),
        config=SimpleNamespace(profile=profile, photos=Path("/photos")),
    )
    return grid


class TestPreloadPosition:
    """The preloader skips a pass that finished for the same position.

    The position has to include everything the pass depends on. Otherwise a
    pass that finished for one collection is skipped for another that happens to
    sit at the same page and highlight, and the photos around it are never warmed.
    """

    def test_a_finished_pass_is_not_repeated_for_the_same_position(self, monkeypatch):
        from tagorganizer.widgets import image_grid_widget

        recorder = _PreloadRecorder(monkeypatch, image_grid_widget)
        grid = _preloading_grid(None, "A")

        ImageGridWidget.preload_items(grid)
        recorder.reset()
        ImageGridWidget.preload_items(grid)

        assert recorder.full == []

    def test_a_profile_switch_at_the_same_position_is_preloaded_again(
        self, monkeypatch
    ):
        from tagorganizer.widgets import image_grid_widget

        recorder = _PreloadRecorder(monkeypatch, image_grid_widget)
        grid = _preloading_grid(None, "A")
        ImageGridWidget.preload_items(grid)

        grid.main.config.profile = "B"
        recorder.reset()
        ImageGridWidget.preload_items(grid)

        assert recorder.full == ["/photos/a.jpg"]

    def test_a_filter_change_at_the_same_position_is_preloaded_again(self, monkeypatch):
        from tagorganizer.widgets import image_grid_widget
        from tagorganizer.widgets.tag_bar import Filters

        recorder = _PreloadRecorder(monkeypatch, image_grid_widget)
        grid = _preloading_grid(Filters(tags=["x"]), "A")
        ImageGridWidget.preload_items(grid)

        grid.main.tag_bar.get_filters = lambda: Filters(tags=["y"])
        recorder.reset()
        ImageGridWidget.preload_items(grid)

        assert recorder.full == ["/photos/a.jpg"]


class TestPreloadWork:
    def test_full_size_photos_are_warmed_by_the_background_loader(self, monkeypatch):
        """A decode on the GUI thread per tick is what the preloader used to do."""
        from tagorganizer.widgets import image_grid_widget

        recorder = _PreloadRecorder(monkeypatch, image_grid_widget)
        grid = _preloading_grid(None, "A")

        ImageGridWidget.preload_items(grid)

        assert recorder.full == ["/photos/a.jpg"]

    def test_thumbnails_are_warmed_at_the_standard_size(self, monkeypatch):
        from tagorganizer.widgets import image_grid_widget

        recorder = _PreloadRecorder(monkeypatch, image_grid_widget)
        grid = _preloading_grid(None, "A")

        ImageGridWidget.preload_items(grid)

        assert 150 in recorder.sizes

    def test_the_size_the_tiles_are_showing_is_warmed_too(self, monkeypatch):
        from types import SimpleNamespace

        from tagorganizer.widgets import image_grid_widget

        recorder = _PreloadRecorder(monkeypatch, image_grid_widget)
        grid = _preloading_grid(None, "A")
        grid.widgets = [SimpleNamespace(pixmap_width=300)]

        ImageGridWidget.preload_items(grid)

        assert set(recorder.sizes) == {150, 300}
