"""Removing a tag from the selected photos, through the real tag menu and window.

The database operation is covered in tests/test_tag_editing.py. These choose
the menu entry on a real tag view, as a right-click would, and read back what
the handler did to the library and to the messages.
"""


def _photos(window, *names):
    from tagorganizer import db

    paths = [str(window.config.photos / name) for name in names]
    db.add_images(paths)
    by_uri = {item.uri: item.id for item in db.get_all_items()}
    return [by_uri[path] for path in paths]


def _tags_of(item_id):
    from tagorganizer import db
    from tagorganizer.models import Item

    with db.new_session() as session:
        return {tag.name for tag in session.get(Item, item_id).tags}


def _choose_on_the_first_tag(window, monkeypatch, label):
    """Right-click the first tag in the tree and choose ``label`` from its menu."""
    import tagorganizer.widgets.tag_view as tag_view_module
    from qtpy.QtCore import QPoint
    from qtpy.QtWidgets import QMenu

    class ChoosingMenu(QMenu):
        def exec(self, *args):
            (action,) = [a for a in self.actions() if a.text() == label]
            action.trigger()

    monkeypatch.setattr(tag_view_module, "QMenu", ChoosingMenu)
    index = window.tag_view.tag_model.index(0, 0)
    monkeypatch.setattr(window.tag_view, "indexAt", lambda position: index)
    window.tag_view.show_tag_menu(QPoint(3, 3))


def _beach_on_two_photos(window):
    """Two photos tagged Beach. Returns their ids."""
    from tagorganizer import db

    first, second = _photos(window, "a.jpg", "b.jpg")
    db.add_tag("Beach")
    db.set_tags(db.get_items_by_ids([first, second]), [db.get_tag("Beach")])
    window.tag_view.update_tags()
    return first, second


class TestContextMenuEntry:
    def test_the_entry_removes_the_tag_from_the_selected_photos_only(
        self, window_for, monkeypatch
    ):
        """Until now a mistagged photo could only be fixed by deleting the tag
        from the whole library."""
        window = window_for()
        selected, other = _beach_on_two_photos(window)
        window.selection.add(selected)

        _choose_on_the_first_tag(window, monkeypatch, "Remove from selected photos")

        assert _tags_of(selected) == set()
        assert _tags_of(other) == {"Beach"}


class TestRemovingFromPhotos:
    def test_the_messages_say_how_many_photos_lost_the_tag(self, window_for):
        from tagorganizer import db

        window = window_for()
        first, second = _beach_on_two_photos(window)
        window.selection.add_many([first, second])

        window.remove_tag_from_selection(db.get_tag("Beach").id)

        assert "Removed 'Beach' from 2 photo(s)" in (
            window.messages.text_edit.toPlainText()
        )

    def test_a_selection_without_the_tag_says_so_rather_than_nothing(self, window_for):
        """'Nothing happened' and 'none of them had that tag' look identical."""
        from tagorganizer import db

        window = window_for()
        (plain,) = _photos(window, "c.jpg")
        db.add_tag("Beach")
        window.selection.add(plain)

        window.remove_tag_from_selection(db.get_tag("Beach").id)

        assert "None of the selected photos had 'Beach'" in (
            window.messages.text_edit.toPlainText()
        )

    def test_with_nothing_selected_the_current_photo_loses_the_tag(self, window_for):
        from tagorganizer import db

        window = window_for()
        first, _ = _beach_on_two_photos(window)
        window.update_items()
        assert window.grid.current_item().item.id == first, "precondition"

        window.remove_tag_from_selection(db.get_tag("Beach").id)

        assert _tags_of(first) == set()

    def test_the_views_are_redrawn_after_the_removal(self, window_for, monkeypatch):
        from tagorganizer import db

        window = window_for()
        first, _ = _beach_on_two_photos(window)
        window.selection.add(first)
        drawn = []
        monkeypatch.setattr(
            window.timeline, "plot_histogram", lambda dates: drawn.append(dates)
        )

        window.remove_tag_from_selection(db.get_tag("Beach").id)

        assert len(drawn) == 1
