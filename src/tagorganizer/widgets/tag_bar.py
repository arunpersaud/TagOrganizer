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

from dataclasses import dataclass, field
from datetime import datetime

from qtpy.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

RESERVED_TAGS = ["No Time", "No GPS", "Wrong dir", "Unnamed faces"]

# Condition kind -> the reserved chip that stands for it.
FLAG_CHIP_NAMES = {
    "no_time": "No Time",
    "no_gps": "No GPS",
    "wrong_dir": "Wrong dir",
    "unnamed_faces": "Unnamed faces",
}


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
class SelectedIds:
    item_ids: list[int] | None = None
    widget: QWidget | None = None


@dataclass
class Condition:
    """One filter chip, expressed as data the query layer can compose.

    Chips used to be applied straight into the query as where-clauses, which
    made them impossible to OR together - a clause that has already been applied
    cannot be combined with anything. Representing a chip as a value first is
    what lets a group of them become a disjunction.
    """

    kind: str
    value: object = None


def remove_group_members(groups, removals):
    """Drop several members from OR groups in one pass.

    ``removals`` are (group_index, member_index) pairs, and every position
    refers to ``groups`` as it was passed in. Removing them one at a time
    would shift the positions of the rest: removing a group's first member
    moves its second into slot zero, and a group that dissolves shifts every
    group after it. Doing them together makes the order irrelevant.

    Returns (groups, dissolved): the groups that remain, and the conditions
    that should go back to being ordinary chips. A group of two that loses one
    member is no longer a disjunction - "(beach)" is just "beach" - so it
    dissolves rather than lingering as a group of one.

    The removed members are discarded, not restored: removing one from the
    group is removing it from the filter. Ungrouping is the operation that
    keeps everything. Positions that do not exist are ignored.

    Nothing is mutated in place; the caller rebuilds its chips from the result.
    """
    doomed = {
        (group_index, member_index)
        for group_index, member_index in removals
        if 0 <= group_index < len(groups)
        and 0 <= member_index < len(groups[group_index])
    }

    remaining = []
    dissolved = []
    for group_index, group in enumerate(groups):
        kept = [
            condition
            for member_index, condition in enumerate(group)
            if (group_index, member_index) not in doomed
        ]
        if len(kept) >= 2:
            remaining.append(kept)
        else:
            dissolved.extend(kept)
    return remaining, dissolved


def remove_group_member(groups, group_index: int, member_index: int):
    """Drop one member from an OR group. See remove_group_members."""
    return remove_group_members(groups, [(group_index, member_index)])


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
    unnamed_faces: bool | None = False
    # The root of the tags that name people; see db._unnamed_faces.
    people_tag: str = "People"
    directories: list[Path] | None = None
    # None means "no id filter at all"; an empty list means "an empty
    # selection", which must match nothing rather than everything.
    item_ids: list[int] | None = None
    # Each inner list is OR'd together; each group is one more conjunct beside
    # the flat fields above. Filters therefore still describes a conjunction -
    # a group is simply a conjunct that happens to be a disjunction.
    groups: list[list[Condition]] = field(default_factory=list)


class TagBar(QHBoxLayout):
    def __init__(self, main):
        super().__init__()

        self.main = main

        self.selected_tags: list[SelectedTag] = []

        self.selected_times_min = SelectedTime()
        self.selected_times_max = SelectedTime()
        self.selected_area = SelectedArea()
        self.selected_ids = SelectedIds()
        self.bool = {
            "Wrong dir": SelectedBool(),
            "No Time": SelectedBool(),
            "No GPS": SelectedBool(),
            "Unnamed faces": SelectedBool(),
        }

        # Chips the user has picked out, for grouping or removal. Held here
        # rather than as a flag on each button so the set survives the buttons
        # being rebuilt, and so "what is selected" has one owner.
        self._selected_chips: list[QWidget] = []

        # Chips that have been pulled out of the flat fields and into an OR
        # group. A chip is in exactly one place: a plain conjunct, or a member
        # of one group. Being in both would AND it as well as OR it, narrowing
        # the result to the opposite of what grouping is for.
        self._groups: list[list[Condition]] = []
        self._group_widgets: list[QWidget] = []
        self._group_members: dict = {}

        # Set while a single user gesture is building several buttons, so
        # the view is redrawn once at the end instead of after each one.
        self._suppress_refresh = False

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_selected_tags)
        self.clear_button.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum
        )
        self.delete_button = QPushButton("Delete tag")
        self.delete_button.setToolTip("Remove the selected filters (or press Delete)")
        self.delete_button.clicked.connect(self.remove_selected)
        self.delete_button.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum
        )

        self.group_button = QPushButton("Group with OR")
        self.group_button.setToolTip(
            "Click chips to select them, then group them so they match with OR"
        )
        self.group_button.clicked.connect(self.group_selected)
        self.group_button.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum
        )

        self.ungroup_button = QPushButton("Ungroup")
        self.ungroup_button.clicked.connect(self.ungroup_selected)
        self.ungroup_button.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum
        )

        self.addWidget(self.clear_button, 0)
        self.addWidget(self.delete_button, 0)
        self.addWidget(self.group_button, 0)
        self.addWidget(self.ungroup_button, 0)
        self.addStretch(1)

    def clear_selected_tags(self):
        self.reset()
        self.refresh()

    def reset(self):
        """Drop every chip and group without redrawing the view.

        Used when the view is about to be redrawn anyway, as after a profile
        switch; clear_selected_tags is the version that redraws.
        """
        previous = self._suppress_refresh
        self._suppress_refresh = True
        try:
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
            self.remove_tag_button(self.selected_ids.widget)
            for widget in self._group_widgets:
                widget.setParent(None)
            self._group_widgets = []
            self._group_members = {}
            self._groups = []
            # A chip deleted above can still be marked selected; keeping it
            # would let a stale widget be grouped into the next filter.
            self._selected_chips = []
        finally:
            self._suppress_refresh = previous

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
        tag_button.clicked.connect(lambda flag, t=tag_button: self.toggle_chip(t))
        self.addWidget(tag_button, 0)
        if tag_name in RESERVED_TAGS:
            self.bool[tag_name].value = True
            self.bool[tag_name].widget = tag_button
        else:
            self.selected_tags.append(SelectedTag(tag_name, tag_button))
        self.refresh()

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
        tag_button.clicked.connect(lambda flag, t=tag_button: self.toggle_chip(t))
        if min_max == ">":
            self.selected_times_min = SelectedTime(date, tag_button)
        elif min_max == "<":
            self.selected_times_max = SelectedTime(date, tag_button)

        self.addWidget(tag_button, 0)

        self.refresh()

    def set_time_range(self, start, end):
        """Set both ends of the time filter in one go.

        add_time_tag refreshes the view itself, so setting the two bounds with
        two calls costs two full redraws of the grid, timeline and map - plainly
        visible on a large library. Dragging a span on the timeline is one
        gesture and should cost one refresh, so the buttons are built with the
        refresh suppressed and the view is updated once at the end.

        The bounds are ordered here, because a drag from right to left means the
        same span as one from left to right.
        """
        if start > end:
            start, end = end, start

        self._suppress_refresh = True
        try:
            self.add_time_tag(start, ">")
            self.add_time_tag(end, "<")
        finally:
            self._suppress_refresh = False

        self.main.update_items()

    def clear_time_range(self):
        """Drop both ends of the time filter, refreshing once."""
        self._suppress_refresh = True
        try:
            self.remove_tag_button(self.selected_times_min.widget)
            self.remove_tag_button(self.selected_times_max.widget)
        finally:
            self._suppress_refresh = False

        self.main.update_items()

    def add_area_tag(self):
        """Show the drawn area as a chip, replacing any area chip already shown.

        The old chip is dropped from the bar without touching the stored
        bounds: map.py sets the new bounds before calling this, and clearing
        them here would throw the new area away.
        """
        self._discard_chip(self.selected_area.widget)
        tag_name = "Area"
        tag_button = QPushButton(tag_name)
        tag_button.setObjectName("Area")
        tag_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        tag_button.clicked.connect(lambda flag, t=tag_button: self.toggle_chip(t))

        self.addWidget(tag_button, 0)
        self.selected_area.widget = tag_button

        self.refresh()

    def _discard_chip(self, widget):
        """Take a chip off the bar, leaving the state it stood for alone."""
        if widget is None:
            return
        if widget in self._selected_chips:
            self._selected_chips.remove(widget)
        widget.setParent(None)

    def add_selection_tag(self, item_ids: list[int]):
        """Show the frozen selection as a removable filter button.

        The ids are copied here rather than read live from the selection, so
        deselecting inside the view does not make photos disappear from it.
        """
        self.remove_tag_button(self.selected_ids.widget)

        tag_button = QPushButton(f"Selection ({len(item_ids)})")
        tag_button.setObjectName("Selection")
        tag_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        tag_button.clicked.connect(lambda flag, t=tag_button: self.toggle_chip(t))

        self.addWidget(tag_button, 0)
        self.selected_ids = SelectedIds(list(item_ids), tag_button)

        self.refresh()

    def _condition_for(self, widget):
        """The Condition a chip stands for, or None if it is not one."""
        for entry in self.selected_tags:
            if entry.widget is widget:
                return Condition("tag", entry.name)
        if widget is self.selected_area.widget:
            return Condition(
                "area",
                {
                    "min_longitude": self.selected_area.min_longitude,
                    "max_longitude": self.selected_area.max_longitude,
                    "min_latitude": self.selected_area.min_latitude,
                    "max_latitude": self.selected_area.max_latitude,
                },
            )
        if widget is self.selected_times_min.widget:
            return Condition("start_date", self.selected_times_min.timestamp)
        if widget is self.selected_times_max.widget:
            return Condition("end_date", self.selected_times_max.timestamp)
        if widget is self.selected_ids.widget:
            return Condition("item_ids", self.selected_ids.item_ids)
        for kind, name in FLAG_CHIP_NAMES.items():
            if widget is self.bool[name].widget:
                return Condition(kind, self._flag_value(kind))
        return None

    def _flag_value(self, kind):
        """What the query layer needs to evaluate a flag chip inside a group.

        The flat fields carry these separately (Filters.directories,
        Filters.people_tag); a condition has only its value.
        """
        config = self.main.config
        if kind == "wrong_dir":
            return [config.photos, config.videos]
        if kind == "unnamed_faces":
            return config.get_people_tag()
        return True

    def group_selected(self):
        """Combine the selected chips into one OR group.

        Fewer than two chips is not a disjunction, so it is left alone rather
        than creating a group that means nothing.
        """
        chips = list(self._selected_chips)
        if len(chips) < 2:
            return

        conditions = [c for c in (self._condition_for(w) for w in chips) if c]
        if len(conditions) < 2:
            return

        self._suppress_refresh = True
        try:
            for widget in chips:
                self.remove_tag_button(widget)
        finally:
            self._suppress_refresh = False

        self._groups.append(conditions)
        self._rebuild_groups()
        self.main.update_items()

    def ungroup_selected(self):
        """Break the groups the selected chips belong to back into loose chips.

        Selecting any member selects its group: with members drawn as their
        own chips there is no separate group chip to click, and requiring the
        user to select all of them would make ungrouping harder than grouping.

        Only the groups actually touched: ungrouping everything at once would
        undo grouping the user deliberately kept, and there is no undo.
        """
        touched = sorted(
            {
                self._group_members[widget][0]
                for widget in self._selected_chips
                if widget in self._group_members
            }
        )
        if not touched:
            return

        freed = [self._groups[index] for index in touched]
        self._suppress_refresh = True
        try:
            self._groups = [
                group
                for index, group in enumerate(self._groups)
                if index not in touched
            ]
            self._rebuild_groups()
            for group in freed:
                for condition in group:
                    self._restore_condition(condition)
        finally:
            self._suppress_refresh = False
        self.main.update_items()

    def _add_group_widgets(self, conditions, group_index):
        """Show a group as its own chips inside brackets: ( beach or surf ).

        The members stay as ordinary chips rather than collapsing into one
        "(a or b)" button, so each can be selected and deleted with the same
        click-then-Delete that every other chip uses. Only the brackets and
        the "or" between them are decoration.
        """
        self._group_widgets.append(self._decoration("("))
        for position, condition in enumerate(conditions):
            if position:
                self._group_widgets.append(self._decoration("or"))
            button = QPushButton(self._condition_label(condition))
            button.setObjectName("GroupMember")
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
            button.clicked.connect(lambda flag, b=button: self.toggle_chip(b))
            self.addWidget(button, 0)
            self._group_widgets.append(button)
            self._group_members[button] = (group_index, position)
        self._group_widgets.append(self._decoration(")"))

    def _decoration(self, text):
        """A bracket or an 'or': visible, but not something to click."""
        label = QLabel(text)
        label.setObjectName("GroupDecoration")
        self.addWidget(label, 0)
        return label

    def _rebuild_groups(self):
        """Redraw every group from self._groups."""
        for widget in self._group_widgets:
            if self.is_chip_selected(widget):
                self.toggle_chip(widget)
            widget.setParent(None)
        self._group_widgets = []
        self._group_members = {}
        for index, group in enumerate(self._groups):
            self._add_group_widgets(group, index)

    def group_of(self, widget):
        """Which (group, member) a chip belongs to, or None if it is loose."""
        return self._group_members.get(widget)

    def remove_group_member(self, group_index: int, member_index: int):
        """Drop one member, dissolving the group if one is left."""
        self._suppress_refresh = True
        try:
            self._remove_members([(group_index, member_index)])
        finally:
            self._suppress_refresh = False
        self.main.update_items()

    def _remove_members(self, removals):
        """Remove members by position, all at once, restoring dissolved groups.

        The caller holds _suppress_refresh and redraws once afterwards.
        """
        remaining, dissolved = remove_group_members(self._groups, removals)
        self._groups = remaining
        self._rebuild_groups()
        for condition in dissolved:
            self._restore_condition(condition)

    def forget_tag(self, name: str) -> bool:
        """Remove every chip, loose or grouped, that filters on this tag.

        Returns whether anything went. The caller redraws: this is used when
        the tag itself was deleted, and that redraw is the caller's to do.
        """
        loose = [entry.widget for entry in self.selected_tags if entry.name == name]
        removals = [
            (group_index, member_index)
            for group_index, group in enumerate(self._groups)
            for member_index, condition in enumerate(group)
            if condition.kind == "tag" and condition.value == name
        ]
        if not loose and not removals:
            return False

        self._suppress_refresh = True
        try:
            for widget in loose:
                self.remove_tag_button(widget)
            if removals:
                self._remove_members(removals)
        finally:
            self._suppress_refresh = False
        return True

    @staticmethod
    def _condition_label(condition) -> str:
        if condition.kind == "tag":
            return str(condition.value)
        return {
            "area": "Area",
            "start_date": "after",
            "end_date": "before",
            "no_time": "No Time",
            "no_gps": "No GPS",
            "wrong_dir": "Wrong dir",
            "unnamed_faces": "Unnamed faces",
            "item_ids": "Selection",
        }.get(condition.kind, condition.kind)

    def _restore_condition(self, condition):
        """Put a condition back as an ordinary chip."""
        if condition.kind == "tag":
            self.add_tag(condition.value)
        elif condition.kind in FLAG_CHIP_NAMES:
            self.add_tag(FLAG_CHIP_NAMES[condition.kind])
        elif condition.kind == "area":
            self.selected_area.set_values(**condition.value)
            self.add_area_tag()
        elif condition.kind == "start_date":
            self.add_time_tag(condition.value, ">")
        elif condition.kind == "end_date":
            self.add_time_tag(condition.value, "<")
        elif condition.kind == "item_ids":
            self.add_selection_tag(condition.value)

    SELECTED_STYLE = "QPushButton { border: 2px solid palette(highlight); }"

    def toggle_chip(self, widget):
        """Pick a chip out, or put it back.

        Clicking a chip used to remove it outright. It now selects, because
        grouping chips into an OR needs a way to name several of them; removal
        moved to the Delete key.
        """
        if widget is None:
            return
        if widget in self._selected_chips:
            self._selected_chips.remove(widget)
            widget.setStyleSheet("")
        else:
            self._selected_chips.append(widget)
            widget.setStyleSheet(self.SELECTED_STYLE)

    def is_chip_selected(self, widget) -> bool:
        return widget in self._selected_chips

    def selected_chips(self) -> list:
        return list(self._selected_chips)

    def remove_selected(self):
        """Delete every selected chip, refreshing once.

        A no-op when nothing is selected: Delete has to be inert then, or a
        stray keypress would silently drop the user's filters.
        """
        if not self._selected_chips:
            return

        chips = list(self._selected_chips)

        # A chip inside a group is removed from the group rather than from the
        # bar: the group has to shrink, and dissolve if only one member is
        # left. All the positions are taken before anything moves, so removing
        # one member cannot shift the position of another.
        removals = [self._group_members[w] for w in chips if w in self._group_members]
        loose = [w for w in chips if w not in self._group_members]

        self._suppress_refresh = True
        try:
            for widget in loose:
                self.remove_tag_button(widget)
            if removals:
                self._remove_members(removals)
        finally:
            self._suppress_refresh = False

        self.main.update_items()

    def refresh(self):
        """Redraw the view, unless a multi-button gesture is in progress."""
        if self._suppress_refresh:
            return
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
            unnamed_faces=self.bool["Unnamed faces"].value,
            people_tag=self.main.config.get_people_tag(),
            directories=[self.main.config.photos, self.main.config.videos],
            item_ids=self.selected_ids.item_ids,
            groups=[list(g) for g in self._groups],
        )

    def remove_tag_button(self, w):
        # so that we can also pass empty time selections in here
        if w is None:
            return

        # Drop it from the selection too, or the set accumulates widgets that
        # no longer exist and Delete appears to do nothing.
        if w in self._selected_chips:
            self._selected_chips.remove(w)

        index = next(
            (i for i, tmp in enumerate(self.selected_tags) if w == tmp.widget), None
        )
        if index is not None:
            w.setParent(None)
            del self.selected_tags[index]
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
            elif w == self.selected_ids.widget:
                w.setParent(None)
                self.selected_ids = SelectedIds()
                del w
            else:
                for key, value in self.bool.items():
                    if w == value.widget:
                        w.setParent(None)
                        self.bool[key].value = False

        self.refresh()
