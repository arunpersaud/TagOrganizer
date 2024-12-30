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

from qtpy.QtWidgets import QDialog, QDialogButtonBox, QLineEdit, QFormLayout


class AddTagDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Tag")

        self.layout = QFormLayout(self)

        self.tag_name_edit = QLineEdit(self)
        self.layout.addRow("Tag Name:", self.tag_name_edit)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def get_tag_name(self):
        return self.tag_name_edit.text()
