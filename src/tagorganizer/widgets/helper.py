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

from qtpy.QtWidgets import QCompleter
from qtpy.QtGui import QPixmap
from qtpy.QtCore import Qt


@lru_cache(1_000)
def load_pixmap(file):
    pixmap = QPixmap(file)
    pixmap = pixmap.scaledToWidth(150, Qt.SmoothTransformation)
    return pixmap


@lru_cache(100)
def load_full_pixmap(file):
    pixmap = QPixmap(file)
    return pixmap


class CommaCompleter(QCompleter):
    def __init__(self, model, parent=None):
        super().__init__(model, parent)
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def splitPath(self, path: str) -> list[str]:
        return [path.split(",")[-1].strip()]
