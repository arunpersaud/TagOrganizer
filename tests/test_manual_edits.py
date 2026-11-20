"""Setting a photo's date or location by hand.

For photos nothing can be read from: scans, exports, cameras without GPS.
Saved in the library only; the files are never changed.
"""

from datetime import datetime

import pytest

from tagorganizer import db


class TestTheDatabase:
    def test_set_date(self, temp_db):
        ids = db.add_images(["/p/a.jpg", "/p/b.jpg", "/p/c.jpg"])
        db.set_date(ids[:2], datetime(1999, 12, 31, 23, 59))
        dates = [item.date for item in db.get_items_by_ids(ids)]
        assert sorted(dates, key=str) == sorted(
            [datetime(1999, 12, 31, 23, 59)] * 2 + [None], key=str
        )

    def test_set_location(self, temp_db):
        [item_id] = db.add_images(["/p/a.jpg"])
        db.set_location([item_id], 48.1, 11.5)
        [item] = db.get_items_by_ids([item_id])
        assert (item.latitude, item.longitude) == (48.1, 11.5)

    def test_a_photo_deleted_meanwhile_is_skipped(self, temp_db):
        ids = db.add_images(["/p/a.jpg", "/p/b.jpg"])
        db.delete_item(ids[0])
        db.set_date(ids, datetime(2000, 1, 1))
        assert db.get_items_by_ids(ids)[0].date == datetime(2000, 1, 1)


@pytest.fixture
def window_with_photos(window_for):
    window = window_for()
    ids = db.add_images(["/p/a.jpg", "/p/b.jpg", "/p/c.jpg"])
    window.refresh_after_data_change()
    window.selection.add_many(ids[:2])
    return window, ids


def dates(ids):
    return {item.id: item.date for item in db.get_items_by_ids(ids)}


class TestSetDate:
    def test_the_chosen_date_goes_on_every_selected_photo(
        self, window_with_photos, monkeypatch
    ):
        import tagorganizer.main as main_module

        window, ids = window_with_photos
        when = datetime(1985, 6, 1, 14, 30)

        class Chosen:
            def __init__(self, initial, count, parent=None):
                self.count = count

            def exec_(self):
                return main_module.QDialog.Accepted

            def chosen(self):
                return when

        monkeypatch.setattr(main_module, "SetDateDialog", Chosen)

        window.set_date()

        assert dates(ids) == {ids[0]: when, ids[1]: when, ids[2]: None}
        assert "Set the date of 2 photo(s)" in window.messages.text_edit.toPlainText()

    def test_cancelling_changes_nothing(self, window_with_photos, monkeypatch):
        import tagorganizer.main as main_module

        window, ids = window_with_photos

        class Cancelled:
            def __init__(self, *args, **kwargs):
                pass

            def exec_(self):
                return main_module.QDialog.Rejected

        monkeypatch.setattr(main_module, "SetDateDialog", Cancelled)

        window.set_date()

        assert set(dates(ids).values()) == {None}

    def test_the_dialog_starts_from_the_photos_date(self, qapp):
        from tagorganizer.widgets.set_date_dialog import SetDateDialog

        dialog = SetDateDialog(datetime(2001, 2, 3, 4, 5), count=3)
        assert dialog.chosen() == datetime(2001, 2, 3, 4, 5)
        assert "3" in dialog.windowTitle() or "3" in dialog.prompt.text()


class TestSetLocation:
    @pytest.fixture
    def answer(self, monkeypatch):
        import tagorganizer.main as main_module

        asked = []

        def set_answer(reply):
            def question(*args, **kwargs):
                asked.append(args)
                return reply

            monkeypatch.setattr(main_module.QMessageBox, "question", question)
            return asked

        return set_answer

    def located(self, ids):
        return {
            item.id: (item.latitude, item.longitude)
            for item in db.get_items_by_ids(ids)
        }

    def test_a_double_click_after_choosing_it_places_the_selection(
        self, window_with_photos, answer
    ):
        from tagorganizer.main import QMessageBox

        window, ids = window_with_photos
        answer(QMessageBox.Yes)

        window.set_location()
        assert window.tabs.currentWidget() is window.map
        window.map.view._bridge.map_double_clicked(48.1, 11.5)

        assert self.located(ids) == {
            ids[0]: (48.1, 11.5),
            ids[1]: (48.1, 11.5),
            ids[2]: (None, None),
        }

    def test_it_is_used_once(self, window_with_photos, answer):
        from tagorganizer.main import QMessageBox

        window, ids = window_with_photos
        asked = answer(QMessageBox.Yes)
        window.set_location()
        window.map.view._bridge.map_double_clicked(48.1, 11.5)

        window.map.view._bridge.map_double_clicked(10.0, 10.0)

        assert len(asked) == 1
        assert self.located(ids)[ids[0]] == (48.1, 11.5)

    def test_saying_no_changes_nothing(self, window_with_photos, answer):
        from tagorganizer.main import QMessageBox

        window, ids = window_with_photos
        answer(QMessageBox.No)
        window.set_location()

        window.map.view._bridge.map_double_clicked(48.1, 11.5)

        assert set(self.located(ids).values()) == {(None, None)}

    def test_an_ordinary_double_click_only_zooms(self, window_with_photos, answer):
        window, ids = window_with_photos
        asked = answer(None)

        window.map.view._bridge.map_double_clicked(48.1, 11.5)

        assert asked == []
        assert set(self.located(ids).values()) == {(None, None)}

    def test_leaving_the_map_disarms_it(self, window_with_photos, answer):
        """Otherwise a later double-click, made only to zoom, would place
        photos chosen long ago."""
        from qtpy.QtGui import QHideEvent

        window, _ids = window_with_photos
        asked = answer(None)
        window.set_location()

        window.map.view.hideEvent(QHideEvent())
        window.map.view._bridge.map_double_clicked(48.1, 11.5)

        assert asked == []

    def test_switching_profile_disarms_it(self, window_with_photos, answer):
        """The armed ids belong to this library; in another they are other photos."""
        window, _ids = window_with_photos
        asked = answer(None)
        window.set_location()

        window.reset_view_state()
        window.map.view._bridge.map_double_clicked(48.1, 11.5)

        assert asked == []

    def test_a_page_that_loads_while_armed_has_zoom_turned_off(
        self, window_with_photos, monkeypatch
    ):
        """Showing the map often rebuilds the page, after arm_location ran."""
        window, _ids = window_with_photos
        window.set_location()
        calls = []
        monkeypatch.setattr(
            window.map.view, "_set_double_click_zoom", lambda on: calls.append(on)
        )

        window.map.view._on_load_finished(True)

        assert calls == [False]

    def test_the_page_reports_double_clicks(self, window_for):
        window = window_for()
        script = window.map.view._make_injection_script("")
        assert "dblclick" in script
        assert "map_double_clicked" in script


def test_both_are_in_the_edit_menu(window_for):
    window = window_for()
    names = {action.text() for action in window.menu["Edit"].actions()}
    assert {"Set Date...", "Set Location..."} <= names
