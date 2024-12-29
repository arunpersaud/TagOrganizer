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
from qtpy.QtGui import QStandardItemModel, QStandardItem, QPixmap, QPainter, QPen
from qtpy.QtCore import Qt, Signal, QDataStream, QIODevice, QEvent


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


class FramedLabel(QLabel):
    def __init__(self, filename, *args, **kwargs):
        super().__init__(*args, **kwargs)
        pixmap = load_pixmap(filename)
        self.setPixmap(pixmap)
        self.setAlignment(Qt.AlignCenter)
        self.selected = False
        self.highlight = False

    def set_selected(self, selected):
        self.selected = selected
        self.update()

    def set_highlight(self, selected):
        self.highlight = selected
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.selected:
            painter = QPainter(self)
            pen = QPen(Qt.blue, 5)
            painter.setPen(pen)
            painter.drawRect(self.rect())
        if self.highlight:
            painter = QPainter(self)
            pen = QPen(Qt.red, 5)
            painter.setPen(pen)
            painter.drawRect(self.rect())


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
        self.highlight = 0

        # we need to keep a reference to the widgets in the grid, otherwise
        # itemAtPosition will return a QLabel
        self.widgets = []

    def show_images(self, items):
        row = 0
        col = 0

        self.clear()

        for i, item in enumerate(items):
            label = FramedLabel(str(item.uri))
            self.widgets.append(label)
            self.layout.addWidget(label, row, col)
            item = self.layout.itemAtPosition(row, col).widget()
            col += 1
            if col >= self.columns:
                col = 0
                row += 1
        self.set_highlight(self.highlight)

    def clear(self):
        for row in range(self.layout.rowCount()):
            for col in range(self.layout.columnCount()):
                item = self.layout.itemAtPosition(row, col)
                if item is not None:
                    widget = item.widget()
                    if widget is not None:
                        widget.deleteLater()
        self.widgets = []

    def set_highlight(self, new):
        if self.widgets:
            old_n = self.highlight % len(self.widgets)
            self.widgets[old_n].set_highlight(False)

        self.highlight = new

        if self.widgets:
            new_n = self.highlight % len(self.widgets)
            self.widgets[new_n].set_highlight(True)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.page = 0

        self.highlight_n = 0

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

        # install event filter
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, source, event):
        if event.type() == QEvent.KeyPress:
            if event.key() in [Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down]:
                self.keyPressEvent(event)
                return True  # Event has been handled
        return super().eventFilter(source, event)

    def keyPressEvent(self, event):
        N = db.get_number_of_items()
        if event.key() == Qt.Key_Left:
            self.highlight_n = max(self.highlight_n - 1, 0)
        elif event.key() == Qt.Key_Right:
            self.highlight_n = min(self.highlight_n + 1, N)
        elif event.key() == Qt.Key_Up:
            if event.modifiers() & Qt.ShiftModifier:
                self.highlight_n = max(self.highlight_n - 25, 0)
            else:
                self.highlight_n = max(self.highlight_n - 5, 0)
        elif event.key() == Qt.Key_Down:
            if event.modifiers() & Qt.ShiftModifier:
                self.highlight_n = min(self.highlight_n + 25, N)
            else:
                self.highlight_n = min(self.highlight_n + 5, N)
        new_page = self.highlight_n // 25
        if new_page != self.page:
            self.page = new_page
            files = db.get_images(self.page)
            self.image_container.show_images(files)
        self.image_container.set_highlight(self.highlight_n)

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
