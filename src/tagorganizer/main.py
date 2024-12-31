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

from pathlib import Path
import sys
import time

from qtpy.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
    QMenu,
)
from qtpy.QtGui import QStandardItemModel, QStandardItem
from qtpy.QtCore import (
    Qt,
    Signal,
    QDataStream,
    QIODevice,
    QEvent,
    QTimer,
    QPoint,
)


from . import db
from . import config

from .widgets import AddTagDialog, ImageGridWidget, ProfileDialog
from .widgets.helper import load_pixmap, load_full_pixmap, CommaCompleter


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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.page = 0

        self.highlight_n = 0
        self.selected = []

        self.config = config.ConfigManager()
        self.setWindowTitle(f"Tag Organizer -- Profile {self.config.profile}")

        # Set up the menu bar
        menu_bar = self.menuBar()
        edit_menu = menu_bar.addMenu("Edit")
        self.profile_menu = menu_bar.addMenu("Profiles")
        help_menu = menu_bar.addMenu("Help")

        # Edit menu
        add_tag_action = QAction("Add Tag", self)
        add_tag_action.triggered.connect(self.add_tag)
        add_tag_action.setShortcut("Ctrl+N")
        edit_menu.addAction(add_tag_action)

        add_images_action = QAction("Add Images", self)
        add_images_action.triggered.connect(self.add_directory)
        add_images_action.setShortcut("Ctrl+I")
        edit_menu.addAction(add_images_action)

        edit_menu.addSeparator()
        clear_selection_action = QAction("Clear Selection", self)
        clear_selection_action.triggered.connect(self.clear_selection)
        clear_selection_action.setShortcut("Ctrl+E")
        edit_menu.addAction(clear_selection_action)

        # Profile menu
        self.create_profile_menu()

        # Help menu
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about_dialog)
        about_action.setShortcut("Ctrl+H")
        help_menu.addAction(about_action)

        # Set up the status bar
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.selected_label = QLabel("Selected Items: 0")
        self.status_bar.addWidget(self.selected_label)

        # Create a QLineEdit for tags
        self.tag_line_edit = QLineEdit()
        self.tag_line_edit.returnPressed.connect(self.handle_tags)
        self.tag_line_edit.setAlignment(Qt.AlignRight)  # Align text to the right
        self.setup_autocomplete()

        # Add the tag_widget to the status bar and set its stretch factor to 1
        self.status_bar.addPermanentWidget(self.tag_line_edit, 1)

        # Set up the central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Set up the layout
        layout = QVBoxLayout(central_widget)

        layout2 = QHBoxLayout()

        # Set up the tag view
        self.tag_view = QTreeView()
        self.tag_model = CustomStandardItemModel()
        self.tag_model.setHorizontalHeaderLabels(["Tags"])
        self.tag_view.setModel(self.tag_model)
        self.tag_view.setDragDropMode(QTreeView.InternalMove)
        self.tag_view.setSelectionMode(QTreeView.ExtendedSelection)

        self.tag_model.itemsMoved.connect(self.on_tag_moved)

        self.tag_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tag_view.customContextMenuRequested.connect(self.show_tag_menu)

        # Populate the tag view with some example tags
        self.update_tags()

        # Set up the timeline
        self.timeline = QLabel("Timeline: Number of files per month")
        self.timeline.setAlignment(Qt.AlignCenter)

        # Set up the image view
        self.image_container = ImageGridWidget()

        self.single_item = QLabel()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.image_container, "Items")
        self.tabs.addTab(self.single_item, "Single")

        self.update_items()

        # Add the tag view and the main area to the layout
        layout2.addWidget(self.tag_view)
        layout2.addWidget(self.tabs)

        layout.addWidget(self.timeline)
        layout.addLayout(layout2)

        self.preloader = QTimer()
        self.preloader.timeout.connect(self.preload_items)
        self.preloader.start(1)

        # install event filter
        QApplication.instance().installEventFilter(self)

    def show_tag_menu(self, position: QPoint):
        index = self.tag_view.indexAt(position)
        if not index.isValid():
            return

        tag_id = self.tag_model.itemFromIndex(index).data()
        menu = QMenu()

        delete_action = menu.addAction("Delete Tag")
        delete_action.triggered.connect(lambda: self.delete_tag(tag_id))

        menu.exec(self.tag_view.viewport().mapToGlobal(position))

    def delete_tag(self, tag_id: int):
        db.delete_tag(tag_id)
        self.update_tags()

    def update_items(self):
        files = db.get_images(self.page)
        self.image_container.show_images(files)

    def create_profile_menu(self):
        self.profile_menu.clear()

        for p in self.config.get_profiles():
            tmp_action = QAction(p, self)
            tmp_action.triggered.connect(lambda: self.change_profile(p))
            self.profile_menu.addAction(tmp_action)

        self.profile_menu.addSeparator()
        new_profile_action = QAction("New Profile", self)
        new_profile_action.triggered.connect(self.new_profile)
        self.profile_menu.addAction(new_profile_action)

        self.profile_menu.addSeparator()
        new_config_action = QAction("New Config", self)
        new_config_action.triggered.connect(self.new_config)
        self.profile_menu.addAction(new_config_action)

        new_config_action = QAction("Change Config", self)
        new_config_action.triggered.connect(self.change_config)
        self.profile_menu.addAction(new_config_action)

    def change_profile(self, name):
        self.config.set_current_profile(name)
        self.update_tags()
        self.update_items()
        self.setWindowTitle(f"Tag Organizer -- Profile {self.config.profile}")

    def new_profile(self):
        dialog = ProfileDialog()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            profile_data = dialog.get_profile_data()
            self.config.create_new_profile(
                profile_data["profile_name"],
                Path(profile_data["db_location"]),
                profile_data["photos_dir"],
                profile_data["videos_dir"],
            )
        self.create_profile_menu()

    def change_config(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select new config file")
        if file_name:
            # TODO: add error checking
            self.config.set_config_file(Path(file_name))
            self.change_profile("default")
            self.create_profile_menu()

    def new_config(self):
        print(
            "Not yet implemented, but you can create an ini file manually (can be empty) and then change to it"
        )

    def show_about_dialog(self):
        text = "This is TagOrganizer\n\n"
        text += "profile name: default\n"
        text += f"Setting file location: {self.config.config_file}\n"
        text += f"DB location: {self.config.db}\n"
        text += f"Photo location: {self.config.photos}\n"
        text += f"Video location: {self.config.videos}\n"
        QMessageBox.about(self, "TagOrganizer", text)

    def handle_tags(self):
        tag_str = self.tag_line_edit.text()
        tags = tag_str.strip().split(",")
        tags = [t.strip().title() for t in tags]

        tag_list = []
        for t in tags:
            tag = db.get_tag(t)
            if tag is None:
                tag_id = db.add_tag(t)
                tag_item = QStandardItem(t)
                tag_item.setData(tag_id)
                self.tag_model.appendRow(tag_item)
                tag = db.get_tag(t)
            tag_list.append(tag)

        if self.selected:
            item_list = [w.item for w in self.selected]
        else:
            item_list = [self.image_container.current_item().item]

            db.set_tags(item_list, tag_list)

    def display_common_tags(self):
        if self.selected:
            common_tags = db.get_common_tags([w.item for w in self.selected])
        else:
            common_tags = db.get_common_tags([self.image_container.current_item().item])

        self.tag_line_edit.setText(",".join(common_tags))

    def preload_items(self):
        start = time.time()
        N = db.get_number_of_items()
        # thumbnails +- 2 pages
        for i in range(self.page - 2, self.page + 3):
            if i < 1:
                continue
            if i > N // 25:
                continue
            files = db.get_images(i)
            for f in files:
                load_pixmap(str(f.uri))
                if time.time() - start > 0.1:
                    return

        # full files +- 5 from current image
        for i in range(self.highlight_n - 5, self.highlight_n + 6):
            if i < 0:
                continue
            if i >= N:
                continue
            file = db.get_current_image(i)
            load_full_pixmap(str(file.uri))
            if time.time() - start > 0.1:
                return

    def eventFilter(self, source, event):
        if event.type() == QEvent.KeyPress and not self.tag_line_edit.hasFocus():
            if event.key() in [
                Qt.Key_Left,
                Qt.Key_Right,
                Qt.Key_Up,
                Qt.Key_Down,
                Qt.Key_Return,
                Qt.Key_Escape,
                Qt.Key_Enter,
                Qt.Key_Space,
            ]:
                self.keyPressEvent(event)
                return True  # Event has been handled
        return super().eventFilter(source, event)

    def keyPressEvent(self, event):
        if self.tag_line_edit.hasFocus():
            return

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
        elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            self.show_current_item()
            return
        elif event.key() == Qt.Key_Escape:
            self.tabs.setCurrentIndex(0)
            return
        elif event.key() == Qt.Key_Space:
            widget = self.image_container.toggle_selection()
            if widget in self.selected:
                self.selected.remove(widget)
            else:
                self.selected.append(widget)
            self.selected_label.setText(f"Selected items: {len(self.selected)}")
            self.display_common_tags()
            return
        if self.tabs.currentWidget() == self.single_item:
            self.show_current_item()
        new_page = self.highlight_n // 25
        if new_page != self.page:
            self.page = new_page
            files = db.get_images(self.page)
            self.image_container.show_images(files)
        self.image_container.set_highlight(self.highlight_n)
        self.display_common_tags()

    def clear_selection(self):
        self.image_container.clear_selection()
        self.selected = []
        self.selected_label.setText("Selected items: 0")

    def show_current_item(self):
        item = db.get_current_image(self.highlight_n)
        pixmap = load_full_pixmap(str(item.uri))
        pixmap = pixmap.scaled(
            self.single_item.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        self.single_item.setPixmap(pixmap)
        self.single_item.setAlignment(Qt.AlignCenter)
        self.tabs.setCurrentWidget(self.single_item)

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

    def update_tags(self):
        self.tag_model.removeRows(0, self.tag_model.rowCount())

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

    def setup_autocomplete(self):
        tags = db.get_all_tags()
        tags = [t.name for t in tags]

        completer = CommaCompleter(tags)

        self.tag_line_edit.setCompleter(completer)

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
        self.setup_autocomplete()


def main():
    app = QApplication([])
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
