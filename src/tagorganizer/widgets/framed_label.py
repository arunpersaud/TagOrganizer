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

from qtpy.QtWidgets import QLabel
from qtpy.QtGui import QPainter, QPen
from qtpy.QtCore import Qt

from .helper import load_pixmap


class FramedLabel(QLabel):
    """A widget to show an thumbnail that can draw blue and red frames around it."""

    def __init__(self, item, *args, **kwargs):
        super().__init__(*args, **kwargs)
        filename = str(item.uri)
        pixmap = load_pixmap(filename)
        self.setPixmap(pixmap)
        self.setAlignment(Qt.AlignCenter)
        self.selected = False
        self.highlight = False
        self.item = item

    def toggle_selected(self):
        self.selected = not self.selected
        self.update()

    def set_highlight(self, selected):
        self.highlight = selected
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        if self.selected:
            pen = QPen(Qt.blue, 8)
            painter.setPen(pen)
            painter.drawRect(self.rect())
        if self.highlight:
            pen = QPen(Qt.red, 5)
            painter.setPen(pen)
            painter.drawRect(self.rect())
