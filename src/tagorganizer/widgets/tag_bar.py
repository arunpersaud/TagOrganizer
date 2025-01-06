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

from qtpy.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy


class TagBar(QHBoxLayout):
    def __init__(self, main):
        super().__init__()

        self.main = main
        self.selected_tags = []

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_selected_tags)
        self.clear_button.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum
        )
        self.addWidget(self.clear_button, 0)
        self.addStretch(1)

    def clear_selected_tags(self):
        for _, w in self.selected_tags:
            w.setParent(None)
        self.selected_tags = []
        self.main.update_items()

    def add_tag(self, tag_name: str):
        tag_button = QPushButton(tag_name)
        tag_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        tag_button.clicked.connect(lambda: self.remove_tag_button(tag_button))
        self.addWidget(tag_button, 0)
        self.selected_tags.append((tag_name, tag_button))
        self.main.update_items()

    def get_selected_tags(self):
        return [x[0] for x in self.selected_tags]

    def remove_tag_button(self, w):
        for i, (_, widget) in enumerate(self.selected_tags):
            if w == widget:
                break
        w.setParent(None)
        del self.selected_tags[i]
        self.main.update_items()
