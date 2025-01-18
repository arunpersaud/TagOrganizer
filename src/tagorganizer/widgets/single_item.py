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

from qtpy.QtWidgets import (
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QScrollArea,
    QStackedLayout,
    QHBoxLayout,
    QWidget,
)
from qtpy.QtCore import Qt

from .helper import load_exif


class SingleItem(QWidget):
    def __init__(self):
        super().__init__()
        layout = QStackedLayout()
        layout.setStackingMode(QStackedLayout.StackAll)

        self.item = QLabel()
        self.item.setAlignment(Qt.AlignCenter)

        self.exif_table = QTableWidget()
        self.exif_table.setVisible(False)
        self.exif_table.setColumnCount(2)
        self.exif_table.setHorizontalHeaderLabels(["Key", "Value"])
        self.exif_table.verticalHeader().setVisible(False)
        self.exif_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.exif_table.setSizeAdjustPolicy(
            QTableWidget.SizeAdjustPolicy.AdjustToContents
        )
        # 50% transparent black
        self.exif_table.setStyleSheet(
            "QTableWidget { background-color: rgba(0, 0, 0, 100); }"
            "QHeaderView::section { background-color: rgba(0, 0, 0, 127); }"
        )

        # Scroll area for EXIF table
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setWidget(self.exif_table)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; }")
        self.scroll_area.viewport().setStyleSheet("background-color: transparent;")

        self.scroll_area_container = QWidget()
        self.scroll_area_container.setStyleSheet("background: transparent;")
        self.scroll_area_layout = QHBoxLayout()
        self.scroll_area_layout.addStretch()
        self.scroll_area_layout.addWidget(self.scroll_area)
        self.scroll_area_container.setLayout(self.scroll_area_layout)
        self.scroll_area_container.setVisible(False)

        self.filename = QLineEdit()
        self.filename.setReadOnly(True)
        self.filename.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.filename.setStyleSheet("background: transparent; border: none;")
        self.filename.setVisible(False)

        layout.addWidget(self.item)
        layout.addWidget(self.scroll_area_container)
        layout.addWidget(self.filename)

        self.setLayout(layout)

    def load_exif(self, filename: str):
        tags = load_exif(filename)
        self.show_exif(tags)

    def show_exif(self, tags):
        self.exif_table.clearContents()
        self.exif_table.setRowCount(len(tags))
        for row, (key, value) in enumerate(sorted(tags.items())):
            key_item = QTableWidgetItem(key)
            value_item = QTableWidgetItem(self.format_str(value))
            self.exif_table.setItem(row, 0, key_item)
            self.exif_table.setItem(row, 1, value_item)
        self.exif_table.resizeColumnsToContents()
        self.adjust_scroll_area_width()

    def adjust_scroll_area_width(self):
        # Calculate the required width for the scroll area
        width = (
            self.exif_table.verticalHeader().width()
            + self.exif_table.columnWidth(0)
            + self.exif_table.columnWidth(1)
            + self.exif_table.verticalScrollBar().width()
        )
        self.scroll_area.setMinimumWidth(width)
        self.scroll_area_container.setMinimumWidth(width)
        self.scroll_area_container.resize(self.item.size())

    def format_str(self, s) -> str:
        s = str(s)
        if len(s) > 20:
            s = s[:17] + "..."
        return s

    def setPixmap(self, pixmap):
        self.item.setPixmap(pixmap)

    def toggle_exif_visibility(self):
        self.scroll_area_container.setVisible(
            not self.scroll_area_container.isVisible()
        )

    def toggle_filename_visibility(self):
        self.filename.setVisible(not self.filename.isVisible())
