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

from functools import lru_cache
from pathlib import Path

from qtpy.QtWidgets import QCompleter
from qtpy.QtGui import QPixmap, QTransform
from qtpy.QtCore import Qt

import exifread as exif


@lru_cache(1_000)
def load_pixmap(file, size=150):
    pixmap = QPixmap(file)
    pixmap = pixmap.scaledToWidth(size, Qt.SmoothTransformation)
    orientation = get_orientation(file)
    pixmap = rotate_pixmap(pixmap, orientation)

    return pixmap


@lru_cache(100)
def load_full_pixmap(file):
    pixmap = QPixmap(file)
    orientation = get_orientation(file)
    pixmap = rotate_pixmap(pixmap, orientation)

    return pixmap


@lru_cache(1_000)
def load_exif(file):
    file = Path(file)
    if not file.is_file():
        return {}
    with file.open("rb") as f:
        tags = exif.process_file(f)
        return tags


def get_orientation(file):
    tags = load_exif(file)
    orientation_tag = "Image Orientation"
    if orientation_tag in tags:
        orientation = tags[orientation_tag].values[0]
    else:
        orientation = 1  # Default to normal orientation if tag is not found
    return orientation


def rotate_pixmap(pixmap, orientation):
    transform = QTransform()
    if orientation == 3:
        transform.rotate(180)
    elif orientation == 6:
        transform.rotate(90)
    elif orientation == 8:
        transform.rotate(-90)
    return pixmap.transformed(transform, Qt.SmoothTransformation)


class CommaCompleter(QCompleter):
    def __init__(self, model, parent=None):
        super().__init__(model, parent)
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def splitPath(self, path: str) -> list[str]:
        return [path.split(",")[-1].strip()]
