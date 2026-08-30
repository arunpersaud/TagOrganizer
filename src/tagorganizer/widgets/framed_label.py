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
from qtpy.QtGui import QPainter, QPen, QImage, QPixmap
from qtpy.QtCore import Qt, Signal

from .helper import get_thumbnail_loader
from ..models import Item


class FramedLabel(QLabel):
    """A widget to show an thumbnail that can draw blue and red frames around it."""

    # Emits the tile itself: the grid knows its own widget order, and the item
    # id alone would not tell it which position was clicked.
    doubleClicked = Signal(object)

    # Shift-click extends the selection to this tile; a plain click is left
    # alone so it keeps doing nothing.
    shiftClicked = Signal(object)

    def __init__(self, item: Item, photos_path: Path):
        super().__init__()

        self.item = item
        self.photos_path = photos_path
        self.pixmap_width = 150

        self.pixmap = None

        # Show placeholder immediately (filename)
        self.show_pixmap(None)
        self.setAlignment(Qt.AlignCenter)
        self.selected = False
        self.highlight = False

        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        # Request thumbnail decode asynchronously
        loader = get_thumbnail_loader()
        loader.thumbnail_ready.connect(self._on_thumbnail_ready)
        loader.load(item, self.pixmap_width, photos_path)

    def _on_thumbnail_ready(self, key, qimage: QImage) -> None:
        """Take a decode result if it is for what this tile is showing.

        Results are addressed by (item id, size) rather than by widget, so a
        tile picks up whatever decode matches its current item and requested
        size - including one the preloader started for that same item. The
        same check is what stops a stale result painting over a tile that has
        since been reused for a different photo, or a small thumbnail landing
        after a resize has already asked for a larger one.
        """
        if key != get_thumbnail_loader().key_for(self.item, self.pixmap_width):
            return

        if qimage is None or qimage.isNull():
            self.show_pixmap(None)
            return

        # QPixmap may only be built on the GUI thread, which is where this
        # slot runs. load_qimage has already written the disk cache entry.
        self.pixmap = QPixmap.fromImage(qimage)
        self.show_pixmap(self.pixmap)

    def show_pixmap(self, pixmap):
        """Show a thumbnail, or the file name when there is no thumbnail.

        load_pixmap returns None when the file has been moved or deleted
        outside the application, or is a format it cannot decode. Passing that
        straight to setPixmap raises TypeError and takes down the whole grid
        page, so fall back to showing which file is missing.
        """
        if pixmap is None:
            self.setText(Path(self.item.uri).name)
            return
        self.setPixmap(pixmap)

    def toggle_selected(self):
        self.selected = not self.selected
        self.update()

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit(self)
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.modifiers() & Qt.ShiftModifier:
            self.shiftClicked.emit(self)
            return
        super().mousePressEvent(event)

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
        size_changed = False
        if self.width() > 1.5 * self.pixmap_width:
            self.pixmap_width = self.width()
            size_changed = True
        if self.width() < 0.6 * self.pixmap_width:
            self.pixmap_width = self.width()
            size_changed = True

        if size_changed:
            # Request new thumbnail at larger size asynchronously
            loader = get_thumbnail_loader()
            loader.load(self.item, self.pixmap_width, self.photos_path)
            # Keep showing current pixmap or placeholder while loading
            if self.pixmap is not None:
                self.show_pixmap(
                    self.pixmap.scaled(
                        self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                )
        else:
            # No reload needed, just scale current pixmap
            if self.pixmap is None:
                self.show_pixmap(None)
            else:
                self.show_pixmap(
                    self.pixmap.scaled(
                        self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                )
        super().resizeEvent(event)
