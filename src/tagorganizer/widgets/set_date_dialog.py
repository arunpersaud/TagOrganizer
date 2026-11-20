"""Ask for the date and time to give one or more photos.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from datetime import datetime

from qtpy.QtCore import QDateTime
from qtpy.QtWidgets import (
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)


class SetDateDialog(QDialog):
    def __init__(self, initial: datetime | None, count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Date")
        self.prompt = QLabel(
            f"Date and time for {count} photo" + ("" if count == 1 else "s") + ":"
        )
        self.edit = QDateTimeEdit(QDateTime(initial or datetime.now()))
        self.edit.setCalendarPopup(True)
        self.edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.prompt)
        layout.addWidget(self.edit)
        layout.addWidget(buttons)

    def chosen(self) -> datetime:
        return self.edit.dateTime().toPyDateTime().replace(microsecond=0)
