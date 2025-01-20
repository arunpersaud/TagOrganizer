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
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QPushButton,
    QScrollArea,
    QWidget,
)

from .helper import load_pixmap


class DeleteConfirmationDialog(QDialog):
    def __init__(self, items, main):
        super().__init__()

        self.items = items
        self.main = main

        self.setWindowTitle("Confirm Deletion")

        layout = QVBoxLayout()

        # Scroll area for thumbnails
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QHBoxLayout()
        scroll_widget.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)

        for item in self.items:
            label = QLabel()
            pixmap = load_pixmap(item, size=80, photos_dir=self.main.config.photos)
            label.setPixmap(pixmap)
            label.setToolTip(item.uri)
            scroll_layout.addWidget(label)

        layout.addWidget(scroll_area)

        # Checkbox for deleting from filesystem
        self.delete_files_checkbox = QCheckBox("Also delete photos from filesystem?")
        layout.addWidget(self.delete_files_checkbox)

        # Buttons
        button_layout = QHBoxLayout()
        cancel_button = QPushButton("Cancel")
        self.delete_button = QPushButton("Delete from database")

        cancel_button.clicked.connect(self.reject)
        self.delete_button.clicked.connect(self.accept)

        self.delete_files_checkbox.stateChanged.connect(self.update_delete_button_text)

        button_layout.addWidget(cancel_button)
        button_layout.addStretch(1)
        button_layout.addWidget(self.delete_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def update_delete_button_text(self):
        if self.delete_files_checkbox.isChecked():
            self.delete_button.setText("Delete from database and filesystem")
        else:
            self.delete_button.setText("Delete from database")

    def should_delete_files(self):
        return self.delete_files_checkbox.isChecked()
