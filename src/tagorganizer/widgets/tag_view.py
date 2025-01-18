from qtpy.QtWidgets import QTreeView, QMenu
from qtpy.QtCore import Qt, Signal, QDataStream, QIODevice, QPoint
from qtpy.QtGui import QStandardItemModel, QStandardItem

from .. import db
from .tag_bar import NOT_ALLOWED_TAGS


class CustomStandardItemModel(QStandardItemModel):
    itemsMoved = Signal(object, object)

    def dropMimeData(self, data, action, row, column, parent):
        result = super().dropMimeData(data, action, row, column, parent)
        fmt = "application/x-qstandarditemmodeldatalist"
        if not result:
            return result

        destination_item = self.itemFromIndex(parent)
        if data.hasFormat(fmt):
            d = data.data(fmt)
            data_stream = QDataStream(d, QIODevice.ReadOnly)

            row = data_stream.readInt32()
            column = data_stream.readInt32()
            source_item = self.item(row, column)
            self.itemsMoved.emit(source_item, destination_item)
        return result


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

    def on_tag_moved(self, src, dest):
        src_id = None
        dest_id = None
        if src:
            src_id = src.data()
        if dest:
            dest_id = dest.data()

        src = db.get_tag_by_id(src_id)
        dest = db.get_tag_by_id(dest_id)

        db.set_parent_tag(src, dest)

    def show_tag_menu(self, position: QPoint):
        index = self.tag_view.indexAt(position)
        if not index.isValid():
            return

        tag_id = self.tag_model.itemFromIndex(index).data()
        menu = QMenu()

        delete_action = menu.addAction("Delete Tag")
        delete_action.triggered.connect(lambda: self.delete_tag(tag_id))

        menu.exec(self.tag_view.viewport().mapToGlobal(position))

    def select_tag(self, index: int):
        tag_name = self.tag_model.itemFromIndex(index).text()
        self.main.tag_bar.add_tag(tag_name)

    def delete_tag(self, tag_id: int):
        db.delete_tag(tag_id)
        self.update_tags()

    def add_tag(self, name: str, id: int = None, background=None):
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

        for tag in NOT_ALLOWED_TAGS:
            self.add_tag(tag, background=Qt.lightGray)
