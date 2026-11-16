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
from qtpy.QtGui import QColor, QPainter, QPen, QImage, QPixmap
from qtpy.QtCore import Qt, Signal, QTimer

from .. import config
from .helper import (
    SPRITE_COLUMNS,
    SPRITE_FRAMES,
    get_thumbnail_loader,
    preview_file,
    sprite_frame_rect,
)
from ..models import Item


# A photo derived from others is marked with a dot. Amber rather than the
# blue or red used by the selection frames, so the three never read as the
# same signal.
LINEAGE_DOT_COLOUR = QColor(255, 170, 0)
LINEAGE_DOT_SIZE = 12


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

        # A cached sprite sheet and where we are in it while hovering. Loaded
        # lazily on the first hover so a grid page costs nothing extra.
        self._sheet = None
        self._frame = 0
        self._animation = QTimer(self)
        self._animation.setInterval(50)
        self._animation.timeout.connect(self._advance_frame)

        # A tile with no result yet is *pending*, not broken. Saying so stops a
        # freshly imported library looking like a wall of missing files.
        self.show_pending()
        self.setAlignment(Qt.AlignCenter)
        self.selected = False
        self.highlight = False

        # Photos this one was derived from, for the indicator dot and its
        # tooltip. The grid fills this in from one query per page.
        self._parent_names = []

        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        # Request thumbnail decode asynchronously
        self._wanted_key = None
        loader = get_thumbnail_loader()
        loader.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._request_thumbnail()

    def _request_thumbnail(self) -> None:
        """Ask for the thumbnail at the current size, and remember what it is.

        The key is recorded at the moment of the request. A result for an
        earlier size, or for an item from a profile that has since been replaced,
        then cannot match, even though it may still arrive.
        """
        loader = get_thumbnail_loader()
        self._wanted_key = loader.key_for(self.item, self.pixmap_width)
        loader.load(self.item, self.pixmap_width, self.photos_path)

    def _on_thumbnail_ready(self, key, qimage: QImage) -> None:
        """Take a decode result if it is the one this tile is waiting for.

        Results are addressed by (generation, item id, size) rather than by
        widget, so a tile picks up whatever decode matches what it asked for -
        including one the preloader started for that same item. A stale result,
        from a size the tile has since left or a profile that has been replaced,
        is recognised by its key and dropped.
        """
        if key != self._wanted_key:
            return

        if qimage is None or qimage.isNull():
            self.show_pixmap(None)
            return

        # QPixmap may only be built on the GUI thread, which is where this
        # slot runs. load_qimage has already written the disk cache entry.
        self.pixmap = QPixmap.fromImage(qimage)
        # Scale to the tile before showing it. load_qimage scales to a target
        # *width*, so a portrait photo comes back taller than a square tile, and
        # QLabel silently clips a pixmap larger than itself - the user would see
        # a band from the middle of the photo instead of the whole photo.
        self.show_pixmap(self.fit_to_tile(self.pixmap))

    def fit_to_tile(self, pixmap):
        """Scale a pixmap down to this tile, keeping its proportions.

        The single place that decides how a thumbnail is sized for display, so
        the freshly-decoded path and the resize path cannot drift apart.
        """
        return pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def show_pending(self):
        """Say the thumbnail is still being made.

        Distinct from show_pixmap(None), which means a decode actually failed -
        a missing or unreadable file. Rendering both the same way hid real
        errors among tiles that were merely still working.
        """
        self.setText(f"generating preview...\n{Path(self.item.uri).name}")

    def is_animating(self) -> bool:
        return self._animation.isActive()

    def enterEvent(self, event):
        """Play the cached preview while the cursor rests on a video tile.

        Only the hovered tile animates, so exactly one timer ever runs. A video
        whose preview the background task has not reached yet simply stays
        still rather than stalling the grid to build one here.
        """
        if self._load_sheet() is not None:
            self._frame = 0
            self._animation.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animation.stop()
        if self.pixmap is not None:
            self.show_pixmap(self.fit_to_tile(self.pixmap))
        super().leaveEvent(event)

    def _load_sheet(self):
        """The sprite sheet for this item, or None if there is not one."""
        if self._sheet is not None:
            return self._sheet
        if Path(self.item.uri).suffix.lower() not in config.VIDEO_SUFFIX:
            return None
        if not self.item.uri_md5:
            return None

        path = preview_file(self.item.uri_md5, self.pixmap_width, self.photos_path)
        if not path.is_file():
            return None

        sheet = QPixmap(str(path))
        if sheet.isNull():
            return None
        self._sheet = sheet
        return self._sheet

    def _advance_frame(self):
        """Show the next frame, wrapping back to the start."""
        if self._sheet is None:
            return
        frame_width = self._sheet.width() // SPRITE_COLUMNS
        frame_height = self._sheet.height() // (SPRITE_FRAMES // SPRITE_COLUMNS)
        x, y, w, h = sprite_frame_rect(self._frame, frame_width, frame_height)
        self.show_pixmap(self.fit_to_tile(self._sheet.copy(x, y, w, h)))
        self._frame = (self._frame + 1) % SPRITE_FRAMES

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
            # Emitting the signal synchronously triggers extend_selection_to, which
            # calls update_items(). That rebuilds the grid: ImageGridWidget.clear()
            # takes every tile out of the layout and calls deleteLater() on it,
            # including this widget. By the time emit returns, this tile is already
            # scheduled for destruction. We must not hand a mousePressEvent to a
            # widget that no longer exists.
            return
        super().mousePressEvent(event)

    def set_parent_names(self, names):
        """Name the photos this one was derived from, or pass [] for none."""
        self._parent_names = list(names)
        if self._parent_names:
            shown = [Path(name).name for name in self._parent_names]
            self.setToolTip("Derived from: " + ", ".join(sorted(shown)))
        else:
            self.setToolTip("")
        self.update()

    def has_parents(self) -> bool:
        return bool(self._parent_names)

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
        if self._parent_names:
            # Inset past the selection frames, which are drawn on the border
            # itself and would otherwise cover the dot.
            painter.setPen(QPen(Qt.white, 1))
            painter.setBrush(LINEAGE_DOT_COLOUR)
            painter.drawEllipse(10, 10, LINEAGE_DOT_SIZE, LINEAGE_DOT_SIZE)

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
            self._request_thumbnail()

        # Either way, show what we already have, fitted to the new size. A
        # higher-resolution decode, if one was requested, replaces this when it
        # arrives.
        if self.pixmap is None:
            self.show_pixmap(None)
        else:
            self.show_pixmap(self.fit_to_tile(self.pixmap))
        super().resizeEvent(event)
