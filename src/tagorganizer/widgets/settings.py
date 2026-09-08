"""Where things live, and which plugins are switched on.

Two questions the application could not previously answer about itself: which
database am I actually looking at, and where do I put a plugin. Both are shown
here as selectable text, because a path you cannot copy is a path you have to
retype.

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

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


def describe_paths(config, plugin_directories) -> list[tuple[str, Path]]:
    """Every location the application uses, labelled, in a stable order."""
    described = [
        ("Config file", Path(config.config_file)),
        ("Database", Path(config.db)),
        ("Photos", Path(config.photos)),
        ("Videos", Path(config.videos)),
    ]
    described.extend(("Plugins", Path(directory)) for directory in plugin_directories)
    return described


class SettingsDialog(QDialog):
    """Show the paths, and let plugins be switched on and off."""

    def __init__(
        self, config, plugins, broken, disabled, plugin_directories, parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("Settings")

        layout = QVBoxLayout()

        # --- paths ---------------------------------------------------------
        self._paths = describe_paths(config, plugin_directories)
        width = max((len(label) for label, _ in self._paths), default=0)
        self.paths_view = QLabel(
            "\n".join(f"{label:<{width}}  {path}" for label, path in self._paths)
        )
        # Selectable so a path can be copied out rather than transcribed.
        self.paths_view.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.paths_view.setStyleSheet("font-family: monospace;")

        paths_box = QGroupBox("Locations")
        paths_layout = QVBoxLayout()
        paths_layout.addWidget(self.paths_view)
        paths_box.setLayout(paths_layout)
        layout.addWidget(paths_box)

        # --- plugins -------------------------------------------------------
        self.plugin_list = QListWidget()
        self._plugins = list(plugins)
        for plugin in self._plugins:
            entry = QListWidgetItem(f"{plugin.name}  ({plugin.category})")
            entry.setFlags(entry.flags() | Qt.ItemIsUserCheckable)
            entry.setCheckState(Qt.Unchecked if plugin.name in disabled else Qt.Checked)
            if plugin.description:
                entry.setToolTip(plugin.description)
            self.plugin_list.addItem(entry)

        plugin_box = QGroupBox("Plugins")
        plugin_layout = QVBoxLayout()
        plugin_layout.addWidget(self.plugin_list)

        # A plugin that failed to load cannot be switched on, so it is
        # reported rather than listed - with the error, because "it does not
        # appear" has to be diagnosable.
        self._broken = list(broken)
        if self._broken:
            self.broken_view = QLabel(self.broken_text())
            self.broken_view.setWordWrap(True)
            self.broken_view.setTextInteractionFlags(Qt.TextSelectableByMouse)
            plugin_layout.addWidget(QLabel("Failed to load:"))
            plugin_layout.addWidget(self.broken_view)
        plugin_box.setLayout(plugin_layout)
        layout.addWidget(plugin_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def paths_text(self) -> str:
        return self.paths_view.text()

    def broken_text(self) -> str:
        return "\n".join(
            f"{broken.path.name}: {broken.error}" for broken in self._broken
        )

    def plugin_names(self) -> list[str]:
        return [plugin.name for plugin in self._plugins]

    def disabled_plugins(self) -> set[str]:
        """The plugins left unchecked."""
        return {
            plugin.name
            for row, plugin in enumerate(self._plugins)
            if self.plugin_list.item(row).checkState() == Qt.Unchecked
        }
