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

from qtpy.QtWidgets import QLabel, QSizePolicy
from qtpy.QtGui import QPainter, QPen
from qtpy.QtCore import Qt

from .helper import load_pixmap


class FramedLabel(QLabel):
    """A widget to show an thumbnail that can draw blue and red frames around it."""

    def __init__(self, item, *args, **kwargs):
        super().__init__(*args, **kwargs)
        filename = Path(item.uri)
        self.pixmap_width = 150
        self.pixmap = load_pixmap(filename, self.pixmap_width)
        self.setPixmap(self.pixmap)
        self.setAlignment(Qt.AlignCenter)
        self.selected = False
        self.highlight = False
        self.item = item

        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

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

    def resizeEvent(self, event):
        # reload pixmap if needed to get reasonable resolution
        if self.width() > 1.5 * self.pixmap_width:
            self.pixmap_width = self.width()
            self.pixmap = load_pixmap(Path(self.item.uri), self.pixmap_width)
        if self.width() < 0.6 * self.pixmap_width:
            self.pixmap_width = self.width()
            self.pixmap = load_pixmap(Path(self.item.uri), self.pixmap_width)

        # scale pixmapx
        scaled_pixmap = self.pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.setPixmap(scaled_pixmap)
        super().resizeEvent(event)
