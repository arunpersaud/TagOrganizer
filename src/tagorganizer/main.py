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

import importlib.metadata
from pathlib import Path
import shutil
import sys

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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qtpy.QtCore import Qt, QEvent

from docopt import docopt

from . import db
from . import config
from . import DBimport
from . import tasks
from .widgets import (
    AddTagDialog,
    DeleteConfirmationDialog,
    ImageGridWidget,
    ProfileDialog,
    SingleItem,
    Timeline,
    MapWidget,
    TagBar,
    TagView,
    RESERVED_TAGS,
)
from .widgets.helper import load_full_pixmap, CommaCompleter


class MainWindow(QMainWindow):
    def __init__(self, app):
        super().__init__()

        self.app = app
        self.filters = None

        self.config = config.ConfigManager()
        self.setWindowTitle(f"Tag Organizer -- Profile {self.config.profile}")

        self.tasks = tasks.TaskManager(self)

        # Set up the menu bar
        self.menu_bar = self.menuBar()

        # the menu of the program as a dict. We automatically creates
        # menus out of this and store the python objects in self.menu
        # the submenu can be either "---" for a separator, two items
        # for name and function, or 3 items for name, shortcut, and
        # function
        menu = {
            "Edit": [
                ["Add New Tag", "Ctrl+N", self.add_tag],
                ["Add Images", "Ctrl+I", self.add_directory],
                "---",
                ["Delete", "Ctrl+D", self.delete_items],
                "---",
                ["Copy Selection to dir", self.copy_selection],
                ["Clear Selection", "Ctrl+E", self.clear_selection],
                "---",
                ["Quit", "Ctrl+Q", self.close],
            ],
            "Tasks": [
                ["Update Timestamps in DB", self.tasks.db_update_timestamps],
                ["Update Locations in DB", self.tasks.db_update_locations],
                ["Move Files to Default Dirs", self.tasks.move_files],
            ],
            "Profiles": [],
            "Help": [["About", "Ctrl+H", self.show_about_dialog]],
        }
        # We use this variable to store links to the menu
        self.menu = {}
        self.create_menu(menu)

        # dynamically create Profile menu depedning on config file
        self.create_profile_menu()

        # Set up the status bar
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.selected_items_label = QLabel("Selected Items: 0")
        self.status_bar.addWidget(self.selected_items_label)

        # Create a QLineEdit for tags
        self.tag_line_edit = QLineEdit()
        self.tag_line_edit.returnPressed.connect(self.handle_tags)
        self.tag_line_edit.setAlignment(Qt.AlignRight)  # Align text to the right
        self.setup_autocomplete()

        # Add the tag_widget to the status bar and set its stretch factor to 1
        self.tasks.register_widgets(self.status_bar)
        self.status_bar.addPermanentWidget(self.tag_line_edit, 1)

        # Set up the central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Set up the layout
        layout = QVBoxLayout(central_widget)

        layout2 = QHBoxLayout()

        # Set up the tag view
        self.tag_view = TagView(self)

        # Populate the tag view with some example tags
        self.tag_view.update_tags()

        # Selected Tags
        self.tag_bar = TagBar(self)
        layout.addLayout(self.tag_bar)

        # Set up the timeline
        self.timeline = Timeline(self)

        # Set up the image view
        self.grid = ImageGridWidget(self)

        self.single_item = SingleItem()

        self.map = MapWidget(self)

        self.messages = QTextEdit()
        self.messages.setReadOnly(True)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.grid, "Items")
        self.tabs.addTab(self.single_item, "Single")
        self.tabs.addTab(self.map, "Map")
        self.tabs.addTab(self.messages, "Messages")

        self.update_items()

        # Add the tag view and the main area to the layout
        layout2.addWidget(self.tag_view)
        layout2.addWidget(self.tabs)

        layout.addWidget(self.timeline)
        layout.addLayout(layout2)

        self.key_actions = {
            "grid": {
                Qt.Key_Left: self.grid.move_left,
                Qt.Key_Right: self.grid.move_right,
                Qt.Key_Up: self.grid.move_up,
                Qt.Key_Down: self.grid.move_down,
                Qt.Key_Return: self.show_current_item,
                Qt.Key_Enter: self.show_current_item,
                Qt.Key_Space: self.grid.toggle_selection,
                (Qt.Key_Up, Qt.ShiftModifier): self.grid.shift_move_up,
                (Qt.Key_Down, Qt.ShiftModifier): self.grid.shift_move_down,
            },
            "single": {
                Qt.Key_Left: self.grid.move_left,
                Qt.Key_Right: self.grid.move_right,
                Qt.Key_Up: self.grid.move_up,
                Qt.Key_Down: self.grid.move_down,
                (Qt.Key_Up, Qt.ShiftModifier): self.grid.shift_move_up,
                (Qt.Key_Down, Qt.ShiftModifier): self.grid.shift_move_down,
                Qt.Key_I: self.single_item.toggle_exif_visibility,
                Qt.Key_F: self.single_item.toggle_filename_visibility,
                Qt.Key_Escape: self.focus_grid,
            },
        }

        self.keys_in_use = []
        for w in self.key_actions:
            keys = self.key_actions[w]
            for k in keys:
                if isinstance(k, tuple):
                    self.keys_in_use.append(k[0])
                else:
                    self.keys_in_use.append(k)

        # install event filter
        QApplication.instance().installEventFilter(self)

        # we want the cursor keys to move our red window at startup
        # and not be in the tag_line
        self.grid.setFocus()

    def create_menu(self, menu: dict):
        for key, submenu in menu.items():
            tmp = self.menu_bar.addMenu(key)
            self.menu[key] = tmp

            for item in submenu:
                match item:
                    case "---":
                        self.menu[key].addSeparator()
                    case [name, shortcut, func]:
                        self.create_action(name, func, self.menu[key], shortcut)
                    case [name, func]:
                        self.create_action(name, func, self.menu[key], shortcut=None)

    def create_action(self, name: str, func, menu, shortcut: str | None = None):
        tmp = QAction(text=name, parent=self)
        tmp.triggered.connect(func)
        if shortcut:
            tmp.setShortcut(shortcut)
        menu.addAction(tmp)

    def update_items(self):
        filters = self.tag_bar.get_filters()

        items = db.get_images(self.grid.page, filters)
        self.grid.show_images(items)

        if filters != self.filters:
            dates, coords = db.get_times_and_location_from_images(filters)

            self.timeline.plot_histogram(dates)
            self.map.set_markers(coords)
            self.filter = filters

    def create_profile_menu(self):
        if "Profiles" not in self.menu:
            print("[ERROR] no 'Profiles' menu")
            return

        self.menu["Profiles"].clear()

        for p in self.config.get_profiles():
            tmp_action = QAction(p, self)
            # the trigger function needs to accept a boolean value. We
            # absorb this in 'checked' and use profile=p, so that the
            # correct p gets remembers inside the namespace of the
            # function without profile=p, e.g. lambda:
            # self.change_profile(p) we would always go to the last
            # 'p' in the for loop
            tmp_action.triggered.connect(
                lambda checked, profile=p: self.change_profile(profile)
            )
            self.menu["Profiles"].addAction(tmp_action)

        self.menu["Profiles"].addSeparator()
        self.create_action("New Profile", self.new_profile, self.menu["Profiles"])
        self.menu["Profiles"].addSeparator()
        self.create_action("New Config", self.new_config, self.menu["Profiles"])
        self.create_action("Change Config", self.change_config, self.menu["Profiles"])

    def change_profile(self, name):
        self.tasks.stop()
        self.config.set_current_profile(name)
        self.tag_view.update_tags()
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
        version = importlib.metadata.version("tagorganizer")

        text = "This is TagOrganizer\n\n"
        text += f"Version: {version}\n\n"
        text += f"Profile name: {self.config.profile}\n"
        text += f"Setting file location: {self.config.config_file}\n"
        text += f"DB location: {self.config.db}\n"
        text += f"Photo location: {self.config.photos}\n"
        text += f"Video location: {self.config.videos}\n"
        QMessageBox.about(self, "TagOrganizer", text)

    def handle_tags(self):
        """Set tags to selected images.

        Take all comma-separated tags from the tag_line widget and apply
        them to either the current item if no other items are selected
        or all selected items.
        """
        tag_str = self.tag_line_edit.text()
        tags = tag_str.strip().split(",")
        tags = [t.strip().title() for t in tags]

        tag_list = []
        for t in tags:
            tag = db.get_tag(t)
            if tag in RESERVED_TAGS:
                print(f"Tag with name '{tag}' is not allowed due to internal use!")
                continue

            if tag is None:
                tag_id = db.add_tag(t)
                self.tag_view.add_tag(t, id=tag_id)
                tag = db.get_tag(t)
            tag_list.append(tag)

        if self.grid.selected_items:
            item_list = self.grid.selected_items
        else:
            current = self.grid.current_item()
            if current is None:
                return
            item_list = [current.item]

            db.set_tags(item_list, tag_list)

    def display_common_tags(self):
        if self.grid.selected_items:
            common_tags = db.get_common_tags(self.grid.selected_items)
        else:
            current = self.grid.current_item()
            if current is None:
                return
            common_tags = db.get_common_tags([current.item])

        self.tag_line_edit.setText(",".join(common_tags))

    def eventFilter(self, source, event):
        if self.tag_line_edit.hasFocus():
            return super().eventFilter(source, event)

        if event.type() == QEvent.KeyPress:
            if event.key() in self.keys_in_use:
                self.keyPressEvent(event)
                return True  # Event has been handled
        return super().eventFilter(source, event)

    def keyPressEvent(self, event):
        if self.tag_line_edit.hasFocus():
            return

        context = "single" if self.tabs.currentWidget() == self.single_item else "grid"

        key = event.key()
        modifiers = event.modifiers()

        relevant_modifiers = (
            Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier
        )
        filtered_modifiers = modifiers & relevant_modifiers

        if (key, filtered_modifiers) in self.key_actions[context]:
            self.key_actions[context][(key, filtered_modifiers)]()
        elif key in self.key_actions[context]:
            self.key_actions[context][key]()

        context = "single" if self.tabs.currentWidget() == self.single_item else "grid"

        if context == "grid":
            new_page = self.grid.highlight // self.grid.N
            if new_page != self.grid.page:
                self.grid.page = new_page
                self.update_items()
            self.display_common_tags()

    def focus_grid(self):
        self.tabs.setCurrentIndex(0)

    def copy_selection(self):
        directory = QFileDialog.getExistingDirectory(None, "Select Directory")

        if not directory:
            return
        target = Path(directory)
        if not target.is_dir():
            print(f"[ERROR] target {target} not a directory.")
            return

        for item in self.grid.selected_items:
            source = Path(item.uri)
            if not source.is_file():
                print(f"[ERROR] item at {source} does not exist...skipping")
                continue
            destination = target / source.name
            shutil.copy(source, destination)

    def clear_selection(self):
        self.grid.clear_selection()
        self.grid.selected_items = []
        self.selected_items_label.setText("Selected items: 0")

    def show_current_item(self):
        widget = self.grid.current_item()
        if not widget:
            return
        item = widget.item
        pixmap = load_full_pixmap(str(item.uri))
        pixmap = pixmap.scaled(
            self.single_item.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        self.single_item.setPixmap(pixmap)
        self.single_item.load_exif(str(item.uri))
        self.single_item.filename.setText(item.uri)
        self.tabs.setCurrentWidget(self.single_item)

    def setup_autocomplete(self):
        tags = db.get_all_tags()
        tags = [t.name for t in tags]

        completer = CommaCompleter(tags)

        self.tag_line_edit.setCompleter(completer)

    def delete_items(self):
        items_to_delete = (
            self.grid.selected_items
            if self.grid.selected_items
            else [self.grid.current_item().item]
        )

        if not items_to_delete:
            return

        dialog = DeleteConfirmationDialog(items_to_delete, self)
        if dialog.exec_() == QDialog.Accepted:
            delete_files = dialog.should_delete_files()
            for item in items_to_delete:
                if delete_files:
                    filepath = Path(item.uri)
                    if filepath.exists():
                        filepath.unlink()
                db.delete_item(item.id)

            self.grid.selected_items = []
            self.update_items()  # Assuming update_items refreshes the displayed items

    def add_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")

        if directory:
            print("selected: ", directory)
            mydir = Path(directory)
            files = []
            for ext in ["jpg", "jpeg"]:
                new = list(mydir.rglob(f"*.{ext}"))
                files = files + new
                new = list(mydir.rglob(f"*.{ext.upper()}"))
                files = files + new
            db.add_images(files)
            self.update_items()

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
                elif tag_name in RESERVED_TAGS:
                    QMessageBox.warning(
                        self, "Tag name not allowed", "The tag name is used internally."
                    )
                else:
                    tag_id = db.add_tag(tag_name)
                    self.tag_view.add_tag(tag_name, id=tag_id)
        self.setup_autocomplete()


def main():
    commands = docopt("""
    Usage:
        TagOragnizer [options]

    --config=<file>                 Use this config file
    --profile=<profile>             Use this profile
    --import-from-f-spot=<f-spot>   Try to load data from this f-spot database

    """)

    app = QApplication(sys.argv)
    window = MainWindow(app)

    if commands["--config"]:
        configfile = Path(commands["--config"]).expanduser()
        if not configfile.is_file():
            print(f"[Error]  config file {configfile} cannot be opened... existing")
            sys.exit(1)
        window.config.set_config_file(configfile)
        window.create_profile_menu()
        print("Starting with config file:", configfile)

    if commands["--profile"]:
        profile = commands["--profile"]
        window.change_profile(profile)
        print("Starting with profile: ", profile)

    if commands["--import-from-f-spot"]:
        old_db = Path(commands["--import-from-f-spot"]).expanduser()
        DBimport.import_f_spot(old_db)

    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
