"""Dialog for selecting a target profile when moving photos.

This dialog is shown before a move operation to confirm:
1. Which profile is the target
2. How many photos will move
3. That tags will not travel (they are destroyed, not left behind)
"""

from qtpy.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
)


def selectable_profiles(all_profiles: list[str], current: str) -> list[str]:
    """Profiles a move can target: everything except the one already open.

    The user cannot move photos within the same database; only across profiles.
    Order is otherwise preserved to match the configuration file order.
    """
    return [p for p in all_profiles if p != current]


class MoveToProfileDialog(QDialog):
    """Dialog for choosing a target profile for moving photos.

    Shows the user:
    - How many photos will move
    - The target profile name
    - A reminder that tags will not travel
    """

    def __init__(self, profiles: list[str], count: int):
        super().__init__()
        self.setWindowTitle("Move Photos to Profile")
        self._selected_profile = None

        # Create layout
        layout = QVBoxLayout()

        # Instruction text
        instruction_label = QLabel(f"Move {count} photo{'s' if count != 1 else ''} to:")
        layout.addWidget(instruction_label)

        # Profile selection
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(profiles)
        layout.addWidget(self.profile_combo)

        # Warning about tags
        warning_label = QLabel(
            "Warning: Tags will not travel.\n"
            "Photos will arrive untagged, and their tags here will be destroyed.\n"
            "Files on disk will not be moved; only database records."
        )
        warning_label.setStyleSheet("QLabel { color: red; }")
        layout.addWidget(warning_label)

        # OK and Cancel buttons
        self.ok_button = QPushButton("Move")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.ok_button)
        buttons_layout.addWidget(self.cancel_button)
        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    def selected_profile(self) -> str | None:
        """Return the selected profile name, or None if cancelled."""
        if self.result() == QDialog.Accepted:
            return self.profile_combo.currentText()
        return None
