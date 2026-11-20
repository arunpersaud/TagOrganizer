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
import traceback

from qtpy.QtWidgets import (
    QAction,
    QAbstractSpinBox,
    QComboBox,
    QInputDialog,
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qtpy.QtCore import Qt, QEvent, qInstallMessageHandler, QtMsgType

from docopt import docopt

from . import db
from .scope import Scope
from . import config
from . import DBimport
from . import dbmove
from . import tasks
from .selection import Selection
from .widgets import (
    AddTagDialog,
    DeleteConfirmationDialog,
    ImageGridWidget,
    MapWidget,
    Messages,
    MoveToProfileDialog,
    ProfileDialog,
    SingleItem,
    TagEditorDialog,
    TagBar,
    TagView,
    Timeline,
    RESERVED_TAGS,
)
from .widgets.set_date_dialog import SetDateDialog
from .widgets.helper import (
    CommaCompleter,
    get_thumbnail_loader,
    get_thumbnail_path,
    stop_background_decodes,
)

logger = logging.getLogger(__name__)


def is_reserved_tag(name: str) -> bool:
    """Is this name one of the internal filter buttons?

    Compared case-insensitively because tag names are stored exactly as the
    user typed them. An exact-match check would let "no gps" through and
    create a real tag that collides with the filter button.
    """
    return name.strip().casefold() in {r.casefold() for r in RESERVED_TAGS}


def lineage_targets(
    current_id: int | None, selected_ids: list[int]
) -> tuple[list[int], str | None]:
    """Which photos the current one should be recorded as derived from.

    Returns the sources and an error, exactly one of which is meaningful. The
    current photo is dropped from its own source list rather than refused: a
    user who selected the whole burst and then picked the panorama out of it
    means the other four, not an error. But if dropping leaves nothing there
    is no link to make, so that says so instead of silently clearing lineage
    the user never asked to clear.
    """
    if current_id is None:
        return [], "No current photo to mark."
    parents = [item_id for item_id in selected_ids if item_id != current_id]
    if not parents:
        if selected_ids:
            return [], "The current photo cannot be its own source."
        return [], "Select the source photos first."
    return parents, None


def clamp_grid_position(highlight: int, count: int, per_page: int) -> tuple[int, int]:
    """Where the red frame and the page belong once the result has ``count`` items.

    A filter change or a deletion can shrink the result under a frame that was
    on page ten. Without this the grid shows an empty page and the frame is off
    screen. Returns (highlight, page).
    """
    if count <= 0:
        return 0, 0
    highlight = min(max(highlight, 0), count - 1)
    return highlight, highlight // per_page


def delete_photos(items, delete_files: bool) -> tuple[list[int], list[str]]:
    """Remove photos from the library, and optionally from disk too.

    Each photo is handled on its own, so one file that cannot be removed does
    not stop the rest. A photo whose file could not be deleted keeps its row:
    dropping the row while the file is still there would let the next import
    add the same photo back as new. Returns the ids removed and one line per
    failure.
    """
    removed = []
    failures = []
    for item in items:
        if delete_files:
            path = Path(item.uri)
            try:
                if path.exists():
                    path.unlink()
            except OSError as error:
                failures.append(
                    f"could not delete {item.uri}: {error.strerror or error}"
                )
                continue
        db.delete_item(item.id)
        removed.append(item.id)
    return removed, failures


def copy_photos(items, target: Path) -> tuple[int, list[str]]:
    """Copy photos into ``target``, returning the count copied and what was skipped.

    A photo that is missing, or whose name is already taken there, is skipped
    rather than overwritten. A copy that fails is reported and the rest still go.
    """
    copied = 0
    problems = []
    for item in items:
        source = Path(item.uri)
        if not source.is_file():
            problems.append(f"{source} does not exist; skipped")
            continue
        destination = target / source.name
        if destination.exists():
            problems.append(f"{destination} already exists; skipped")
            continue
        try:
            shutil.copy(source, destination)
        except OSError as error:
            problems.append(f"could not copy {source}: {error.strerror or error}")
            continue
        copied += 1
    return copied, problems


# Widgets that take typed text or arrow keys for themselves. The app-wide key
# filter must leave their key presses alone.
_KEY_TAKING_WIDGETS = (
    QLineEdit,
    QTextEdit,
    QPlainTextEdit,
    QAbstractSpinBox,
    QComboBox,
)


class MainWindow(QMainWindow):
    def __init__(self, app, config_file=None, profile=None):
        super().__init__()

        self.filters = None

        # Passed straight through: the config has to be chosen before any
        # database is opened, not swapped afterwards.
        self.config = config.ConfigManager(config_file=config_file, profile=profile)
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
                ["Edit Tags...", self.edit_tags],
                ["Settings...", self.open_settings],
                ["Add Images", "Ctrl+I", self.add_directory],
                "---",
                ["Delete", "Ctrl+D", self.delete_items],
                ["Set Date...", self.set_date],
                ["Set Location...", self.set_location],
                "---",
                ["Copy Selection to dir", self.copy_selection],
                ["Clear Selection", "Ctrl+E", self.clear_selection],
                ["Show Selected Only", "Ctrl+Shift+S", self.show_selected_only],
                ["Move Selection to Profile...", self.move_selection_to_profile],
                "---",
                ["Mark as Derived from Selection", self.mark_as_derived],
                ["Clear Sources of Current Photo", self.clear_lineage],
                "---",
                ["Quit", "Ctrl+Q", self.close],
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

        # Loaded once the window is fully assembled. A plugin that fails to
        # import is reported through the message widget, which needs the tab
        # bar to exist - and a startup crash is exactly what the plugin error
        # isolation exists to prevent.
        self.tasks.load_plugins()
        self.tasks.registry.set_disabled(self.config.get_disabled_plugins())
        self.build_plugin_menu()

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
                # Removes selected FILTER CHIPS, not photos. TagBar.remove_selected
                # is a no-op when no chip is selected, so a stray Delete cannot
                # touch the library; deleting photos is still Ctrl+D.
                Qt.Key_Delete: self.tag_bar.remove_selected,
                # On macOS the key labelled "delete" sends Backspace; Key_Delete
                # is the forward-delete, reachable only with fn held. Binding
                # both makes the key the user actually presses work.
                Qt.Key_Backspace: self.tag_bar.remove_selected,
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

    def report_unhandled(self, summary: str, details: str) -> None:
        """Show an exception that escaped a handler, without ending the session.

        The Messages tab keeps the one-line summary; the dialog carries the
        full traceback behind its details button, so a bug report can be
        copied from it.
        """
        self.messages.add(f"[ERROR] Unexpected error: {summary}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Unexpected error")
        box.setText(
            f"{summary}\n\nTagOrganizer is still running. The details are in "
            "the Messages tab and the log."
        )
        box.setDetailedText(details)
        box.exec()

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

    def open_settings(self):
        """Show where things live, and which plugins are switched on."""
        from .plugins.discovery import plugin_paths
        from .widgets.settings import SettingsDialog

        registry = self.tasks.registry
        dialog = SettingsDialog(
            self.config,
            registry.every(),
            self.tasks.broken,
            self.config.get_disabled_plugins(),
            plugin_paths(),
            self,
        )
        if not dialog.exec():
            return

        disabled = dialog.disabled_plugins()
        self.config.set_disabled_plugins(disabled)
        registry.set_disabled(disabled)
        # Rebuilt rather than deferred to the next start: a setting that does
        # nothing until you restart reads as a setting that does not work.
        self.build_plugin_menu()
        self.messages.add(f"{len(disabled)} plugin(s) disabled")

    def build_plugin_menu(self):
        """Create the task menus from the plugin registry.

        The scope is resolved inside the click handler rather than here: the
        menu is built once, and the selection changes constantly.

        Any menus from a previous build are removed first, so switching a
        plugin off in Settings and rebuilding does not leave a second
        Maintenance menu beside the first.
        """
        for menu in getattr(self, "_plugin_menus", []):
            # Removing the action unhooks it from the bar but leaves the menu
            # parented to it, so a rebuild would add a second Maintenance menu
            # beside the first. The widget has to go too.
            self.menu_bar.removeAction(menu.menuAction())
            self.menu.pop(menu.title(), None)
            menu.setParent(None)
            menu.deleteLater()
        self._plugin_menus = []

        for category, plugins in self.tasks.registry.by_category().items():
            menu = self.menu_bar.addMenu(category)
            self.menu[category] = menu
            for plugin in plugins:
                action = QAction(text=plugin.name, parent=self)
                if plugin.description:
                    action.setToolTip(plugin.description)
                # p=plugin binds this iteration's plugin. Without it every
                # entry would close over the loop variable and run the last
                # plugin in the category. The selection is read at click time,
                # not here, because it changes constantly.
                action.triggered.connect(
                    lambda checked=False, p=plugin: self.tasks.run_from_menu(
                        p, self.selection.ids()
                    )
                )
                menu.addAction(action)
            self._plugin_menus.append(menu)

    def closeEvent(self, event):
        """Stop the task worker before the window goes away.

        A QThread still running when its owner is destroyed aborts the
        process, which would turn a clean quit into a crash report. If a task
        cannot be stopped in time the close is refused rather than forced; the
        cancel has been requested, so a second close normally succeeds.
        """
        if not self.tasks.shutdown():
            self.messages.add("A task is still stopping; close again in a moment.")
            event.ignore()
            return
        super().closeEvent(event)

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
        """Redraw the grid, and the timeline and map when the filters changed.

        Also the one place the status line is brought up to date: the map adds
        to the selection and then calls this, so the selected count follows.
        """
        filters = self.tag_bar.get_filters()

        nr_items = db.get_number_of_items(filters)
        nr_total_items = db.get_number_of_items()
        self.grid.highlight, self.grid.page = clamp_grid_position(
            self.grid.highlight, nr_items, self.grid.N
        )
        self.update_numbers(
            view=nr_items, selected=len(self.selection), total=nr_total_items
        )

        items = db.get_images(self.grid.page, filters)
        self.grid.show_images(items)

        if filters != self.filters:
            dates, _ = db.get_times_and_location_from_images(filters)

            self.timeline.plot_histogram(dates)
            self.map.set_locations(db.get_locations_for_filter(filters))
            self.filters = filters

    def refresh_after_data_change(self):
        """Redraw everything that shows the library, after its contents changed.

        update_items redraws the timeline and map only when the filters differ
        from last time. That is right for paging, but after tagging, deleting,
        importing or a plugin run the same filter matches different photos, so
        every view has to be drawn again. Dropping the cached filters forces it.
        """
        self.filters = None
        self.tag_view.update_tags()
        self.setup_autocomplete()
        self.update_items()

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

        The tag bar is reset without its own redraw; the caller redraws once.
        """
        self.grid.page = 0
        self.grid.highlight = 0
        # Armed with ids from the old database, which name other photos here.
        self.map.view.disarm_location()
        self.selection.clear()
        self.tag_bar.reset()
        self.filters = None
        self.update_numbers(selected=0)
        # Item ids repeat across profiles, so decodes requested for the old
        # database must not answer requests made for the new one.
        get_thumbnail_loader().new_generation()

    def change_profile(self, name):
        previous = self.config.profile
        if not self.tasks.stop():
            QMessageBox.warning(
                self,
                "Task still running",
                "A task is still stopping, so the profile was not changed. "
                "Try again in a moment.",
            )
            return
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

        # Switching config switches the database too, so the worker must be
        # idle first, exactly as for a profile switch.
        if not self.tasks.stop():
            QMessageBox.warning(
                self,
                "Task still running",
                "A task is still stopping, so the config was not changed. "
                "Try again in a moment.",
            )
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
        # A tag created just now has to be completable straight away, and under
        # an active tag filter the photos on show may have just changed.
        self.refresh_after_data_change()

    def edit_tags(self):
        """Open the tag editor: rename a tag, or merge two into one."""
        dialog = TagEditorDialog(db.get_all_tags(), self)
        dialog.rename_button.clicked.connect(lambda: self._rename_tag(dialog))
        dialog.merge_button.clicked.connect(lambda: self._merge_tags(dialog))
        dialog.exec()

        # The vocabulary may have changed underneath everything.
        self.refresh_after_data_change()

    def _rename_tag(self, dialog):
        chosen = dialog.selected_tag_ids()
        if len(chosen) != 1:
            return

        tag = db.get_tag_by_id(chosen[0])
        new_name, accepted = QInputDialog.getText(
            dialog, "Rename Tag", "New name:", text=tag.name
        )
        if not accepted:
            return

        try:
            db.rename_tag(tag.id, new_name)
        except ValueError as error:
            QMessageBox.warning(dialog, "Cannot rename", str(error))
            return

        self._reload_tag_editor(dialog)

    def _merge_tags(self, dialog):
        """Fold one tag into another, naming the casualty before doing it.

        Merging is directional and cannot be undone, so the confirmation says
        which tag disappears rather than only asking whether to merge.
        """
        chosen = dialog.selected_tag_ids()
        if len(chosen) != 2:
            return

        source, target = db.get_tag_by_id(chosen[0]), db.get_tag_by_id(chosen[1])
        answer = QMessageBox.question(
            dialog,
            "Merge Tags",
            f"Merge {source.name!r} into {target.name!r}?\n\n"
            f"{source.name!r} will be deleted. Its photos and any child tags "
            f"move to {target.name!r}. This cannot be undone.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            moved, dropped = db.merge_tags(source.id, target.id)
        except ValueError as error:
            QMessageBox.warning(dialog, "Cannot merge", str(error))
            return

        self.messages.add(
            f"Merged {source.name!r} into {target.name!r}: "
            f"{moved} photo(s) moved, {dropped} already had it"
        )
        self._reload_tag_editor(dialog)

    @staticmethod
    def _reload_tag_editor(dialog):
        """Rebuild the dialog's list after the vocabulary changed."""
        from .widgets.tag_editor import tag_paths

        dialog.tag_list.clear()
        dialog._ids = []
        for tag_id, path in tag_paths(db.get_all_tags()):
            dialog.tag_list.addItem(path)
            dialog._ids.append(tag_id)
        dialog._selection_changed()

    def remove_tag_from_selection(self, tag_id):
        """Take one tag off the selected photos, or the current one.

        Targets are chosen the same way tagging chooses them, so applying and
        removing a tag are symmetric. The tag itself survives: this is for
        fixing a mistagged photo, which until now meant deleting the tag from
        the whole library.
        """
        tag = db.get_tag_by_id(tag_id)
        if tag is None:
            return

        if len(self.selection):
            items = db.get_items_by_ids(self.selection.ids())
        else:
            current = self.grid.current_item()
            if current is None:
                return
            items = [current.item]

        removed = db.remove_tags(items, [tag])
        if removed:
            self.messages.add(f"Removed {tag.name!r} from {removed} photo(s)")
        else:
            # Otherwise "it did nothing" and "none of them had that tag" look
            # exactly alike.
            self.messages.add(f"None of the selected photos had {tag.name!r}")

        self.display_common_tags()
        self.refresh_after_data_change()

    def display_common_tags(self):
        if len(self.selection):
            common_tags = db.get_common_tags(db.get_items_by_ids(self.selection.ids()))
        else:
            current = self.grid.current_item()
            if current is None:
                return
            common_tags = db.get_common_tags([current.item])

        self.tag_line_edit.setText(",".join(common_tags))

    def _owns_key_event(self, source) -> bool:
        """Whether a key press belongs to this window's own shortcuts.

        The filter is installed on the whole application, so it also sees keys
        typed into dialogs and other windows. Taking those would let arrow keys
        move the hidden grid behind a dialog, Backspace delete a filter chip, or
        Return switch tabs. A key is ours only when it comes from inside this
        window, no modal dialog is open, and the focused widget does not take
        typing or arrow keys itself.
        """
        if not isinstance(source, QWidget):
            return False
        if source is not self and not self.isAncestorOf(source):
            return False
        if QApplication.activeModalWidget() is not None:
            return False
        return not isinstance(QApplication.focusWidget(), _KEY_TAKING_WIDGETS)

    def eventFilter(self, source, event):
        if event.type() == QEvent.KeyPress and self._owns_key_event(source):
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

        copied, problems = copy_photos(
            db.get_items_by_ids(self.selection.ids()), target
        )
        for problem in problems:
            self.messages.add(f"[ERROR] {problem}")
        self.messages.add(f"Copied {copied} photo(s) to {target}")

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

    def _items_to_edit(self):
        """The selection, or the current photo when nothing is selected."""
        if len(self.selection):
            return db.get_items_by_ids(self.selection.ids())
        current = self.grid.current_item()
        return [] if current is None else [current.item]

    def set_date(self):
        """Give the selected photos a date by hand, for those with none to read."""
        items = self._items_to_edit()
        if not items:
            return
        initial = next((item.date for item in items if item.date), None)
        dialog = SetDateDialog(initial, len(items), self)
        if dialog.exec_() != QDialog.Accepted:
            return
        when = dialog.chosen()
        db.set_date([item.id for item in items], when)
        self.messages.add(f"Set the date of {len(items)} photo(s) to {when}")
        self.refresh_after_data_change()

    def set_location(self):
        """Place the selected photos with the next double-click on the map."""
        items = self._items_to_edit()
        if not items:
            return
        ids = [item.id for item in items]
        which = Path(items[0].uri).name + (
            f" and {len(ids) - 1} more" if len(ids) > 1 else ""
        )

        def place(latitude, longitude):
            answer = QMessageBox.question(
                self,
                "Set Location",
                f"Set the location of {which} to {latitude:.5f}, {longitude:.5f}?",
            )
            if answer != QMessageBox.Yes:
                return
            db.set_location(ids, latitude, longitude)
            self.messages.add(
                f"Set the location of {len(ids)} photo(s) to "
                f"{latitude:.5f}, {longitude:.5f}"
            )
            self.refresh_after_data_change()

        self.tabs.setCurrentWidget(self.map)
        self.map.view.arm_location(place)
        self.messages.add(
            f"Double-click the map where {which} was taken "
            "(on the map, not on a marker; leaving the map cancels)"
        )

    def delete_items(self):
        items_to_delete = self._items_to_edit()

        if not items_to_delete:
            return

        dialog = DeleteConfirmationDialog(items_to_delete, self)
        if dialog.exec_() == QDialog.Accepted:
            removed, failures = delete_photos(
                items_to_delete, dialog.should_delete_files()
            )
            for failure in failures:
                self.messages.add(f"[ERROR] {failure}")
            if failures:
                QMessageBox.warning(
                    self,
                    "Some photos were kept",
                    f"{len(failures)} photo(s) could not be deleted from disk, "
                    "so they stay in the library. See the Messages tab.",
                )
            self.messages.add(f"Deleted {len(removed)} photo(s)")

            # Only what was removed leaves the selection; a photo kept after a
            # failed file delete is still selected.
            for item_id in removed:
                self.selection.discard(item_id)
            self.refresh_after_data_change()

    def mark_as_derived(self):
        """Record the current photo as made from the selected ones.

        A panorama from its frames, or an edit from its original. The current
        photo - the one under the red frame - is the result; the selection is
        what it was made from.
        """
        current = self.grid.current_item()
        parents, error = lineage_targets(
            current.item.id if current else None, self.selection.ids()
        )
        if error:
            self.messages.add(error)
            return

        try:
            db.set_parents(current.item.id, parents)
        except ValueError as exception:
            # A cycle: the current photo is already an ancestor of one of the
            # sources, so this link would make lineage circular.
            self.messages.add(str(exception))
            return

        self.messages.add(f"Marked as derived from {len(parents)} photo(s).")
        self.update_items()

    def clear_lineage(self):
        """Forget what the current photo was derived from."""
        current = self.grid.current_item()
        if current is None:
            self.messages.add("No current photo to clear.")
            return
        if not db.get_parent_ids(current.item.id):
            self.messages.add("This photo has no recorded sources.")
            return
        db.set_parents(current.item.id, [])
        self.messages.add("Cleared the recorded sources.")
        self.update_items()

    def move_selection_to_profile(self):
        """Move the selected photos into another profile's database.

        Everything that can fail is checked before the transaction opens, so a
        refusal leaves the current database exactly as it was. Afterwards the
        selection is cleared: its ids belonged to rows that no longer exist
        here, and acting on ids from another database is a bug this project has
        already shipped once.
        """
        # A running task may be writing to these photos right now, and it
        # would be left pointing at rows that have just moved away.
        if not self.tasks.runner.is_idle():
            self.messages.add(
                "A task is still running. Wait for it to finish before moving photos."
            )
            return

        # Refuse if nothing is selected
        if not len(self.selection):
            self.messages.add("Nothing is selected.")
            return

        # Get list of selectable profiles (all except current)
        all_profiles = self.config.get_profiles()
        selectable = [p for p in all_profiles if p != self.config.profile]

        # Refuse if no other profiles are available
        if not selectable:
            self.messages.add("No other profiles available to move to.")
            return

        # Open the dialog for the user to choose a target profile and confirm
        # the dialog shows count, target, and warnings about tags and files
        dialog = MoveToProfileDialog(selectable, len(self.selection))
        if dialog.exec_() != QDialog.Accepted:
            return

        target_profile = dialog.selected_profile()
        if not target_profile:
            return

        # Resolve the target path via config
        try:
            target_path = self.config.get_profile_database(target_profile)
        except config.ProfileNotFoundError:
            self.messages.add(f"[ERROR] Profile {target_profile!r} not found in config")
            return

        # Validate and prepare the target database before the transaction.
        # Everything that can fail is checked here, before the transaction opens.
        try:
            dbmove.prepare_target(target_path)
        except dbmove.TargetUnusable as error:
            QMessageBox.critical(
                self, "Cannot Move to Target", f"Target database unusable:\n\n{error}"
            )
            return

        # Perform the move inside a session
        try:
            with db.new_session() as session:
                result = dbmove.move_items(session, target_path, self.selection.ids())

            # Report results through messages
            self.messages.add(
                f"Moved {len(result.moved_ids)} photos to {target_profile}"
            )
            if result.skipped_ids:
                self.messages.add(f"Skipped {len(result.skipped_ids)} duplicate photos")
            if result.dropped_tags:
                tags_str = ", ".join(result.dropped_tags)
                self.messages.add(f"Dropped tags: {tags_str}")
            if result.dropped_lineage:
                self.messages.add(
                    f"Dropped {result.dropped_lineage} derived-from link(s) "
                    "that cannot survive the move"
                )

            # Clear the selection and update UI
            self.selection.clear()
            self.refresh_after_data_change()

        except Exception as error:
            QMessageBox.critical(
                self, "Move Failed", f"An error occurred during the move:\n\n{error}"
            )
            self.messages.add(f"[ERROR] Move failed: {error}")

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
            new_ids = db.add_images(files)
            self.refresh_after_data_change()
            self.messages.add(f"finished adding {directory}")

            # Run the automatic plugins straight away, so a new batch is
            # hashed, dated and animates without being asked for. Most see only
            # the photos this import added: rereading every undated file in a
            # large library for each folder added would be slow. Those that can
            # cheaply tell what is left (hashes, previews) take the whole
            # library, so they finish what a cancelled import left undone. An
            # import that added nothing runs none. The order comes from each
            # plugin's ``after`` declaration, not from registration: a preview
            # is cached under the item's md5, so hashing must come before it.
            if new_ids:
                imported = Scope(tuple(new_ids), kind="imported")
                for plugin in self.tasks.registry.auto_plugins():
                    scope = Scope.LIBRARY if plugin.auto_whole_library else imported
                    self.tasks.run_plugin(plugin, scope)

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


_QT_LOG_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}

# libpng emits this for any PNG carrying an old Adobe colour profile. It is not
# actionable, it fires once per image decoded, and it lands on stderr
# underneath our own output. Dropping it here catches every source: the user's
# photos and our cached thumbnails alike.
_QT_MESSAGE_NOISE = ("iCCP: known incorrect sRGB profile",)


def qt_message_handler(mode, context, message):
    """Send Qt's own output through logging instead of straight to stderr."""
    if any(noise in message for noise in _QT_MESSAGE_NOISE):
        return
    logging.getLogger("qt").log(_QT_LOG_LEVELS.get(mode, logging.INFO), "%s", message)


def format_unhandled(exc_type, exc, tb) -> tuple[str, str]:
    """A one-line summary and the full traceback of an uncaught exception."""
    summary = f"{exc_type.__name__}: {exc}"
    details = "".join(traceback.format_exception(exc_type, exc, tb))
    return summary, details


def make_excepthook(report):
    """Build a sys.excepthook that reports an uncaught exception and carries on.

    PyQt6 aborts the whole process when an exception escapes a slot, unless a
    hook is installed. Left alone, any bug in a handler would close the
    program with the user's unsaved tagging in flight. The hook logs the
    traceback and hands it to ``report`` so the user can see what went wrong.

    KeyboardInterrupt keeps the default handling: it is how a terminal asks
    the program to stop, and that is not a bug to report.
    """

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        summary, details = format_unhandled(exc_type, exc, tb)
        logger.error("Unhandled exception: %s\n%s", summary, details)
        try:
            report(summary, details)
        except Exception:
            # A failing reporter must not turn one abort into a silent one.
            logger.exception("could not show the unhandled exception")

    return hook


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
    qInstallMessageHandler(qt_message_handler)


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

    # Validate before the window exists: constructing it opens a database, so
    # a bad path must be caught while nothing has been opened yet.
    configfile = None
    if commands["--config"]:
        configfile = Path(commands["--config"]).expanduser()
        if not configfile.is_file():
            logger.error("config file %s cannot be opened... exiting", configfile)
            sys.exit(1)

    app = QApplication(sys.argv)
    app.aboutToQuit.connect(stop_background_decodes)
    try:
        window = MainWindow(app, config_file=configfile, profile=commands["--profile"])
    except config.ProfileNotFoundError as error:
        logger.error("%s", error)
        sys.exit(3)

    if configfile:
        logger.info("Starting with config file: %s", configfile)

    if commands["--profile"]:
        logger.info("Starting with profile: %s", commands["--profile"])

    if commands["--import-from-f-spot"]:
        old_db = Path(commands["--import-from-f-spot"]).expanduser()
        DBimport.import_f_spot(old_db)

    # Installed once the window exists, so the report has somewhere to go. The
    # default hook is what PyQt6 aborts on; see make_excepthook.
    sys.excepthook = make_excepthook(window.report_unhandled)

    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
