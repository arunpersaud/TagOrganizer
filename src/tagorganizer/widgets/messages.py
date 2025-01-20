from qtpy.QtWidgets import (
    QTextEdit,
    QVBoxLayout,
    QPushButton,
    QWidget,
)
from qtpy.QtGui import QColor
from qtpy.QtCore import Qt


class Messages(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main

        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)

        self.clear_button = QPushButton("Clear", self)
        self.clear_button.clicked.connect(self.clear_messages)

        layout = QVBoxLayout()
        layout.addWidget(self.text_edit)
        layout.addWidget(self.clear_button)
        self.setLayout(layout)

    def clear_messages(self):
        self.text_edit.clear()

    def add(self, message):
        """Add a message to the QTextEdit and highlight the tab if it's not active."""
        self.text_edit.append(message)
        current_index = self.main.tabs.currentIndex()
        tab_index = self.main.tabs.indexOf(self.main.messages)

        if current_index != tab_index:
            self.main.tabs.tabBar().setTabTextColor(tab_index, QColor(Qt.red))

    def reset_tab_color(self):
        """Reset the tab color to default."""
        tab_index = self.main.tabs.indexOf(self.main.messages)
        self.main.tabs.tabBar().setTabTextColor(tab_index, QColor(Qt.black))
