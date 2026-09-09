"""The tag editor: renaming and merging from one window.

The path building and ordering are pure functions and tested directly. The
dialog itself needs a QApplication, guarded as elsewhere.
"""

import os


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tagorganizer.widgets.tag_editor import tag_paths


class _Tag:
    """Stands in for a Tag row; tag_paths only needs id, name and parent_id."""

    def __init__(self, id, name, parent_id=None):
        self.id = id
        self.name = name
        self.parent_id = parent_id


class TestTagPaths:
    def test_a_top_level_tag_is_its_own_path(self):
        assert tag_paths([_Tag(1, "Travel")]) == [(1, "Travel")]

    def test_a_child_shows_its_ancestry(self):
        """Two tags can share a name at different levels, so the bare name is
        not enough to tell them apart in a picker."""
        tags = [_Tag(1, "Travel"), _Tag(2, "Japan", parent_id=1)]
        assert dict(tag_paths(tags))[2] == "Travel > Japan"

    def test_deep_nesting(self):
        tags = [
            _Tag(1, "Travel"),
            _Tag(2, "Japan", parent_id=1),
            _Tag(3, "Kyoto", parent_id=2),
        ]
        assert dict(tag_paths(tags))[3] == "Travel > Japan > Kyoto"

    def test_sorted_by_path(self):
        tags = [_Tag(1, "Zebra"), _Tag(2, "Apple")]
        assert [name for _, name in tag_paths(tags)] == ["Apple", "Zebra"]

    def test_a_missing_parent_does_not_hang_or_raise(self):
        """A dangling parent_id should degrade to the bare name, not crash the
        window that is meant to fix such problems."""
        assert dict(tag_paths([_Tag(2, "Orphan", parent_id=99)]))[2] == "Orphan"

    def test_a_parent_cycle_does_not_hang(self):
        """Defensive: a cycle should never exist, but the editor must not spin."""
        tags = [_Tag(1, "A", parent_id=2), _Tag(2, "B", parent_id=1)]
        paths = dict(tag_paths(tags))
        assert set(paths) == {1, 2}

    def test_empty(self):
        assert tag_paths([]) == []


class TestDialog:
    def test_lists_every_tag_by_path(self, qapp):
        from tagorganizer.widgets.tag_editor import TagEditorDialog

        tags = [_Tag(1, "Travel"), _Tag(2, "Japan", parent_id=1)]
        dialog = TagEditorDialog(tags)

        listed = [
            dialog.tag_list.item(i).text() for i in range(dialog.tag_list.count())
        ]
        assert listed == ["Travel", "Travel > Japan"]

    def test_merge_is_only_offered_for_exactly_two_tags(self, qapp):
        """Merge is directional and destructive; it needs exactly a pair."""
        from tagorganizer.widgets.tag_editor import TagEditorDialog

        dialog = TagEditorDialog([_Tag(1, "A"), _Tag(2, "B"), _Tag(3, "C")])

        assert dialog.merge_button.isEnabled() is False
        dialog.tag_list.item(0).setSelected(True)
        dialog._selection_changed()
        assert dialog.merge_button.isEnabled() is False
        dialog.tag_list.item(1).setSelected(True)
        dialog._selection_changed()
        assert dialog.merge_button.isEnabled() is True
        dialog.tag_list.item(2).setSelected(True)
        dialog._selection_changed()
        assert dialog.merge_button.isEnabled() is False

    def test_rename_is_only_offered_for_one_tag(self, qapp):
        from tagorganizer.widgets.tag_editor import TagEditorDialog

        dialog = TagEditorDialog([_Tag(1, "A"), _Tag(2, "B")])
        dialog.tag_list.item(0).setSelected(True)
        dialog._selection_changed()
        assert dialog.rename_button.isEnabled() is True

        dialog.tag_list.item(1).setSelected(True)
        dialog._selection_changed()
        assert dialog.rename_button.isEnabled() is False

    def test_selected_ids_are_reported_in_list_order(self, qapp):
        from tagorganizer.widgets.tag_editor import TagEditorDialog

        dialog = TagEditorDialog([_Tag(7, "A"), _Tag(9, "B")])
        dialog.tag_list.item(0).setSelected(True)
        dialog.tag_list.item(1).setSelected(True)

        assert dialog.selected_tag_ids() == [7, 9]


class TestMenuWiring:
    def test_the_editor_is_reachable_from_the_edit_menu(self):
        from pathlib import Path as P

        source = (
            P(__file__).parent.parent / "src" / "tagorganizer" / "main.py"
        ).read_text()
        assert "Edit Tags..." in source

    def test_merge_confirms_before_destroying_a_tag(self):
        """Merging cannot be undone, so it must ask, and name the casualty."""
        import ast
        from pathlib import Path as P

        tree = ast.parse(
            (P(__file__).parent.parent / "src" / "tagorganizer" / "main.py").read_text()
        )
        node = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_merge_tags"
        )
        called = {
            n.func.attr
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "question" in called, "merge must confirm first"
        assert "merge_tags" in called
