"""Tests for tagging functionality and related fixes.

These tests verify:
- F2: Multi-item tagging works correctly (tags applied to all selected items)
- F8: Reserved tag names are rejected before DB creation
"""

import logging

from sqlmodel import Session, select
from window_fixtures import add_profile, answer_move_dialog, database_uris

from tagorganizer import db
from tagorganizer.models import Item, Tag


class TestF2MultiItemTagging:
    """F2: db.set_tags must apply tags to all selected items."""

    def test_set_tags_applies_to_all_items(self, seeded_db):
        """Verify db.set_tags tags every item in the list."""
        # Get the first 2 items from seeded_db
        items = seeded_db["items"][:2]

        # Create a new tag
        with Session(db.engine) as session:
            new_tag = Tag(name="TestTag")
            session.add(new_tag)
            session.commit()
            session.refresh(new_tag)
            tag = db.get_tag("TestTag")

        # Apply tag to both items
        db.set_tags(items, [tag])

        # Verify both items now have the tag
        with Session(db.engine) as session:
            for item in items:
                db_item = session.exec(select(Item).where(Item.id == item.id)).first()
                assert db_item is not None
                tag_names = [t.name for t in db_item.tags]
                assert "TestTag" in tag_names

    def test_set_tags_applies_multiple_tags(self, seeded_db):
        """Verify db.set_tags applies multiple tags to all items."""
        items = seeded_db["items"][:3]

        # Create multiple new tags
        tag_ids = []
        for tag_name in ["Tag1", "Tag2", "Tag3"]:
            db.add_tag(tag_name)
            tag_ids.append(db.get_tag(tag_name).id)

        tags = [db.get_tag_by_id(tid) for tid in tag_ids]

        # Apply all tags to all items
        db.set_tags(items, tags)

        # Verify all items have all tags
        with Session(db.engine) as session:
            for item in items:
                db_item = session.exec(select(Item).where(Item.id == item.id)).first()
                tag_names = [t.name for t in db_item.tags]
                assert "Tag1" in tag_names
                assert "Tag2" in tag_names
                assert "Tag3" in tag_names


class TestF8ReservedTags:
    """F8: Reserved tag names must be rejected before DB creation."""

    def test_reserved_tags_constant_matches(self, temp_db):
        """Verify RESERVED_TAGS contains the expected reserved names."""
        from tagorganizer.widgets import RESERVED_TAGS

        expected = ["No Time", "No GPS", "Wrong dir", "Unnamed faces", "Duplicates"]
        assert expected == RESERVED_TAGS, (
            f"RESERVED_TAGS mismatch: {RESERVED_TAGS} != {expected}"
        )


class TestReservedTagsAreCaseInsensitive:
    """Reserved names must be rejected however the user capitalises them.

    Tag names are stored as typed, so the check cannot rely on any particular
    casing: an exact-match test would let "no gps" through and create a real tag
    colliding with the filter button.
    """

    def test_every_reserved_name_is_rejected_whatever_the_casing(self):
        from tagorganizer.main import is_reserved_tag
        from tagorganizer.widgets.tag_bar import RESERVED_TAGS

        for reserved in RESERVED_TAGS:
            assert is_reserved_tag(reserved), reserved
            # the exact transformation handle_tags applies
            assert is_reserved_tag(reserved.strip().title()), reserved
            assert is_reserved_tag(reserved.lower()), reserved
            assert is_reserved_tag(reserved.upper()), reserved
            assert is_reserved_tag(f"  {reserved}  "), reserved

    def test_ordinary_names_are_not_reserved(self):
        from tagorganizer.main import is_reserved_tag

        for name in ("Holiday", "Beach", "No", "GPS", "Wrong", "No GPSX"):
            assert not is_reserved_tag(name), name


class TestChangeProfileResetsViewState:
    """Regression guard: stale grid state doesn't survive profile switch.

    Switching profiles leaves the old grid pagination, highlight, and
    selection (which are ids from the old database). This would corrupt
    operations like delete_items or copy_selection. change_profile must call
    reset_view_state to clear this state; deleting it would reintroduce the bug.
    """

    def test_switching_profile_forgets_the_selection(self, window_for, tmp_path):
        """The selected ids name rows of the old database, so none may survive."""
        from tagorganizer import db

        window = window_for()
        add_profile(window, "other", tmp_path)
        db.add_images([str(window.config.photos / "a.jpg")])
        (item_id,) = [item.id for item in db.get_all_items()]
        window.selection.add(item_id)
        window.update_items()
        assert len(window.selection) == 1, "precondition"

        window.change_profile("other")

        assert window.config.profile == "other", "the switch did not happen"
        assert len(window.selection) == 0


class TestQtMessageHandler:
    """Qt's own output goes through logging, and one known-benign line is dropped."""

    def test_drops_the_libpng_iccp_warning(self, caplog):
        from qtpy.QtCore import QtMsgType

        from tagorganizer.main import qt_message_handler

        with caplog.at_level(logging.DEBUG):
            qt_message_handler(
                QtMsgType.QtWarningMsg,
                None,
                "libpng warning: iCCP: known incorrect sRGB profile",
            )
        assert caplog.records == []

    def test_passes_other_qt_warnings_through(self, caplog):
        """Only the one known line is suppressed; real warnings must survive."""
        from qtpy.QtCore import QtMsgType

        from tagorganizer.main import qt_message_handler

        with caplog.at_level(logging.DEBUG):
            qt_message_handler(QtMsgType.QtWarningMsg, None, "something real broke")
        assert len(caplog.records) == 1
        assert "something real broke" in caplog.records[0].getMessage()


class TestMoveSelectionToProfile:
    """Moving the selection into another profile's database.

    The move must validate everything before the transaction opens, so refusals
    leave the database untouched. Order matters: prepare_target must run before
    move_items.
    """

    def _select_photos(self, window, *names):
        from tagorganizer import db

        paths = [str(window.config.photos / name) for name in names]
        db.add_images(paths)
        ids = [item.id for item in db.get_all_items() if item.uri in paths]
        window.selection.add_many(ids)
        return paths

    def test_an_unusable_target_is_refused_and_the_library_keeps_its_photos(
        self, window_for, tmp_path, monkeypatch
    ):
        """A WAL-mode target cannot take part in an atomic move. The refusal must
        come from the target check, before any rows are touched, so the
        'Cannot Move to Target' dialog is the one shown and the library is intact.
        """
        import sqlite3

        import tagorganizer.main as main_module
        from tagorganizer import db

        window = window_for()
        target = add_profile(window, "other", tmp_path)
        connection = sqlite3.connect(target)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE placeholder (id INTEGER)")
        connection.commit()
        connection.close()
        paths = self._select_photos(window, "a.jpg", "b.jpg")
        answer_move_dialog(monkeypatch, "other")
        titles = []

        class RecordingBox:
            @staticmethod
            def critical(parent, title, text):
                titles.append(title)

        monkeypatch.setattr(main_module, "QMessageBox", RecordingBox)

        window.move_selection_to_profile()

        assert titles == ["Cannot Move to Target"]
        assert db.get_number_of_items() == len(paths)
        assert len(window.selection) == len(paths)

    def test_a_successful_move_clears_the_selection_and_takes_the_photos(
        self, window_for, tmp_path, monkeypatch
    ):
        """The selected ids belonged to rows that have now left this database."""
        from tagorganizer import db

        window = window_for()
        target = add_profile(window, "other", tmp_path)
        paths = self._select_photos(window, "a.jpg", "b.jpg")
        answer_move_dialog(monkeypatch, "other")

        window.move_selection_to_profile()

        assert len(window.selection) == 0
        assert db.get_number_of_items() == 0
        assert database_uris(target) == sorted(paths)
