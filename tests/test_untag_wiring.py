"""Removing a tag from the selected photos.

The database operation is covered in tests/test_tag_editing.py; these guard the
wiring, in the ast style this codebase uses for widget code.
"""

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "tagorganizer"


def _tree(relative):
    return ast.parse((SRC / relative).read_text())


def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


class TestContextMenuEntry:
    def test_the_tag_menu_offers_removing_from_selected_photos(self):
        """Until now a mistagged photo could only be fixed by deleting the tag
        from the whole library."""
        source = (SRC / "widgets" / "tag_view.py").read_text()
        assert "Remove from selected" in source

    def test_the_entry_is_wired_to_a_handler(self):
        node = _function(_tree("widgets/tag_view.py"), "show_tag_menu")
        assert node is not None
        called = {
            n.func.attr
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "remove_tag_from_selection" in called


class TestMainWindowHandler:
    def test_the_handler_removes_links_and_refreshes(self):
        node = _function(_tree("main.py"), "remove_tag_from_selection")
        assert node is not None, "MainWindow has no remove_tag_from_selection"
        called = {
            n.func.attr
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "remove_tags" in called, "it must call db.remove_tags"
        assert "update_items" in called, "the grid must refresh afterwards"

    def test_the_handler_reports_what_it_did(self):
        """'Nothing happened' and 'none of them had that tag' look identical."""
        node = _function(_tree("main.py"), "remove_tag_from_selection")
        called = {
            n.func.attr
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "add" in called, "it must report through messages"
