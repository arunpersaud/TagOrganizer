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


class TestChipSelection:
    def test_clicking_a_chip_selects_it_rather_than_removing_it(self, qapp):
        """Click used to remove. It now selects, so chips can be grouped."""
        bar = _tag_bar()
        bar.add_tag("Holiday")
        chip = bar.selected_tags[0].widget

        bar.toggle_chip(chip)

        assert bar.is_chip_selected(chip) is True
        assert "Holiday" in bar.get_filters().tags, "the filter must still apply"

    def test_clicking_again_deselects(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Holiday")
        chip = bar.selected_tags[0].widget

        bar.toggle_chip(chip)
        bar.toggle_chip(chip)

        assert bar.is_chip_selected(chip) is False

    def test_remove_selected_drops_only_the_selected_chips(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Holiday")
        bar.add_tag("Beach")
        bar.toggle_chip(bar.selected_tags[0].widget)

        bar.remove_selected()

        assert bar.get_filters().tags == ["Beach"]

    def test_remove_selected_refreshes_once(self, qapp):
        """Removing several chips is one gesture and should cost one redraw."""
        bar = _tag_bar()
        bar.add_tag("Holiday")
        bar.add_tag("Beach")
        for entry in list(bar.selected_tags):
            bar.toggle_chip(entry.widget)
        bar.main.update_items_calls = 0

        bar.remove_selected()

        assert bar.main.update_items_calls == 1

    def test_remove_selected_with_nothing_selected_does_nothing(self, qapp):
        """Delete must be inert unless chips are selected.

        Otherwise a stray Delete keypress would silently drop filters, and the
        key is close enough to the photo-deleting workflow to be alarming.
        """
        bar = _tag_bar()
        bar.add_tag("Holiday")
        bar.main.update_items_calls = 0

        bar.remove_selected()

        assert bar.get_filters().tags == ["Holiday"]
        assert bar.main.update_items_calls == 0

    def test_selection_survives_an_unrelated_refresh(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Holiday")
        chip = bar.selected_tags[0].widget
        bar.toggle_chip(chip)

        bar.refresh()

        assert bar.is_chip_selected(chip) is True

    def test_removing_a_chip_forgets_its_selection(self, qapp):
        """A removed chip must not linger in the selection set."""
        bar = _tag_bar()
        bar.add_tag("Holiday")
        chip = bar.selected_tags[0].widget
        bar.toggle_chip(chip)

        bar.remove_selected()

        assert bar.selected_chips() == []


class TestDeleteKeyBinding:
    def test_delete_is_bound_to_removing_chips_not_photos(self):
        """Delete must reach TagBar.remove_selected, never delete_items.

        remove_selected is itself inert with nothing selected, so the two
        together are what keep a stray Delete from touching the library.
        """
        import ast
        from pathlib import Path as P

        source = (
            P(__file__).parent.parent / "src" / "tagorganizer" / "main.py"
        ).read_text()
        tree = ast.parse(source)

        init = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "__init__"
        )
        bound = {
            ast.unparse(k): ast.unparse(v)
            for n in ast.walk(init)
            if isinstance(n, ast.Dict)
            for k, v in zip(n.keys, n.values, strict=False)
            if k is not None
        }
        delete_targets = [v for k, v in bound.items() if "Key_Delete" in k]
        assert delete_targets, "Delete is not bound at all"
        assert "remove_selected" in delete_targets[0]
        assert "delete_items" not in delete_targets[0]


class TestClickWiring:
    def test_clicking_the_button_selects_rather_than_removes(self, qapp):
        """Exercise the real click, not just the method it should reach.

        Testing toggle_chip directly proves the method works but says nothing
        about what the button is wired to - the connection could still call
        remove_tag_button and every other test would pass.
        """
        bar = _tag_bar()
        bar.add_tag("Holiday")
        chip = bar.selected_tags[0].widget

        chip.click()

        assert bar.is_chip_selected(chip) is True
        assert bar.get_filters().tags == ["Holiday"], "clicking must not remove it"
