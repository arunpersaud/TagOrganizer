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

from pathlib import Path

from dataclasses import dataclass
from datetime import datetime

from qtpy.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

RESERVED_TAGS = ["No Time", "No GPS", "Wrong dir"]


@dataclass
class SelectedTime:
    timestamp: datetime | None = None
    widget: QWidget | None = None


@dataclass
class SelectedTag:
    name: str | None = None
    widget: QWidget | None = None


@dataclass
class SelectedBool:
    value: bool | None = False
    widget: QWidget | None = None


@dataclass
class SelectedArea:
    min_longitude: float | None = None
    max_longitude: float | None = None
    min_latitude: float | None = None
    max_latitude: float | None = None
    widget: QWidget | None = None

    def set_values(self, min_longitude, max_longitude, min_latitude, max_latitude):
        self.min_latitude = min_latitude
        self.max_latitude = max_latitude
        self.min_longitude = min_longitude
        self.max_longitude = max_longitude


@dataclass
class Filters:
    tags: list[str] | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    min_longitude: float | None = None
    max_longitude: float | None = None
    min_latitude: float | None = None
    max_latitude: float | None = None
    wrong_dir: bool | None = False
    no_time: bool | None = False
    no_gps: bool | None = False
    directories: list[Path] | None = None


class TagBar(QHBoxLayout):
    def __init__(self, main):
        super().__init__()

        self.main = main

        self.selected_tags: list[SelectedTag] = []

        self.selected_times_min = SelectedTime()
        self.selected_times_max = SelectedTime()
        self.selected_area = SelectedArea()
        self.bool = {
            "Wrong dir": SelectedBool(),
            "No Time": SelectedBool(),
            "No GPS": SelectedBool(),
        }

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_selected_tags)
        self.clear_button.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum
        )
        self.addWidget(self.clear_button, 0)
        self.addStretch(1)

    def clear_selected_tags(self):
        for t in self.selected_tags:
            t.widget.setParent(None)
        for key, v in self.bool.items():
            if v.value:
                v.widget.setParent(None)
                self.bool[key].value = False

        self.selected_tags = []
        self.remove_tag_button(self.selected_times_min.widget)
        self.remove_tag_button(self.selected_times_max.widget)
        self.remove_tag_button(self.selected_area.widget)
        self.main.update_items()

    def get_all_names(self):
        out = []
        for t in self.selected_tags:
            out.append(t.name)
        for k, v in self.bool.items():
            if v.value:
                out.append(k)
        return out

    def add_tag(self, tag_name: str):
        # check if tag_name already in tag_bar
        if tag_name in self.get_all_names():
            return

        # if not, add new button
        tag_button = QPushButton(tag_name)
        tag_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        tag_button.clicked.connect(lambda flag, t=tag_button: self.remove_tag_button(t))
        self.addWidget(tag_button, 0)
        if tag_name in RESERVED_TAGS:
            self.bool[tag_name].value = True
            self.bool[tag_name].widget = tag_button
        else:
            self.selected_tags.append(SelectedTag(tag_name, tag_button))
        self.main.update_items()

    def add_time_tag(self, date: datetime, min_max: str = "<"):
        # delete button if there is already one
        if min_max == ">":
            if self.selected_times_min.timestamp is not None:
                w = self.selected_times_min.widget
                w.setParent(None)
                del w
        elif min_max == "<":
            if self.selected_times_max.timestamp is not None:
                w = self.selected_times_max.widget
                w.setParent(None)
                del w

        tag_name = f"{min_max} {date.strftime('%Y-%m-%d')}"
        tag_button = QPushButton(tag_name)
        tag_button.setObjectName("Time")
        tag_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        tag_button.clicked.connect(lambda flag, t=tag_button: self.remove_tag_button(t))
        if min_max == ">":
            self.selected_times_min = SelectedTime(date, tag_button)
        elif min_max == "<":
            self.selected_times_max = SelectedTime(date, tag_button)

        self.addWidget(tag_button, 0)

        self.main.update_items()

    def add_area_tag(self):
        tag_name = "Area"
        tag_button = QPushButton(tag_name)
        tag_button.setObjectName("Area")
        tag_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        tag_button.clicked.connect(lambda flag, t=tag_button: self.remove_tag_button(t))

        self.addWidget(tag_button, 0)
        self.selected_area.widget = tag_button

        self.main.update_items()

    def get_filters(self) -> Filters:
        return Filters(
            tags=[x.name for x in self.selected_tags],
            start_date=self.selected_times_min.timestamp,
            end_date=self.selected_times_max.timestamp,
            min_longitude=self.selected_area.min_longitude,
            max_longitude=self.selected_area.max_longitude,
            min_latitude=self.selected_area.min_latitude,
            max_latitude=self.selected_area.max_latitude,
            wrong_dir=self.bool["Wrong dir"].value,
            no_time=self.bool["No Time"].value,
            no_gps=self.bool["No GPS"].value,
            directories=[self.main.config.photos, self.main.config.videos],
        )

    def remove_tag_button(self, w):
        # so that we can also pass empty time selections in here
        if w is None:
            return

        found = False
        for i, tmp in enumerate(self.selected_tags):
            if w == tmp.widget:
                found = True
                break
        if found:
            w.setParent(None)
            del self.selected_tags[i]
        else:
            if w == self.selected_times_min.widget:
                w.setParent(None)
                self.selected_times_min = SelectedTime()
                del w
            elif w == self.selected_times_max.widget:
                w.setParent(None)
                self.selected_times_max = SelectedTime()
                del w
            elif w == self.selected_area.widget:
                w.setParent(None)
                self.selected_area = SelectedArea()
                del w
            else:
                for key, value in self.bool.items():
                    if w == value.widget:
                        w.setParent(None)
                        self.bool[key].value = False

        self.main.update_items()
