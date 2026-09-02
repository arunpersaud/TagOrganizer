"""A window for tidying the tag vocabulary: renaming and merging.

Reorganising the hierarchy stays in the main window's tag tree, where dragging
one tag onto another already works. This window covers the two operations that
had no home: giving a tag a different name, and folding two tags into one.
"""

from qtpy.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

PATH_SEPARATOR = " > "


def tag_paths(tags) -> list[tuple[int, str]]:
    """Every tag as (id, full path), sorted by path.

    The full ancestry rather than the bare name, because two tags at different
    levels may share a name and a picker showing only "Japan" twice would give
    the user no way to tell which one they are about to rename or delete.

    A dangling parent_id degrades to the bare name and a parent cycle stops
    rather than spinning: this window exists to repair a broken vocabulary, so
    it must survive one.
    """
    by_id = {tag.id: tag for tag in tags}

    def path_for(tag):
        parts = [tag.name]
        seen = {tag.id}
        parent_id = tag.parent_id
        while parent_id is not None and parent_id in by_id and parent_id not in seen:
            seen.add(parent_id)
            parent = by_id[parent_id]
            parts.append(parent.name)
            parent_id = parent.parent_id
        return PATH_SEPARATOR.join(reversed(parts))

    return sorted(((tag.id, path_for(tag)) for tag in tags), key=lambda pair: pair[1])


class TagEditorDialog(QDialog):
    """Pick one tag to rename, or exactly two to merge."""

    def __init__(self, tags, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Tags")

        layout = QVBoxLayout()

        self.tag_list = QListWidget()
        self.tag_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self._ids = []
        for tag_id, path in tag_paths(tags):
            self.tag_list.addItem(path)
            self._ids.append(tag_id)
        layout.addWidget(QLabel("Select one tag to rename, or two to merge:"))
        layout.addWidget(self.tag_list)

        self.rename_button = QPushButton("Rename...")
        self.merge_button = QPushButton("Merge...")
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        for button in (self.rename_button, self.merge_button, self.close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.setLayout(layout)

        self.tag_list.itemSelectionChanged.connect(self._selection_changed)
        self._selection_changed()

    def selected_tag_ids(self) -> list[int]:
        """The chosen tags' ids, in the order the list shows them."""
        return [
            self._ids[row]
            for row in range(self.tag_list.count())
            if self.tag_list.item(row).isSelected()
        ]

    def _selection_changed(self):
        """Offer only the operation the current selection can actually perform.

        Merge needs exactly two: it is directional and destructive, so guessing
        which of three tags survives is not something to leave to chance.
        """
        count = len(self.selected_tag_ids())
        self.rename_button.setEnabled(count == 1)
        self.merge_button.setEnabled(count == 2)
