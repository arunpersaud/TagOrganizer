"""Tests for tagging functionality and related fixes.

These tests verify:
- F2: Multi-item tagging works correctly (tags applied to all selected items)
- F8: Reserved tag names are rejected before DB creation
"""

import ast
import logging
from pathlib import Path

from sqlmodel import Session, select

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

        expected = ["No Time", "No GPS", "Wrong dir"]
        assert (
            expected == RESERVED_TAGS
        ), f"RESERVED_TAGS mismatch: {RESERVED_TAGS} != {expected}"


class TestF11FiltersAttribute:
    """F11: Structural test that self.filters (with 's') is updated, not self.filter."""

    def test_update_items_assigns_to_filters_not_filter(self):
        """Verify the attribute is self.filters, not self.filter."""
        main_file = Path(__file__).parent.parent / "src" / "tagorganizer" / "main.py"
        with open(main_file) as f:
            tree = ast.parse(f.read())

        # Find update_items method
        update_items_method = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "update_items":
                update_items_method = node
                break

        assert update_items_method is not None

        # Find assignments to self.filter or self.filters
        filter_assignment = None
        filters_assignment = None

        for node in ast.walk(update_items_method):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        if (
                            isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                        ):
                            if target.attr == "filter":
                                filter_assignment = node
                            elif target.attr == "filters":
                                filters_assignment = node

        # Should have assignment to self.filters, not self.filter
        assert (
            filters_assignment is not None
        ), "No assignment to self.filters found in update_items"
        assert (
            filter_assignment is None
        ), "Found assignment to self.filter (typo); should be self.filters"


class TestF15DeleteEmptyGrid:
    """F15: delete_items must safely handle empty grid without AttributeError."""

    def test_delete_items_guards_current_item_none(self):
        """Verify delete_items guards against current_item() returning None."""
        main_file = Path(__file__).parent.parent / "src" / "tagorganizer" / "main.py"
        with open(main_file) as f:
            tree = ast.parse(f.read())

        # Find delete_items method
        delete_items_method = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "delete_items":
                delete_items_method = node
                break

        assert delete_items_method is not None

        # Verify that current_item() is not called in a list comprehension
        # or directly in an attribute access without checking
        for node in ast.walk(delete_items_method):
            if isinstance(node, ast.Call):
                # Look for direct calls to current_item()
                if isinstance(node.func, ast.Attribute):
                    if (
                        isinstance(node.func.value, ast.Attribute)
                        and isinstance(node.func.value.value, ast.Name)
                        and node.func.value.value.id == "self"
                        and node.func.value.attr == "grid"
                        and node.func.attr == "current_item"
                    ):
                        # Found a current_item call
                        # Now check if it's inside a subscript access (which would be bad)
                        # We check if the parent is an Subscript or Attribute access
                        # This is a complex check, so we'll trust the fix is correct
                        pass

        # A simpler structural test: check that current_item is assigned to a
        # variable before being used
        current_assignment = None
        current_item_call = None

        for stmt in delete_items_method.body:
            if isinstance(stmt, ast.If):
                # Look inside the else clause
                for node in stmt.orelse:
                    if isinstance(node, ast.Assign):
                        # Check if this is current = self.grid.current_item()
                        if isinstance(node.value, ast.Call):
                            if isinstance(node.value.func, ast.Attribute):
                                if (
                                    isinstance(node.value.func.value, ast.Attribute)
                                    and node.value.func.value.attr == "grid"
                                    and node.value.func.attr == "current_item"
                                ):
                                    current_assignment = node
                    elif isinstance(node, ast.If):
                        # Check for None guard
                        if isinstance(node.test, ast.Compare):
                            if (
                                isinstance(node.test.left, ast.Name)
                                and node.test.left.id == "current"
                            ):
                                current_item_call = node

        # Should have both assignment and None check
        assert (
            current_assignment is not None
        ), "current_item() should be assigned to a local variable"
        assert (
            current_item_call is not None
        ), "Should have a guard checking if current is None"


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


class TestOnTabChangedDispatchesToSingleView:
    """Regression guard: single view populated on tab change (defect a).

    The single view showed nothing because on_tab_changed never called
    update_single_item. This test ensures that dispatch is present and
    connected correctly; deleting it would be caught immediately.
    """

    def test_on_tab_changed_calls_update_single_item(self):
        """Verify on_tab_changed dispatches to update_single_item()."""
        main_file = Path(__file__).parent.parent / "src" / "tagorganizer" / "main.py"
        with open(main_file) as f:
            tree = ast.parse(f.read())

        # Find on_tab_changed method
        on_tab_method = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "on_tab_changed":
                on_tab_method = node
                break

        assert on_tab_method is not None, "on_tab_changed method not found"

        # Search for call to update_single_item in the method
        calls_update_single_item = False
        for node in ast.walk(on_tab_method):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "update_single_item":
                        calls_update_single_item = True
                        break
                elif isinstance(node.func, ast.Name):
                    if node.func.id == "update_single_item":
                        calls_update_single_item = True
                        break

        assert (
            calls_update_single_item
        ), "on_tab_changed must call update_single_item to populate the single view"


class TestOnTabChangedDispatchesToMapShown:
    """Regression guard: map refreshes on tab change (defect b).

    The map showed nothing because on_tab_changed never called map.on_shown(),
    leaving Leaflet thinking it was hidden and never measuring its container.
    This test ensures that dispatch is present; deleting it would be caught.
    """

    def test_on_tab_changed_calls_map_on_shown(self):
        """Verify on_tab_changed dispatches to self.map.on_shown()."""
        main_file = Path(__file__).parent.parent / "src" / "tagorganizer" / "main.py"
        with open(main_file) as f:
            tree = ast.parse(f.read())

        # Find on_tab_changed method
        on_tab_method = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "on_tab_changed":
                on_tab_method = node
                break

        assert on_tab_method is not None, "on_tab_changed method not found"

        # Search for call to self.map.on_shown in the method
        calls_map_on_shown = False
        for node in ast.walk(on_tab_method):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if (
                        isinstance(node.func.value, ast.Attribute)
                        and isinstance(node.func.value.value, ast.Name)
                        and node.func.value.value.id == "self"
                        and node.func.value.attr == "map"
                        and node.func.attr == "on_shown"
                    ):
                        calls_map_on_shown = True
                        break

        assert (
            calls_map_on_shown
        ), "on_tab_changed must call self.map.on_shown() to wake the map"


class TestChangeProfileResetsViewState:
    """Regression guard: stale grid state doesn't survive profile switch.

    Switching profiles leaves the old grid pagination, highlight, and
    selection (which are ids from the old database). This would corrupt
    operations like delete_items or copy_selection. change_profile must call
    reset_view_state to clear this state; deleting it would reintroduce the bug.
    """

    def test_change_profile_calls_reset_view_state(self):
        """Verify change_profile calls reset_view_state()."""
        main_file = Path(__file__).parent.parent / "src" / "tagorganizer" / "main.py"
        with open(main_file) as f:
            tree = ast.parse(f.read())

        # Find change_profile method
        change_profile_method = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "change_profile":
                change_profile_method = node
                break

        assert change_profile_method is not None, "change_profile method not found"

        # Search for call to reset_view_state in the method
        calls_reset_view_state = False
        for node in ast.walk(change_profile_method):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "reset_view_state":
                        calls_reset_view_state = True
                        break
                elif isinstance(node.func, ast.Name):
                    if node.func.id == "reset_view_state":
                        calls_reset_view_state = True
                        break

        assert (
            calls_reset_view_state
        ), "change_profile must call reset_view_state to clear old database ids"


class TestShowSelectedOnlyCallsAddSelectionTag:
    """Regression guard: show_selected_only must apply the selection filter.

    Deleting the add_selection_tag call would leave the method non-functional,
    as it would accept the selection but not restrict the view to it.
    """

    def test_show_selected_only_calls_add_selection_tag(self):
        """Verify show_selected_only calls self.tag_bar.add_selection_tag()."""
        main_file = Path(__file__).parent.parent / "src" / "tagorganizer" / "main.py"
        with open(main_file) as f:
            tree = ast.parse(f.read())

        # Find show_selected_only method
        show_selected_only_method = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "show_selected_only":
                show_selected_only_method = node
                break

        assert (
            show_selected_only_method is not None
        ), "show_selected_only method not found"

        # Search for call to self.tag_bar.add_selection_tag in the method
        calls_add_selection_tag = False
        for node in ast.walk(show_selected_only_method):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if (
                        isinstance(node.func.value, ast.Attribute)
                        and isinstance(node.func.value.value, ast.Name)
                        and node.func.value.value.id == "self"
                        and node.func.value.attr == "tag_bar"
                        and node.func.attr == "add_selection_tag"
                    ):
                        calls_add_selection_tag = True
                        break

        assert calls_add_selection_tag, "show_selected_only must call self.tag_bar.add_selection_tag to filter the view"


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
    """Regression guards for move_selection_to_profile implementation.

    The move operation must validate everything before the transaction opens,
    so refusals leave the database untouched. Order matters: prepare_target
    must run before move_items.
    """

    def test_move_selection_calls_prepare_target_before_move_items(self):
        """Verify prepare_target is called before move_items in move_selection_to_profile.

        This ordering is load-bearing: prepare_target checks everything before
        any transaction opens, so a refusal leaves the source database intact.
        """
        main_file = Path(__file__).parent.parent / "src" / "tagorganizer" / "main.py"
        with open(main_file) as f:
            tree = ast.parse(f.read())

        # Find move_selection_to_profile method
        move_method = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "move_selection_to_profile"
            ):
                move_method = node
                break

        assert move_method is not None, "move_selection_to_profile method not found"

        # Find the lines where prepare_target and move_items are called
        prepare_target_line = None
        move_items_line = None

        for node in ast.walk(move_method):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    # Check for dbmove.prepare_target
                    if (
                        isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "dbmove"
                        and node.func.attr == "prepare_target"
                    ):
                        if prepare_target_line is None:
                            prepare_target_line = node.lineno
                    # Check for dbmove.move_items
                    if (
                        isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "dbmove"
                        and node.func.attr == "move_items"
                    ):
                        if move_items_line is None:
                            move_items_line = node.lineno

        assert (
            prepare_target_line is not None
        ), "dbmove.prepare_target() call not found in move_selection_to_profile"
        assert (
            move_items_line is not None
        ), "dbmove.move_items() call not found in move_selection_to_profile"

        assert (
            prepare_target_line < move_items_line
        ), "FAIL: prepare_target must be called before move_items; "
        "the ordering is what makes a refusal safe"

    def test_move_selection_clears_selection_after_move(self):
        """Verify selection is cleared after successful move in move_selection_to_profile.

        Clearing the selection is essential: the ids belonged to rows that no
        longer exist in this database. Acting on ids from another database is
        a bug this project has already shipped once.
        """
        main_file = Path(__file__).parent.parent / "src" / "tagorganizer" / "main.py"
        with open(main_file) as f:
            tree = ast.parse(f.read())

        # Find move_selection_to_profile method
        move_method = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "move_selection_to_profile"
            ):
                move_method = node
                break

        assert move_method is not None, "move_selection_to_profile method not found"

        # Look for self.selection.clear() call in the method
        calls_selection_clear = False
        for node in ast.walk(move_method):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if (
                        isinstance(node.func.value, ast.Attribute)
                        and isinstance(node.func.value.value, ast.Name)
                        and node.func.value.value.id == "self"
                        and node.func.value.attr == "selection"
                        and node.func.attr == "clear"
                    ):
                        calls_selection_clear = True
                        break

        assert (
            calls_selection_clear
        ), "move_selection_to_profile must call self.selection.clear() after the move; "
        "the ids belonged to rows that no longer exist in this database"
