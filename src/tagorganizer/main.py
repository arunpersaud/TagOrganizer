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
import logging
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
    QVBoxLayout,
    QWidget,
)
from qtpy.QtCore import Qt, QEvent

from docopt import docopt

from . import db
from . import config
from . import DBimport
from . import tasks
from .selection import Selection
from .widgets import (
    AddTagDialog,
    DeleteConfirmationDialog,
    ImageGridWidget,
    MapWidget,
    Messages,
    ProfileDialog,
    SingleItem,
    TagBar,
    TagView,
    Timeline,
    RESERVED_TAGS,
)
from .widgets.helper import CommaCompleter, get_thumbnail_path

logger = logging.getLogger(__name__)


def is_reserved_tag(name: str) -> bool:
    """Is this name one of the internal filter buttons?

    Compared case-insensitively because tag names are stored exactly as the
    user typed them. An exact-match check would let "no gps" through and
    create a real tag that collides with the filter button.
    """
    return name.strip().casefold() in {r.casefold() for r in RESERVED_TAGS}


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
                ["Show Selected Only", "Ctrl+Shift+S", self.show_selected_only],
                "---",
                ["Quit", "Ctrl+Q", self.close],
            ],
            "Tasks": [
                ["Update Timestamps in DB", self.tasks.db_update_timestamps],
                ["Update Locations in DB", self.tasks.db_update_locations],
                ["Update Hashes in DB", self.tasks.db_update_hashes],
                ["Check for Files in Default Dirs", self.tasks.list_files_not_in_db],
                [
                    "Check for Files outside of Default Dirs",
                    self.tasks.list_files_not_in_config_dir,
                ],
                ["Move Files with new date set", self.tasks.fix_no_date_files],
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
        self.numbers = [0, 0, 0]
        self.numbers_label = QLabel("View: 0 Selected: 0 Total: 0")
        self.status_bar.addWidget(self.numbers_label)

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

        # Owned here rather than by the grid: the grid shows one page of it, and
        # selecting on the map will feed the same object.
        self.selection = Selection()

        # Set up the image view
        self.grid = ImageGridWidget(self)

        self.single_item = SingleItem(self)

        self.map = MapWidget(self)

        self.messages = Messages(self)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.grid, "Items")
        self.tabs.addTab(self.single_item, "Single")
        self.tabs.addTab(self.map, "Map")
        self.tabs.addTab(self.messages, "Messages")

        self.tabs.currentChanged.connect(self.on_tab_changed)

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

    def update_numbers(self, view=None, selected=None, total=None):
        if view is not None:
            self.numbers[0] = view
        if selected is not None:
            self.numbers[1] = selected
        if total is not None:
            self.numbers[2] = total
        view, selected, total = self.numbers
        self.numbers_label.setText(f"View: {view} Selected: {selected} Total: {total}")

    def update_single_item(self) -> bool:
        """Load the current grid item into the single view.

        Returns False when the grid is empty, so callers can leave the tab alone
        rather than switching to a blank one.
        """
        widget = self.grid.current_item()
        if not widget:
            return False
        self.single_item.set_item(widget.item)
        return True

    def show_current_item(self):
        if self.update_single_item():
            self.tabs.setCurrentWidget(self.single_item)

    def on_tab_changed(self, index):
        """Tell a tab that it has become visible.

        Both the single view and the map need this. Nothing else populates the
        single view, and Leaflet sized itself against a container that had no
        size while its tab was hidden, so it has to be told to measure again.
        """
        widget = self.tabs.widget(index)
        if widget == self.messages:
            self.messages.reset_tab_color()
        elif widget == self.single_item:
            self.update_single_item()
        elif widget == self.map:
            self.map.on_shown()

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

        nr_items = db.get_number_of_items(filters)
        nr_total_items = db.get_number_of_items()
        self.update_numbers(view=nr_items, total=nr_total_items)

        items = db.get_images(self.grid.page, filters)
        self.grid.show_images(items)

        if filters != self.filters:
            dates, coords = db.get_times_and_location_from_images(filters)

            self.timeline.plot_histogram(dates)
            self.map.set_markers(coords)
            self.filters = filters

    def create_profile_menu(self):
        if "Profiles" not in self.menu:
            self.messages.add("[ERROR] no 'Profiles' menu")
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

    def reset_view_state(self):
        """Drop everything that belonged to the previous database.

        selection matters most: those are ids from the old database, and
        delete_items would happily act on whatever holds them now. Clearing the
        cached filters forces update_items to redraw the timeline and the map,
        which it otherwise skips whenever two profiles compare equal - which
        they do whenever they share their photo and video directories.
        """
        self.grid.page = 0
        self.grid.highlight = 0
        self.selection.clear()
        self.tag_bar.clear_selected_tags()
        self.filters = None
        self.update_numbers(selected=0)

    def change_profile(self, name):
        previous = self.config.profile
        self.tasks.stop()
        self.single_item.stop_playback()
        try:
            self.config.set_current_profile(name)
        except config.ProfileNotFoundError as error:
            self.config.profile = previous
            QMessageBox.warning(self, "Profile not found", str(error))
            return

        self.reset_view_state()
        self.tag_view.update_tags()
        self.setup_autocomplete()
        self.update_items()
        self.setWindowTitle(f"Tag Organizer -- Profile {self.config.profile}")

    def new_profile(self):
        dialog = ProfileDialog()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            profile_data = dialog.get_profile_data()
            profile_name = profile_data["profile_name"]
            self.config.create_new_profile(
                profile_name,
                Path(profile_data["db_location"]),
                profile_data["photos_dir"],
                profile_data["videos_dir"],
            )
            if profile_name not in self.config.get_profiles():
                QMessageBox.warning(
                    self,
                    "Profile creation failed",
                    f"Profile {profile_name!r} could not be created.",
                )
        self.create_profile_menu()

    def change_config(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select new config file")
        if not file_name:
            return

        previous_file = self.config.config_file
        previous_profile = self.config.profile
        try:
            self.config.set_config_file(Path(file_name))
        except config.ProfileNotFoundError as error:
            # Put the working configuration back: the user is still looking at
            # the old profile's photos and we have not loaded anything else.
            self.config.config_file = previous_file
            self.config.profile = previous_profile
            self.config.read_config()
            QMessageBox.warning(self, "Cannot use this config file", str(error))
            return

        self.reset_view_state()
        self.tag_view.update_tags()
        self.setup_autocomplete()
        self.update_items()
        self.create_profile_menu()
        self.setWindowTitle(f"Tag Organizer -- Profile {self.config.profile}")

    def new_config(self):
        self.messages.add(
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
        text += f"Thumbnail location: {get_thumbnail_path(self.config.photos)}\n"
        QMessageBox.about(self, "TagOrganizer", text)

    def handle_tags(self):
        """Set tags to selected images.

        Take all comma-separated tags from the tag_line widget and apply
        them to either the current item if no other items are selected
        or all selected items.
        """
        tag_str = self.tag_line_edit.text()
        tags = tag_str.strip().split(",")
        # Stored as typed. db.get_tag folds case when it looks them up, so the
        # spelling the user chose survives without forking "iPhone" from
        # "Iphone" into two separate tags.
        tags = [t.strip() for t in tags if t.strip()]

        tag_list = []
        for t in tags:
            if is_reserved_tag(t):
                self.messages.add(
                    f"Tag with name '{t}' is not allowed due to internal use!"
                )
                continue

            tag = db.get_tag(t)
            if tag is None:
                tag_id = db.add_tag(t)
                self.tag_view.add_tag(t, id=tag_id)
                tag = db.get_tag(t)
            tag_list.append(tag)

        if len(self.selection):
            item_list = db.get_items_by_ids(self.selection.ids())
        else:
            current = self.grid.current_item()
            if current is None:
                return
            item_list = [current.item]

        db.set_tags(item_list, tag_list)

        self.tag_line_edit.clear()
        # A tag created just now has to be completable straight away, and the
        # counts and any active tag filter are stale until the view is redrawn.
        self.setup_autocomplete()
        self.update_items()

    def display_common_tags(self):
        if len(self.selection):
            common_tags = db.get_common_tags(db.get_items_by_ids(self.selection.ids()))
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
            self.messages.add(f"[ERROR] target {target} not a directory.")
            return

        for item in db.get_items_by_ids(self.selection.ids()):
            source = Path(item.uri)
            if not source.is_file():
                self.messages.add(f"[ERROR] item at {source} does not exist...skipping")
                continue
            destination = target / source.name
            if destination.exists():
                self.messages.add(f"[ERROR] {destination} already exists...skipping")
                continue
            shutil.copy(source, destination)

    def clear_selection(self):
        self.grid.clear_selection()
        self.selection.clear()
        self.update_numbers(selected=0)

    def show_selected_only(self):
        """Restrict the view to the current selection.

        The ids are snapshotted into the filter rather than read live, so
        deselecting a photo while inside the view removes its blue frame but
        leaves it on screen - otherwise a mis-deselect would remove the only
        place the photo could be re-selected from.
        """
        if not len(self.selection):
            self.messages.add("Nothing is selected.")
            return
        self.tag_bar.add_selection_tag(self.selection.ids())

    def setup_autocomplete(self):
        tags = db.get_all_tags()
        tags = [t.name for t in tags]

        completer = CommaCompleter(tags)

        self.tag_line_edit.setCompleter(completer)

    def delete_items(self):
        if len(self.selection):
            items_to_delete = db.get_items_by_ids(self.selection.ids())
        else:
            current = self.grid.current_item()
            if current is None:
                return
            items_to_delete = [current.item]

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

            self.selection.clear()
            self.update_items()  # Assuming update_items refreshes the displayed items

    def add_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")

        if directory:
            self.messages.add(f"selected: {directory}")
            mydir = Path(directory)
            # One walk, matching on the lowercased suffix: globbing "*.jpg" and
            # "*.JPG" misses ".Jpg", which phones and cameras both produce.
            suffixes = {ext.lower() for ext in config.ALL_SUFFIX}
            files = [
                path
                for path in mydir.rglob("*")
                if path.is_file() and path.suffix.lower() in suffixes
            ]
            db.add_images(files)
            self.update_items()
            self.messages.add(f"finished adding {directory}")

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
                elif is_reserved_tag(tag_name):
                    QMessageBox.warning(
                        self, "Tag name not allowed", "The tag name is used internally."
                    )
                else:
                    tag_id = db.add_tag(tag_name)
                    self.tag_view.add_tag(tag_name, id=tag_id)
        self.setup_autocomplete()


def configure_logging(verbose: bool = False) -> None:
    """Send library log records to the console.

    The modules under tagorganizer log through logging.getLogger(__name__) and
    deliberately install no handlers of their own - that is the application's
    job, and doing it here means importing the package never has side effects.
    Without this call the CLI paths, including the f-spot import, would be
    silent.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )


def main():
    commands = docopt("""
    Usage:
        TagOragnizer [options]

    --config=<file>                 Use this config file
    --profile=<profile>             Use this profile
    --import-from-f-spot=<f-spot>   Try to load data from this f-spot database
    --verbose                       Log debug messages as well

    """)

    configure_logging(verbose=commands["--verbose"])

    app = QApplication(sys.argv)
    try:
        window = MainWindow(app)
    except config.ProfileNotFoundError as error:
        logger.error("%s", error)
        sys.exit(3)

    if commands["--config"]:
        configfile = Path(commands["--config"]).expanduser()
        if not configfile.is_file():
            logger.error("config file %s cannot be opened... exiting", configfile)
            sys.exit(1)
        try:
            window.config.set_config_file(configfile)
        except config.ProfileNotFoundError as error:
            logger.error("%s", error)
            sys.exit(3)
        window.create_profile_menu()
        logger.info("Starting with config file: %s", configfile)

    if commands["--profile"]:
        profile = commands["--profile"]
        window.change_profile(profile)
        logger.info("Starting with profile: %s", profile)

    if commands["--import-from-f-spot"]:
        old_db = Path(commands["--import-from-f-spot"]).expanduser()
        DBimport.import_f_spot(old_db)

    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
