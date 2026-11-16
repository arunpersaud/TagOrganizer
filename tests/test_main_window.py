"""Building the real main window.

Nothing else in the suite constructs a MainWindow, and that gap hid three
separate bugs: a broken plugin crashed startup, an undecodable photo aborted
the process, and rebuilding the menus stacked duplicates. Each was found by
running a scratch script by hand. These tests are those scripts, kept.

The fixtures that build the window live in window_fixtures.py, which conftest
registers as a plugin.
"""

from pathlib import Path

import pytest

from window_fixtures import add_profile, answer_move_dialog, menu_titles


class TestItStarts:
    def test_the_window_opens_the_config_it_was_given(self, window_for, tmp_path):
        window = window_for()
        assert str(window.config.db).startswith(str(tmp_path))

    def test_no_database_outside_the_temp_directory_is_opened(
        self, window_for, database_opens, tmp_path
    ):
        """The failure that started all of this: a script that meant to use a
        temp config migrated the user's actual photo library instead. Checking
        only the final path missed a database opened on the way, so every open
        is checked."""
        window_for()
        assert database_opens, "the window opened no database at all"
        for opened in database_opens:
            assert Path(opened).is_relative_to(tmp_path), opened

    def test_the_status_bar_has_the_progress_widgets(self, window_for):
        window = window_for()
        assert window.tasks.progressbar is not None


class TestTheMenus:
    def test_the_plugin_categories_are_all_present(self, window_for):
        titles = menu_titles(window_for())
        for expected in ("Maintenance", "Files", "Reports"):
            assert expected in titles

    def test_maintenance_comes_before_the_others(self, window_for):
        """It holds the tasks reached for most often."""
        titles = menu_titles(window_for())
        assert titles.index("Maintenance") < titles.index("Files")
        assert titles.index("Files") < titles.index("Reports")

    def test_every_shipped_plugin_has_an_entry(self, window_for):
        window = window_for()
        entries = set()
        for menu in window._plugin_menus:
            entries.update(action.text() for action in menu.actions())
        assert "Update Hashes in DB" in entries
        assert "Move Files to Default Dirs" in entries

    def test_rebuilding_does_not_duplicate_the_menus(self, window_for):
        """removeAction alone leaves the menu parented to the bar, and every
        visit to Settings added another Maintenance menu."""
        window = window_for()
        before = menu_titles(window)

        window.build_plugin_menu()
        window.build_plugin_menu()

        assert menu_titles(window) == before


class TestBrokenPlugins:
    def test_a_plugin_that_fails_to_import_does_not_stop_startup(
        self, window_for, tmp_path
    ):
        """Reporting the failure used to happen before the message widget
        existed, which turned a bad plugin into a crash on launch."""
        home = tmp_path / "withbroken"
        (home / "plugins").mkdir(parents=True)
        (home / "plugins" / "bad.py").write_text("import no_such_module\n")

        window = window_for(plugins_dir=home)

        assert [b.path.name for b in window.tasks.broken] == ["bad.py"]

    def test_the_working_plugins_still_load(self, window_for, tmp_path):
        home = tmp_path / "withbroken2"
        (home / "plugins").mkdir(parents=True)
        (home / "plugins" / "bad.py").write_text("import no_such_module\n")

        window = window_for(plugins_dir=home)

        assert len(window.tasks.registry.all()) >= 8


class TestUserPlugins:
    GOOD = """
from tagorganizer.plugins import Plugin


class Mine(Plugin):
    name = "My own task"
    category = "Tags"

    def run(self, ctx):
        yield 1, 1
"""

    def test_a_plugin_dropped_in_the_directory_appears(self, window_for, tmp_path):
        home = tmp_path / "withmine"
        (home / "plugins").mkdir(parents=True)
        (home / "plugins" / "mine.py").write_text(self.GOOD)

        window = window_for(plugins_dir=home)

        assert "My own task" in {p.name for p in window.tasks.registry.all()}

    def test_it_gets_its_own_menu(self, window_for, tmp_path):
        home = tmp_path / "withmine2"
        (home / "plugins").mkdir(parents=True)
        (home / "plugins" / "mine.py").write_text(self.GOOD)

        window = window_for(plugins_dir=home)

        assert "Tags" in menu_titles(window)


class TestRunningATask:
    def test_a_task_runs_to_completion_through_the_worker(self, window_for, tmp_path):
        from sqlmodel import Session

        from tagorganizer import db
        from tagorganizer.models import Item
        from tagorganizer.scope import Scope

        window = window_for()
        for index in range(3):
            path = window.config.photos / f"{index}.jpg"
            path.write_bytes(b"data" + str(index).encode())
            with Session(db.engine) as session:
                session.add(Item(uri=str(path)))
                session.commit()

        plugin = next(
            p for p in window.tasks.registry.all() if p.name == "Update Hashes in DB"
        )
        window.tasks.run_plugin(plugin, Scope.LIBRARY)

        assert window.tasks.wait_for_idle(), "the task never finished"
        assert all(item.data_xxhash for item in db.get_all_items())


class TestLineageActions:
    """The derived-from actions: refusals say why, and the link is what they say.

    The refusal tests used to assert nothing, so a refusal that wrote a link
    anyway would still pass. Each one checks the message and that the database
    is unchanged.
    """

    def _two_photos(self, window):
        from tagorganizer import db

        paths = [str(window.config.photos / name) for name in ("a.jpg", "b.jpg")]
        db.add_images(paths)
        by_uri = {item.uri: item.id for item in db.get_all_items()}
        return by_uri[paths[0]], by_uri[paths[1]]

    def _highlight(self, window, item_id):
        """Put the red frame on one photo, as a click on it would."""
        window.grid.highlight = next(
            index
            for index, widget in enumerate(window.grid.widgets)
            if widget.item.id == item_id
        )

    def _shown(self, window):
        return window.messages.text_edit.toPlainText()

    def test_marking_without_a_current_photo_says_so(self, window_for):
        window = window_for()

        window.mark_as_derived()

        assert "No current photo to mark." in self._shown(window)

    def test_marking_with_no_selection_says_so_and_links_nothing(self, window_for):
        from tagorganizer import db

        window = window_for()
        child, _ = self._two_photos(window)
        window.update_items()
        self._highlight(window, child)

        window.mark_as_derived()

        assert "Select the source photos first." in self._shown(window)
        assert "Marked as derived" not in self._shown(window)
        assert db.get_parent_ids(child) == []

    def test_a_photo_cannot_be_its_own_source(self, window_for):
        from tagorganizer import db

        window = window_for()
        child, _ = self._two_photos(window)
        window.update_items()
        self._highlight(window, child)
        window.selection.add(child)

        window.mark_as_derived()

        assert "cannot be its own source" in self._shown(window)
        assert db.get_parent_ids(child) == []

    def test_marking_records_the_selection_as_sources(self, window_for):
        from tagorganizer import db

        window = window_for()
        child, parent = self._two_photos(window)
        window.update_items()
        self._highlight(window, child)
        window.selection.add(parent)

        window.mark_as_derived()

        assert db.get_parent_ids(child) == [parent]
        assert "Marked as derived from 1 photo(s)." in self._shown(window)

    def test_clearing_without_a_current_photo_says_so(self, window_for):
        window = window_for()

        window.clear_lineage()

        assert "No current photo to clear." in self._shown(window)

    def test_clearing_a_photo_with_no_sources_says_so(self, window_for):
        window = window_for()
        child, _ = self._two_photos(window)
        window.update_items()
        self._highlight(window, child)

        window.clear_lineage()

        assert "This photo has no recorded sources." in self._shown(window)

    def test_clearing_removes_the_recorded_sources(self, window_for):
        from tagorganizer import db

        window = window_for()
        child, parent = self._two_photos(window)
        db.set_parents(child, [parent])
        window.update_items()
        self._highlight(window, child)

        window.clear_lineage()

        assert db.get_parent_ids(child) == []
        assert "Cleared the recorded sources." in self._shown(window)


class TestViewsFollowTheLibrary:
    def test_a_data_change_redraws_the_timeline_even_when_filters_match(
        self, window_for, monkeypatch
    ):
        """update_items skips the timeline and map when the filters have not
        changed. After a tag or a delete they have, though the filter did not."""
        window = window_for()
        window.update_items()

        drawn = []
        monkeypatch.setattr(
            window.timeline, "plot_histogram", lambda dates: drawn.append(dates)
        )
        window.update_items()
        assert drawn == [], "precondition: plain redraw keeps the timeline"

        window.refresh_after_data_change()
        assert len(drawn) == 1


class TestGridAfterAFilterChange:
    def test_a_shrunken_result_moves_the_frame_back_on_screen(self, window_for):
        window = window_for()
        window.grid.page = 10
        window.grid.highlight = 10 * window.grid.N + 3

        window.update_items()  # the library is empty: nothing matches

        assert (window.grid.page, window.grid.highlight) == (0, 0)


class TestSelectedCount:
    def test_the_selected_count_follows_the_selection(self, window_for):
        """The map adds to the selection and then calls update_items; the
        status line must show the new count without anything else asked."""
        window = window_for()
        window.selection.add_many([1, 2, 3])

        window.update_items()

        assert "Selected: 3" in window.numbers_label.text()


class TestKeysBelongToTheWindow:
    """The key filter sits on the whole application.

    It used to take every key press in the program, so typing into a dialog
    moved the hidden grid, Backspace removed filter chips behind it and Return
    switched tabs. Only this window's own keys may be taken.
    """

    def _key(self, key):
        from qtpy.QtCore import QEvent, Qt
        from qtpy.QtGui import QKeyEvent

        return QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)

    def test_a_key_from_another_window_is_left_alone(self, window_for):
        from qtpy.QtCore import Qt
        from qtpy.QtWidgets import QWidget

        window = window_for()
        other = QWidget()  # a top-level window, as a dialog would be
        try:
            handled = window.eventFilter(other, self._key(Qt.Key.Key_Backspace))
        finally:
            other.deleteLater()

        assert handled is False

    def test_a_key_from_another_window_does_not_touch_the_filters(self, window_for):
        from qtpy.QtCore import Qt
        from qtpy.QtWidgets import QWidget

        window = window_for()
        window.tag_bar.add_tag("beach")
        window.tag_bar.toggle_chip(window.tag_bar.selected_tags[0].widget)
        other = QWidget()
        try:
            window.eventFilter(other, self._key(Qt.Key.Key_Delete))
        finally:
            other.deleteLater()

        assert window.tag_bar.get_all_names() == ["beach"]

    def test_the_window_still_gets_its_own_keys(self, window_for):
        """The positive case, so the negative ones above cannot pass by
        accident because the filter stopped doing anything at all."""
        from qtpy.QtCore import Qt

        window = window_for()
        assert window.eventFilter(window.grid, self._key(Qt.Key.Key_Escape)) is True
        assert window._owns_key_event(window.grid) is True


class TestMovingWhileATaskRuns:
    def test_a_move_is_refused_while_the_worker_is_busy(self, window_for, monkeypatch):
        window = window_for()
        window.selection.add_many([1])
        monkeypatch.setattr(window.tasks.runner, "is_idle", lambda: False)

        window.move_selection_to_profile()

        assert "still running" in window.messages.text_edit.toPlainText()


class TestTagTreeChanges:
    """Drops and deletes from the tag tree, through the real window and database."""

    def _tags(self, window):
        from tagorganizer import db

        return {t.name: t for t in db.get_all_tags()}

    def test_a_nested_tag_moves_under_the_tag_it_was_dropped_on(self, window_for):
        from tagorganizer import db

        window = window_for()
        france = db.add_tag("France")
        paris = db.add_tag("Paris")
        animals = db.add_tag("Animals")
        db.set_parent_tag_by_id(paris, france)

        window.tag_view.on_tag_moved([paris], animals, False)

        assert db.get_tag_by_id(paris).parent_id == animals

    def test_a_tag_dropped_under_itself_is_refused_and_nothing_changes(
        self, window_for
    ):
        from tagorganizer import db

        window = window_for()
        france = db.add_tag("France")
        paris = db.add_tag("Paris")
        db.set_parent_tag_by_id(paris, france)

        window.tag_view.on_tag_moved([france], paris, False)

        assert db.get_tag_by_id(france).parent_id is None
        assert "ancestor" in window.messages.text_edit.toPlainText()

    def test_a_reserved_button_cannot_be_dragged(self, window_for):
        from tagorganizer import db

        window = window_for()
        animals = db.add_tag("Animals")

        window.tag_view.on_tag_moved([None], animals, False)

        assert db.get_tag_by_id(animals).parent_id is None

    def test_a_drop_at_the_top_level_makes_the_tag_top_level(self, window_for):
        from tagorganizer import db

        window = window_for()
        france = db.add_tag("France")
        paris = db.add_tag("Paris")
        db.set_parent_tag_by_id(paris, france)

        window.tag_view.on_tag_moved([paris], None, False)

        assert db.get_tag_by_id(paris).parent_id is None

    def test_deleting_a_tag_with_subtags_is_refused_with_a_reason(
        self, window_for, monkeypatch
    ):
        from tagorganizer import db
        import tagorganizer.widgets.tag_view as tag_view_module

        warnings = []

        class FakeBox:
            StandardButton = tag_view_module.QMessageBox.StandardButton

            @staticmethod
            def warning(*args):
                warnings.append(args)

            @staticmethod
            def question(*args):
                raise AssertionError("a refused delete must not ask")

        monkeypatch.setattr(tag_view_module, "QMessageBox", FakeBox)
        window = window_for()
        france = db.add_tag("France")
        paris = db.add_tag("Paris")
        db.set_parent_tag_by_id(paris, france)

        window.tag_view.delete_tag(france)

        assert db.get_tag_by_id(france) is not None
        assert warnings and "subtag" in warnings[0][2]

    def test_a_confirmed_delete_removes_the_tag_and_its_filter_chip(
        self, window_for, monkeypatch
    ):
        from tagorganizer import db
        import tagorganizer.widgets.tag_view as tag_view_module

        class FakeBox:
            StandardButton = tag_view_module.QMessageBox.StandardButton

            @staticmethod
            def question(*args):
                return FakeBox.StandardButton.Yes

        monkeypatch.setattr(tag_view_module, "QMessageBox", FakeBox)
        window = window_for()
        beach = db.add_tag("beach")
        window.tag_bar.add_tag("beach")

        window.tag_view.delete_tag(beach)

        assert db.get_tag_by_id(beach) is None
        assert "beach" not in window.tag_bar.get_all_names()

    def test_a_declined_delete_changes_nothing(self, window_for, monkeypatch):
        from tagorganizer import db
        import tagorganizer.widgets.tag_view as tag_view_module

        class FakeBox:
            StandardButton = tag_view_module.QMessageBox.StandardButton

            @staticmethod
            def question(*args):
                return FakeBox.StandardButton.No

        monkeypatch.setattr(tag_view_module, "QMessageBox", FakeBox)
        window = window_for()
        beach = db.add_tag("beach")

        window.tag_view.delete_tag(beach)

        assert db.get_tag_by_id(beach) is not None


class TestMoveReportsLineage:
    def test_dropped_lineage_is_reported_beside_dropped_tags(
        self, window_for, tmp_path, monkeypatch
    ):
        """Lineage links are lost in a move just as tags are, and the user should
        be told about both."""
        from tagorganizer import db

        window = window_for()
        add_profile(window, "other", tmp_path)
        paths = [str(window.config.photos / name) for name in ("a.jpg", "b.jpg")]
        db.add_images(paths)
        by_uri = {item.uri: item.id for item in db.get_all_items()}
        parent, child = by_uri[paths[0]], by_uri[paths[1]]
        db.set_parents(child, [parent])
        db.add_tag("Beach")
        db.set_tags(db.get_items_by_ids([child]), [db.get_tag("Beach")])
        window.selection.add(child)
        answer_move_dialog(monkeypatch, "other")

        window.move_selection_to_profile()

        shown = window.messages.text_edit.toPlainText()
        assert "Dropped tags: Beach" in shown
        assert "Dropped 1 derived-from link(s)" in shown


class TestReportingAnError:
    def test_the_summary_goes_to_messages_and_the_traceback_to_the_dialog(
        self, window_for, monkeypatch
    ):
        import tagorganizer.main as main_module

        shown = []

        class FakeBox:
            Icon = main_module.QMessageBox.Icon

            def __init__(self, parent=None):
                shown.append(self)
                self.details = None

            def setIcon(self, icon):
                pass

            def setWindowTitle(self, title):
                pass

            def setText(self, text):
                self.text = text

            def setDetailedText(self, text):
                self.details = text

            def exec(self):
                self.executed = True

        monkeypatch.setattr(main_module, "QMessageBox", FakeBox)
        window = window_for()

        window.report_unhandled("ValueError: nope", "Traceback (most recent call last)")

        assert "ValueError: nope" in window.messages.text_edit.toPlainText()
        (box,) = shown
        assert box.details == "Traceback (most recent call last)"
        assert box.executed is True


class TestStatusLineCounts:
    """The status line shows what it was last given, and zero is a value.

    update_numbers used to be tested on a copy of itself. These run the real
    method, so a change to `is not None` checks shows up here.
    """

    @pytest.mark.parametrize(
        "field, index", [("view", 0), ("selected", 1), ("total", 2)]
    )
    def test_zero_is_shown_for_each_count(self, window_for, field, index):
        window = window_for()
        window.update_numbers(view=5, selected=5, total=5)

        window.update_numbers(**{field: 0})

        assert window.numbers[index] == 0
        assert f"{field.capitalize()}: 0" in window.numbers_label.text()

    def test_all_zeros_are_shown(self, window_for):
        window = window_for()
        window.update_numbers(view=5, selected=5, total=5)

        window.update_numbers(view=0, selected=0, total=0)

        assert window.numbers == [0, 0, 0]
        assert window.numbers_label.text() == "View: 0 Selected: 0 Total: 0"


class TestTagsFromTheTagLine:
    """handle_tags is the tag line: it names the tags, then tags the photos.

    These run the real method and read the database back, so they hold however
    handle_tags is arranged internally.
    """

    def _photos(self, window, *names):
        from tagorganizer import db

        paths = [str(window.config.photos / name) for name in names]
        db.add_images(paths)
        return [item.id for item in db.get_all_items() if item.uri in paths]

    def _tags_of(self, item_id):
        from tagorganizer import db
        from tagorganizer.models import Item

        with db.new_session() as session:
            return {tag.name for tag in session.get(Item, item_id).tags}

    def test_the_tags_go_to_every_selected_photo(self, window_for):
        window = window_for()
        first, second = self._photos(window, "a.jpg", "b.jpg")
        window.selection.add_many([first, second])
        window.tag_line_edit.setText("Beach, Holiday")

        window.handle_tags()

        for item_id in (first, second):
            assert self._tags_of(item_id) == {"Beach", "Holiday"}

    def test_with_nothing_selected_the_current_photo_gets_them(self, window_for):
        window = window_for()
        (only,) = self._photos(window, "c.jpg")
        window.update_items()
        assert window.grid.current_item().item.id == only, "precondition"
        window.tag_line_edit.setText("Beach")

        window.handle_tags()

        assert self._tags_of(only) == {"Beach"}

    def test_a_name_is_stored_as_typed(self, window_for):
        from tagorganizer import db

        window = window_for()
        (photo,) = self._photos(window, "d.jpg")
        window.selection.add(photo)
        window.tag_line_edit.setText("iPhone")

        window.handle_tags()

        assert db.get_tag("iphone").name == "iPhone"
        assert self._tags_of(photo) == {"iPhone"}

    @pytest.mark.parametrize("reserved", ["No GPS", "no gps", "Wrong dir"])
    def test_a_reserved_name_is_refused_and_creates_no_tag(self, window_for, reserved):
        from tagorganizer import db

        window = window_for()
        (photo,) = self._photos(window, "e.jpg")
        window.selection.add(photo)
        window.tag_line_edit.setText(f"{reserved}, Beach")

        window.handle_tags()

        assert db.get_tag(reserved) is None, "the reserved name became a real tag"
        assert self._tags_of(photo) == {"Beach"}
        assert "not allowed" in window.messages.text_edit.toPlainText()


class TestWindowWiring:
    """What the window does when a tab, a button or a selection changes.

    These used to read main.py and look for a call by name. They now trigger
    the real signal or method, so they fail if the call is removed or the
    wiring is broken.
    """

    def test_switching_to_the_single_view_populates_it(self, window_for, monkeypatch):
        window = window_for()
        calls = []
        monkeypatch.setattr(window, "update_single_item", lambda: calls.append(1))
        assert window.tabs.currentWidget() is not window.single_item, "precondition"

        window.tabs.setCurrentWidget(window.single_item)

        assert calls == [1]

    def test_switching_to_the_map_tells_it_it_is_shown(self, window_for, monkeypatch):
        window = window_for()
        shown = []
        monkeypatch.setattr(window.map, "on_shown", lambda: shown.append(1))
        assert window.tabs.currentWidget() is not window.map, "precondition"

        window.tabs.setCurrentWidget(window.map)

        assert shown == [1]

    def test_show_selected_only_restricts_the_view_to_the_selection(self, window_for):
        window = window_for()
        window.selection.add_many([1, 2, 3])

        window.show_selected_only()

        assert window.tag_bar.selected_ids.item_ids == [1, 2, 3]

    def test_show_selected_only_with_nothing_selected_says_so(self, window_for):
        window = window_for()

        window.show_selected_only()

        assert "Nothing is selected." in window.messages.text_edit.toPlainText()
        assert window.tag_bar.selected_ids.item_ids is None

    def test_the_applied_filters_follow_the_chips(self, window_for):
        """update_items remembers the filters it drew, so a later change to them
        is noticed and the timeline and map are redrawn."""
        window = window_for()
        window.update_items()
        before = window.filters
        window.selection.add_many([1])
        window.show_selected_only()

        window.update_items()

        assert window.filters != before

    def test_deleting_with_nothing_current_does_nothing(self, window_for):
        """With no photo highlighted there is nothing to delete, and no
        confirmation dialog may open: the call returns at once."""
        window = window_for()

        window.delete_items()

        assert window.messages.text_edit.toPlainText() == ""
