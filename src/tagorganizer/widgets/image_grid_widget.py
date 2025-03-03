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

from functools import wraps
import time

from qtpy.QtWidgets import QWidget, QGridLayout
from qtpy.QtCore import QTimer

from .framed_label import FramedLabel
from .helper import load_pixmap, load_full_pixmap
from .. import db


class ImageGridWidget(QWidget):
    def __init__(self, main):
        super().__init__()
        self.columns = 5
        self.rows = 5
        self.N = self.columns * self.rows
        self.highlight = 0
        self.page = 0
        self.selected_items = []

        self.main = main
        self.layout = QGridLayout()
        self.setLayout(self.layout)

        # we need to keep a reference to the widgets in the grid, otherwise
        # itemAtPosition will return a QLabel and not a FramedLabel
        self.widgets = []

        self.preloader = QTimer()
        self.preloader.timeout.connect(self.preload_items)
        self.preloader.start(100)

    @staticmethod
    def change_highlight(func):
        @wraps(func)
        def wrapper(self, *args):
            if self.widgets:
                n = self.highlight % self.N
                n = min(n, len(self.widgets) - 1)
                self.widgets[n].set_highlight(False)
            func(self, *args)
            if self.widgets:
                n = self.highlight % self.N
                n = min(n, len(self.widgets) - 1)
                self.widgets[n].set_highlight(True)
            # update single item if in view
            if self.main.tabs.currentWidget() == self.main.single_item:
                self.main.show_current_item()

        return wrapper

    @change_highlight
    def show_images(self, items):
        row = 0
        col = 0

        self.clear()

        for i, item in enumerate(items):
            label = FramedLabel(item, self.main.config.photos)
            if item in self.selected_items:
                label.selected = True
            self.widgets.append(label)
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
            widget = self.current_item()
            widget.toggle_selected()

            item = widget.item

            if item in self.selected_items:
                self.selected_items.remove(item)
            else:
                self.selected_items.append(item)
            self.main.update_numbers(selected=len(self.selected_items))
            self.main.display_common_tags()

            return

    @change_highlight
    def move_left(self):
        self.highlight = max(self.highlight - 1, 0)

    @change_highlight
    def move_right(self):
        N = self.main.numbers[2]

        self.highlight = min(self.highlight + 1, N - 1)

    @change_highlight
    def move_up(self):
        self.highlight = max(self.highlight - self.columns, 0)

    @change_highlight
    def shift_move_up(self):
        self.highlight = max(self.highlight - self.N, 0)

    @change_highlight
    def move_down(self):
        N = self.main.numbers[2]

        self.highlight = min(self.highlight + self.columns, N - 1)

    @change_highlight
    def shift_move_down(self):
        N = self.main.numbers[2]

        self.highlight = min(self.highlight + self.N, N - 1)

    def preload_items(self):
        start = time.time()

        filters = self.main.tag_bar.get_filters()
        N = db.get_number_of_items(filters)

        # thumbnails +- 2 pages
        for i in range(self.page - 2, self.page + 3):
            if i < 1:
                continue
            if i > N // self.N:
                continue
            items = db.get_images(i, filters)
            for item in items:
                load_pixmap(item, 150, self.main.config.photos)
                if time.time() - start > 0.1:
                    return

        # full files +- 5 from current image
        for i in range(self.highlight - 5, self.highlight + 6):
            if i < 0:
                continue
            if i >= N:
                continue
            item = db.get_current_image(i, filters)
            load_full_pixmap(str(item.uri))
            if time.time() - start > 0.1:
                return
