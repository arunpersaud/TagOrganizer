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

from qtpy.QtWidgets import QWidget
from qtpy.QtGui import QImage, QPainter
from qtpy.QtCore import Qt, QRect, QPoint
import logging

logger = logging.getLogger(__name__)

MAX_PREVIEW = 9


def mosaic_grid(count: int) -> tuple[int, int]:
    """Rows and columns for `count` previews, at most 3x3.

    Only as large as it needs to be: one photo is one cell, four is two by two.
    """
    shown = min(count, MAX_PREVIEW)
    if shown <= 0:
        return 0, 0
    columns = 1 if shown == 1 else (2 if shown <= 4 else 3)
    rows = (shown + columns - 1) // columns
    return rows, columns


def compose_mosaic(images, cell: int = 150):
    """Paint up to nine thumbnails into a grid.

    Sourced from the already-decoded thumbnail cache, so this costs about a
    millisecond - it runs on every hover and has to feel instant.
    """
    if not images:
        return QImage()

    # Determine the grid dimensions.
    rows, columns = mosaic_grid(len(images))
    if rows == 0 or columns == 0:
        return QImage()

    # Create the output image with appropriate dimensions.
    total_width = columns * cell
    total_height = rows * cell
    mosaic = QImage(total_width, total_height, QImage.Format_RGB32)
    mosaic.fill(0xFFFFFF)  # White background

    # Paint each image into its cell.
    painter = QPainter(mosaic)
    try:
        for idx, image in enumerate(images):
            if idx >= MAX_PREVIEW:
                break

            row = idx // columns
            col = idx % columns
            x = col * cell
            y = row * cell

            # Scale the image to fit the cell.
            if not image.isNull():
                scaled = image.scaledToWidth(cell, Qt.SmoothTransformation)
                # Center the scaled image vertically if it's shorter than the cell.
                y_offset = (cell - scaled.height()) // 2
                painter.drawImage(x, y + y_offset, scaled)
    finally:
        painter.end()

    return mosaic


class MosaicOverlay(QWidget):
    """A frameless preview shown above the map, following the cursor."""

    def __init__(self, parent=None):
        """Initialize the overlay widget.

        Uses Qt.ToolTip and Qt.FramelessWindowHint so it floats above the web
        view without taking focus.
        """
        super().__init__(parent)
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._pixmap = None

    def show_for(self, pixmap, global_pos):
        """Show the mosaic near the given global cursor position.

        The overlay is positioned near the cursor but nudged to stay on screen
        rather than running off the edge.

        Args:
            pixmap: QPixmap containing the mosaic to display
            global_pos: QPoint in global coordinates for cursor position
        """
        self._pixmap = pixmap
        if pixmap is None or pixmap.isNull():
            self.hide()
            return

        # Set the widget size to match the pixmap.
        self.resize(pixmap.width(), pixmap.height())

        # Position near the cursor, nudging to stay on screen.
        offset_x = 20
        offset_y = 20
        target_pos = global_pos + QPoint(offset_x, offset_y)

        # Get the screen geometry to ensure we stay on screen.
        screen = self.screen()
        if screen:
            screen_rect = screen.geometry()
            widget_rect = QRect(target_pos, self.size())

            # Nudge left if off the right edge.
            if widget_rect.right() > screen_rect.right():
                target_pos.setX(screen_rect.right() - widget_rect.width() - 5)

            # Nudge up if off the bottom edge.
            if widget_rect.bottom() > screen_rect.bottom():
                target_pos.setY(screen_rect.bottom() - widget_rect.height() - 5)

            # Keep x coordinate non-negative.
            if target_pos.x() < screen_rect.left():
                target_pos.setX(screen_rect.left() + 5)

            # Keep y coordinate non-negative.
            if target_pos.y() < screen_rect.top():
                target_pos.setY(screen_rect.top() + 5)

        self.move(target_pos)
        self.show()

    def hide_mosaic(self):
        """Hide the overlay."""
        self.hide()

    def paintEvent(self, event):
        """Paint the mosaic onto the widget."""
        if self._pixmap is not None and not self._pixmap.isNull():
            painter = QPainter(self)
            painter.drawPixmap(0, 0, self._pixmap)
            painter.end()
