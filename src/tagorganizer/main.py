"""
Copyright 2024 Arun Persaud.

This file is part of TagOrganizer.

TagOrganizer is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or (at
your option) any later version.

TagOrganizer is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with TagOrganizer. If not, see <https://www.gnu.org/licenses/>.

"""

from functools import lru_cache
from pathlib import Path
import sys

from qtpy.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QMainWindow,
    QStatusBar,
    QGridLayout,
    QTreeView,
    QVBoxLayout,
    QHBoxLayout,
    QFileDialog,
    QWidget,
    QLabel,
    QLineEdit,
    QAction,
    QMessageBox,
)
from qtpy.QtGui import QStandardItemModel, QStandardItem, QPixmap
from qtpy.QtCore import Qt, Signal, QDataStream, QIODevice


from . import db
from .config import get_or_create_db_path
from .migrations import upgrade_db


class AddTagDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Tag")

        self.layout = QFormLayout(self)

        self.tag_name_edit = QLineEdit(self)
        self.layout.addRow("Tag Name:", self.tag_name_edit)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def get_tag_name(self):
        return self.tag_name_edit.text()


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


@lru_cache(1_000)
def load_pixmap(file):
    pixmap = QPixmap(file)
    pixmap = pixmap.scaledToWidth(200, Qt.SmoothTransformation)
    return pixmap


class ImageGridWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.columns = 5
        self.layout = QGridLayout()
        self.setLayout(self.layout)

    def show_images(self, items):
        row = 0
        col = 0

        self.clear()

        for i, item in enumerate(items):
            label = QLabel(f"{item.uri}")
            pixmap = load_pixmap(str(item.uri))
            label.setPixmap(pixmap)
            label.setAlignment(Qt.AlignCenter)
            self.layout.addWidget(label, row, col)

            col += 1
            if col >= self.columns:
                col = 0
                row += 1

    def clear(self):
        for row in range(self.layout.rowCount()):
            for col in range(self.layout.columnCount()):
                item = self.layout.itemAtPosition(row, col)
                if item is not None:
                    widget = item.widget()
                    if widget is not None:
                        widget.deleteLater()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.page = 0

        self.setWindowTitle("Tag Organizer")

        # Set up the menu bar
        menu_bar = self.menuBar()
        edit_menu = menu_bar.addMenu("Edit")

        add_tag_action = QAction("Add Tag", self)
        add_tag_action.triggered.connect(self.add_tag)
        add_tag_action.setShortcut("Ctrl+N")
        edit_menu.addAction(add_tag_action)

        add_images_action = QAction("Add Images", self)
        add_images_action.triggered.connect(self.add_directory)
        add_images_action.setShortcut("Ctrl+I")
        edit_menu.addAction(add_images_action)

        # Set up the status bar
        self.setStatusBar(QStatusBar(self))

        # Set up the central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Set up the layout
        layout = QHBoxLayout(central_widget)

        # Set up the tag view
        self.tag_view = QTreeView()
        self.tag_model = CustomStandardItemModel()
        self.tag_model.setHorizontalHeaderLabels(["Tags"])
        self.tag_view.setModel(self.tag_model)
        self.tag_view.setDragDropMode(QTreeView.InternalMove)
        self.tag_view.setSelectionMode(QTreeView.ExtendedSelection)

        self.tag_model.itemsMoved.connect(self.on_tag_moved)

        # Populate the tag view with some example tags
        self.populate_tags()

        # Set up the main area with a splitter
        splitter = QVBoxLayout()

        # Set up the timeline
        self.timeline = QLabel("Timeline: Number of files per month")
        self.timeline.setAlignment(Qt.AlignCenter)
        splitter.addWidget(self.timeline)

        # Set up the image view
        self.image_container = ImageGridWidget()

        files = db.get_images(self.page)
        self.image_container.show_images(files)

        splitter.addWidget(self.image_container)

        # Add the tag view and the main area to the layout
        layout.addWidget(self.tag_view)
        layout.addLayout(splitter)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Left:
            self.page = max(self.page - 1, 0)
            files = db.get_images(self.page)
            self.image_container.show_images(files)
        elif event.key() == Qt.Key_Right:
            N = db.get_number_of_items() // 25
            self.page = min(self.page + 1, N)
            files = db.get_images(self.page)
            self.image_container.show_images(files)
        else:
            super().keyPressEvent(event)

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

    def populate_tags(self):
        tags = db.get_all_tags()
        # create Qt Items
        out = []
        for t in tags:
            tmp = QStandardItem(t.name)
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

    def add_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")

        if directory:
            print("selected: ", directory)
            mydir = Path(directory)
            files = list(mydir.rglob("*.jpg")) + list(mydir.rglob("*.JPG"))
            db.add_images(files)
            files = db.get_images(0)
            self.image_container.show_images(files)

    def add_tag(self):
        dialog = AddTagDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            tag_name = dialog.get_tag_name()
            if tag_name:
                existing_tag = db.get_tag(tag_name)
                if existing_tag:
                    QMessageBox.warning(
                        self, "Duplicate Tag", "The tag name already exists."
                    )
                else:
                    tag_id = db.add_tag(tag_name)
                    tag_item = QStandardItem(tag_name)
                    tag_item.setData(tag_id)
                    self.tag_model.appendRow(tag_item)


def main():
    db.create_db()
    print(f"DB: {get_or_create_db_path()}")

    # run alembic
    upgrade_db()

    app = QApplication([])
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
