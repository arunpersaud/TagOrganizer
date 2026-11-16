import logging

from qtpy.QtWidgets import QTreeView, QMenu, QMessageBox, QSizePolicy
from qtpy.QtCore import Qt, Signal, QPoint
from qtpy.QtGui import QStandardItemModel, QStandardItem

from .. import db
from ..tag_moves import refuse_move
from .tag_bar import RESERVED_TAGS

logger = logging.getLogger(__name__)


class CustomStandardItemModel(QStandardItemModel):
    """Reports drops with the tags that were dragged, not Qt's mime encoding.

    Qt encodes a dragged item by its row and column under its own parent, and
    the model then resolves those numbers at the top level. For a nested tag
    that picks the wrong tag, so the view records the dragged ids itself.
    """

    itemsMoved = Signal(object, object, bool)

    def __init__(self):
        super().__init__()
        # Set by the view for the length of one drag; empty otherwise.
        self.drag_ids: list[int | None] = []

    def dropMimeData(self, data, action, row, column, parent):
        if not self.drag_ids:
            return False
        target = self.itemFromIndex(parent) if parent.isValid() else None
        # A drop onto a reserved button has an item with no id; a drop at the
        # top level has no item at all. The rules treat them differently.
        target_is_reserved = target is not None and target.data() is None
        target_id = target.data() if target is not None else None
        self.itemsMoved.emit(list(self.drag_ids), target_id, target_is_reserved)
        # False: the database is the source of truth, so Qt must not also
        # move the rows. Returning True would make the view remove its own
        # copy of the source at the end of the drag, using indexes that the
        # rebuild in on_tag_moved has already invalidated.
        return False


class TagView(QTreeView):
    def __init__(self, main):
        super().__init__()
        self.main = main

        self.tag_model = CustomStandardItemModel()
        self.tag_model.setHorizontalHeaderLabels(["Tags"])
        self.setModel(self.tag_model)
        self.setDragDropMode(QTreeView.InternalMove)
        self.setSelectionMode(QTreeView.ExtendedSelection)

        self.tag_model.itemsMoved.connect(self.on_tag_moved)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_tag_menu)

        self.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.doubleClicked.connect(self.select_tag)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

    def startDrag(self, supported_actions):
        """Record which tags are being dragged, then let Qt run the drag.

        Every selected tag moves, not only the one under the pointer, so the
        ids are taken from the selection rather than from the drag mime data.
        """
        ids: list[int | None] = []
        for index in self.selectedIndexes():
            item = self.tag_model.itemFromIndex(index)
            if item is not None and item.data() not in ids:
                ids.append(item.data())
        self.tag_model.drag_ids = ids
        try:
            super().startDrag(supported_actions)
        finally:
            self.tag_model.drag_ids = []

    def on_tag_moved(self, moving, target_id, target_is_reserved):
        """Re-parent the dragged tags, or make them top level.

        target_id is None for a drop at the top level. The rules are checked
        against the whole vocabulary, so a cycle is refused before any row is
        written.
        """
        parents = {tag.id: tag.parent_id for tag in db.get_all_tags()}
        refusal = refuse_move(moving, target_id, target_is_reserved, parents)
        if refusal:
            self.main.messages.add(refusal)
            self.update_tags()
            return

        parent = db.get_tag_by_id(target_id) if target_id is not None else None
        for tag_id in moving:
            if parents.get(tag_id) == target_id:
                continue
            child = db.get_tag_by_id(tag_id)
            try:
                db.set_parent_tag(child, parent)
            except ValueError as error:
                # The database refuses a placement that would make a tag its own
                # ancestor. The rules above catch the same case first; this is
                # the backstop for a stored hierarchy they did not see.
                self.main.messages.add(f"[ERROR] Could not move tag: {error}")
            except Exception as error:
                # Reported rather than raised: an exception here would abort
                # the drag, and the tree must still be redrawn from the data.
                logger.exception("could not move tag %s", tag_id)
                self.main.messages.add(f"[ERROR] Could not move tag: {error}")
        self.update_tags()

    def show_tag_menu(self, position: QPoint):
        index = self.indexAt(position)
        if not index.isValid():
            return

        tag_id = self.tag_model.itemFromIndex(index).data()
        self.tag_menu = QMenu()

        remove_action = self.tag_menu.addAction("Remove from selected photos")
        remove_action.triggered.connect(
            lambda: self.main.remove_tag_from_selection(tag_id)
        )

        delete_action = self.tag_menu.addAction("Delete Tag")
        delete_action.triggered.connect(lambda: self.delete_tag(tag_id))

        self.tag_menu.exec(self.viewport().mapToGlobal(position))

    def select_tag(self, index: int):
        tag_name = self.tag_model.itemFromIndex(index).text()
        self.main.tag_bar.add_tag(tag_name)

    def delete_tag(self, tag_id: int):
        """Delete a tag from the whole library, after saying so and checking it.

        Deleting is not undoable and touches every photo carrying the tag, so
        the user confirms first. A tag with subtags is refused here with the
        reason, because the database quietly declines that case.
        """
        tag = db.get_tag_by_id(tag_id)
        if tag is None:
            self.update_tags()
            return

        subtags = [t.name for t in db.get_all_tags() if t.parent_id == tag_id]
        if subtags:
            QMessageBox.warning(
                self,
                "Cannot delete tag",
                f"{tag.name!r} still has {len(subtags)} subtag(s): "
                f"{', '.join(sorted(subtags))}.\n\n"
                "Move or delete them first.",
            )
            return

        answer = QMessageBox.question(
            self,
            "Delete Tag",
            f"Delete {tag.name!r} from the whole library?\n\n"
            "It is removed from every photo that has it. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        db.delete_tag(tag_id)
        if db.get_tag_by_id(tag_id) is not None:
            QMessageBox.warning(
                self, "Cannot delete tag", f"{tag.name!r} was not deleted."
            )
            self.update_tags()
            return

        # A filter chip naming the deleted tag would keep filtering on a name
        # that no longer exists, so it goes too.
        self.main.tag_bar.forget_tag(tag.name)
        self.main.refresh_after_data_change()

    def add_tag(self, name: str, id: int | None = None, background=None):
        """Add a tag at the top level of the hierachy."""
        tmp = QStandardItem(name)
        tmp.setEditable(False)
        if background:
            tmp.setBackground(background)
        if id:
            tmp.setData(id)
        self.tag_model.appendRow(tmp)

    def update_tags(self):
        self.tag_model.removeRows(0, self.tag_model.rowCount())

        tags = db.get_all_tags()

        out = []
        for t in tags:
            tmp = QStandardItem(t.name)
            tmp.setEditable(False)
            tmp.setData(t.id)
            out.append((tmp, t))

        # set up the hierachy
        for tmp, t in out:
            if t.parent_id is None:
                self.tag_model.appendRow(tmp)
            else:
                for a, b in out:
                    if b.id == t.parent_id:
                        a.appendRow(tmp)
                        break

        for tag in RESERVED_TAGS:
            self.add_tag(tag, background=Qt.lightGray)
