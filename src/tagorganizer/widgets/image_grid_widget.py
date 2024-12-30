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

from qtpy.QtWidgets import QWidget, QGridLayout

from .framed_label import FramedLabel


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
            label = FramedLabel(item)
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

    def clear_selection(self):
        for row in range(self.layout.rowCount()):
            for col in range(self.layout.columnCount()):
                item = self.layout.itemAtPosition(row, col)
                if item is not None:
                    widget = item.widget()
                    if widget.selected:
                        widget.toggle_selected()

    def current_item(self):
        if self.widgets:
            current = self.highlight % len(self.widgets)
            return self.widgets[current]

    def toggle_selection(self):
        if self.widgets:
            current = self.highlight % len(self.widgets)
            self.widgets[current].toggle_selected()
            return self.widgets[current]

    def set_highlight(self, new):
        if self.widgets:
            old_n = self.highlight % len(self.widgets)
            self.widgets[old_n].set_highlight(False)

        self.highlight = new

        if self.widgets:
            new_n = self.highlight % len(self.widgets)
            self.widgets[new_n].set_highlight(True)
