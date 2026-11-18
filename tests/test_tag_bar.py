"""Behavioural tests for the tag bar's filter buttons.

TagBar builds real QPushButtons, so it needs a QApplication; guarded the same
way as the other Qt-touching test modules.
"""

import os
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _DummyConfig:
    photos = Path("/photos")
    videos = Path("/videos")

    def get_people_tag(self):
        return "Family"


class _DummyMain:
    """Counts refreshes, because how many happen is the point of one test."""

    def __init__(self):
        self.config = _DummyConfig()
        self.update_items_calls = 0

    def update_items(self):
        self.update_items_calls += 1


def _tag_bar():
    from tagorganizer.widgets.tag_bar import TagBar

    return TagBar(_DummyMain())


class TestSetTimeRange:
    def test_sets_both_bounds(self, qapp):
        bar = _tag_bar()
        bar.set_time_range(date(2024, 1, 1), date(2024, 6, 30))

        filters = bar.get_filters()
        assert filters.start_date == date(2024, 1, 1)
        assert filters.end_date == date(2024, 6, 30)

    def test_refreshes_the_view_only_once(self, qapp):
        """Dragging a range must not redraw the whole library twice.

        add_time_tag calls update_items itself, so setting the two bounds with
        two calls costs two full refreshes - visible on a large library.
        """
        bar = _tag_bar()
        bar.main.update_items_calls = 0
        bar.set_time_range(date(2024, 1, 1), date(2024, 6, 30))

        assert bar.main.update_items_calls == 1

    def test_replaces_a_previous_range_rather_than_stacking(self, qapp):
        bar = _tag_bar()
        bar.set_time_range(date(2024, 1, 1), date(2024, 6, 30))
        bar.set_time_range(date(2020, 3, 1), date(2020, 4, 1))

        filters = bar.get_filters()
        assert filters.start_date == date(2020, 3, 1)
        assert filters.end_date == date(2020, 4, 1)

    def test_orders_the_bounds(self, qapp):
        """A drag right-to-left still means the same span."""
        bar = _tag_bar()
        bar.set_time_range(date(2024, 6, 30), date(2024, 1, 1))

        filters = bar.get_filters()
        assert filters.start_date == date(2024, 1, 1)
        assert filters.end_date == date(2024, 6, 30)


class TestClearTimeRange:
    def test_removes_both_bounds(self, qapp):
        bar = _tag_bar()
        bar.set_time_range(date(2024, 1, 1), date(2024, 6, 30))
        bar.clear_time_range()

        filters = bar.get_filters()
        assert filters.start_date is None
        assert filters.end_date is None

    def test_is_quiet_when_no_range_is_set(self, qapp):
        bar = _tag_bar()
        bar.clear_time_range()
        assert bar.get_filters().start_date is None


class TestChipSelection:
    def test_clicking_a_chip_selects_it_rather_than_removing_it(self, qapp):
        """Click used to remove. It now selects, so chips can be grouped."""
        bar = _tag_bar()
        bar.add_tag("Holiday")
        chip = bar.selected_tags[0].widget

        bar.toggle_chip(chip)

        assert bar.is_chip_selected(chip) is True
        assert "Holiday" in bar.get_filters().tags, "the filter must still apply"

    def test_clicking_again_deselects(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Holiday")
        chip = bar.selected_tags[0].widget

        bar.toggle_chip(chip)
        bar.toggle_chip(chip)

        assert bar.is_chip_selected(chip) is False

    def test_remove_selected_drops_only_the_selected_chips(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Holiday")
        bar.add_tag("Beach")
        bar.toggle_chip(bar.selected_tags[0].widget)

        bar.remove_selected()

        assert bar.get_filters().tags == ["Beach"]

    def test_remove_selected_refreshes_once(self, qapp):
        """Removing several chips is one gesture and should cost one redraw."""
        bar = _tag_bar()
        bar.add_tag("Holiday")
        bar.add_tag("Beach")
        for entry in list(bar.selected_tags):
            bar.toggle_chip(entry.widget)
        bar.main.update_items_calls = 0

        bar.remove_selected()

        assert bar.main.update_items_calls == 1

    def test_remove_selected_with_nothing_selected_does_nothing(self, qapp):
        """Delete must be inert unless chips are selected.

        Otherwise a stray Delete keypress would silently drop filters, and the
        key is close enough to the photo-deleting workflow to be alarming.
        """
        bar = _tag_bar()
        bar.add_tag("Holiday")
        bar.main.update_items_calls = 0

        bar.remove_selected()

        assert bar.get_filters().tags == ["Holiday"]
        assert bar.main.update_items_calls == 0

    def test_selection_survives_an_unrelated_refresh(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Holiday")
        chip = bar.selected_tags[0].widget
        bar.toggle_chip(chip)

        bar.refresh()

        assert bar.is_chip_selected(chip) is True

    def test_removing_a_chip_forgets_its_selection(self, qapp):
        """A removed chip must not linger in the selection set."""
        bar = _tag_bar()
        bar.add_tag("Holiday")
        chip = bar.selected_tags[0].widget
        bar.toggle_chip(chip)

        bar.remove_selected()

        assert bar.selected_chips() == []


class TestClickWiring:
    def test_clicking_the_button_selects_rather_than_removes(self, qapp):
        """Exercise the real click, not just the method it should reach.

        Testing toggle_chip directly proves the method works but says nothing
        about what the button is wired to - the connection could still call
        remove_tag_button and every other test would pass.
        """
        bar = _tag_bar()
        bar.add_tag("Holiday")
        chip = bar.selected_tags[0].widget

        chip.click()

        assert bar.is_chip_selected(chip) is True
        assert bar.get_filters().tags == ["Holiday"], "clicking must not remove it"


class TestGrouping:
    def test_grouping_two_chips_produces_one_or_group(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Beach")
        bar.add_tag("Mountain")
        for entry in list(bar.selected_tags):
            bar.toggle_chip(entry.widget)

        bar.group_selected()

        filters = bar.get_filters()
        assert len(filters.groups) == 1
        assert {c.value for c in filters.groups[0]} == {"Beach", "Mountain"}

    def test_grouped_chips_leave_the_flat_fields(self, qapp):
        """A chip is either a plain conjunct or a member of a group, not both.

        Leaving it in both would AND it as well as OR it, quietly narrowing the
        result to the opposite of what grouping is for.
        """
        bar = _tag_bar()
        bar.add_tag("Beach")
        bar.add_tag("Mountain")
        bar.add_tag("2024")
        for entry in list(bar.selected_tags)[:2]:
            bar.toggle_chip(entry.widget)

        bar.group_selected()

        assert bar.get_filters().tags == ["2024"]

    def test_grouping_fewer_than_two_chips_does_nothing(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Beach")
        bar.toggle_chip(bar.selected_tags[0].widget)

        bar.group_selected()

        assert bar.get_filters().groups == []
        assert bar.get_filters().tags == ["Beach"]

    def test_ungrouping_returns_chips_to_the_flat_fields(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Beach")
        bar.add_tag("Mountain")
        for entry in list(bar.selected_tags):
            bar.toggle_chip(entry.widget)
        bar.group_selected()

        # Ungrouping acts on the group a selected chip belongs to, so pick
        # any one member.
        bar.toggle_chip(next(iter(bar._group_members)))
        bar.ungroup_selected()

        filters = bar.get_filters()
        assert filters.groups == []
        assert sorted(filters.tags) == ["Beach", "Mountain"]

    def test_a_mixed_group_survives_the_round_trip(self, qapp):
        """A tag and a map area in one group is the point of the feature."""
        from datetime import date

        bar = _tag_bar()
        bar.add_tag("Beach")
        bar.selected_area.set_values(
            min_longitude=0.0, max_longitude=1.0, min_latitude=2.0, max_latitude=3.0
        )
        bar.add_area_tag()
        bar.toggle_chip(bar.selected_tags[0].widget)
        bar.toggle_chip(bar.selected_area.widget)

        bar.group_selected()

        filters = bar.get_filters()
        assert len(filters.groups) == 1
        assert {c.kind for c in filters.groups[0]} == {"tag", "area"}
        assert filters.min_latitude is None, "the area moved into the group"
        del date


class TestGroupIsVisible:
    def test_grouping_leaves_the_members_visible_in_brackets(self, qapp):
        """A group must be visible, or filters appear to vanish.

        The members stay as their own chips inside brackets rather than
        collapsing into one, so each can still be clicked and deleted.
        """
        bar = _tag_bar()
        bar.add_tag("Beach")
        bar.add_tag("Mountain")
        for entry in list(bar.selected_tags):
            bar.toggle_chip(entry.widget)

        bar.group_selected()

        assert [w.text() for w in bar._group_widgets] == [
            "(",
            "Beach",
            "or",
            "Mountain",
            ")",
        ]

    def test_each_member_is_a_chip_of_its_own(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Beach")
        bar.add_tag("Mountain")
        for entry in list(bar.selected_tags):
            bar.toggle_chip(entry.widget)

        bar.group_selected()

        assert len(bar._group_members) == 2

    def test_ungrouping_removes_the_group_chip(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Beach")
        bar.add_tag("Mountain")
        for entry in list(bar.selected_tags):
            bar.toggle_chip(entry.widget)
        bar.group_selected()

        bar.toggle_chip(next(iter(bar._group_members)))
        bar.ungroup_selected()

        assert bar._group_widgets == []

    def test_clear_removes_groups_too(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Beach")
        bar.add_tag("Mountain")
        for entry in list(bar.selected_tags):
            bar.toggle_chip(entry.widget)
        bar.group_selected()

        bar.clear_selected_tags()

        assert bar.get_filters().groups == []
        assert bar._group_widgets == []

    def test_a_mixed_group_is_labelled_by_kind(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Beach")
        bar.selected_area.set_values(
            min_longitude=0.0, max_longitude=1.0, min_latitude=2.0, max_latitude=3.0
        )
        bar.add_area_tag()
        bar.toggle_chip(bar.selected_tags[0].widget)
        bar.toggle_chip(bar.selected_area.widget)

        bar.group_selected()

        assert [w.text() for w in bar._group_widgets] == [
            "(",
            "Beach",
            "or",
            "Area",
            ")",
        ]


class TestDeleteKeysInTheWindow:
    """Delete and Backspace are bound in the window, to the tag bar's remove.

    Sent to the real window as key presses. The delete dialog for photos must
    never open from them: with a photo highlighted it is what a wrong binding
    would reach.
    """

    @pytest.mark.parametrize("key_name", ["Key_Delete", "Key_Backspace"])
    def test_the_key_removes_the_selected_chip_and_never_asks_about_photos(
        self, window_for, monkeypatch, key_name
    ):
        from qtpy.QtCore import QEvent, Qt
        from qtpy.QtGui import QKeyEvent

        import tagorganizer.main as main_module
        from tagorganizer import db

        def no_photo_dialog(*args, **kwargs):
            raise AssertionError("the delete-photos dialog opened")

        monkeypatch.setattr(main_module, "DeleteConfirmationDialog", no_photo_dialog)
        window = window_for()
        db.add_images([str(window.config.photos / "a.jpg")])
        window.update_items()
        assert window.grid.current_item() is not None, "precondition"
        window.tag_bar.add_tag("beach")
        window.tag_bar.toggle_chip(window.tag_bar.selected_tags[0].widget)

        window.keyPressEvent(
            QKeyEvent(
                QEvent.Type.KeyPress,
                getattr(Qt.Key, key_name),
                Qt.KeyboardModifier.NoModifier,
            )
        )

        assert window.tag_bar.get_all_names() == []
        assert db.get_number_of_items() == 1, "the photo must survive the key"


class TestDeleteButton:
    def test_there_is_a_button_for_removing_selected_chips(self, qapp):
        """Not everything should require knowing a keyboard shortcut."""
        bar = _tag_bar()
        assert bar.delete_button.text() == "Delete tag"

    def test_the_button_removes_the_selected_chips(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Holiday")
        bar.add_tag("Beach")
        bar.toggle_chip(bar.selected_tags[0].widget)

        bar.delete_button.click()

        assert bar.get_filters().tags == ["Beach"]


class TestUngroupOnlySelected:
    def _two_groups(self, bar):
        for name in ("A", "B", "C", "D"):
            bar.add_tag(name)
        chips = [entry.widget for entry in bar.selected_tags]
        bar.toggle_chip(chips[0])
        bar.toggle_chip(chips[1])
        bar.group_selected()
        remaining = [entry.widget for entry in bar.selected_tags]
        bar.toggle_chip(remaining[0])
        bar.toggle_chip(remaining[1])
        bar.group_selected()

    def test_ungroups_only_the_selected_group(self, qapp):
        """Ungrouping everything at once would undo work the user kept."""
        bar = _tag_bar()
        self._two_groups(bar)
        assert len(bar.get_filters().groups) == 2

        # Selecting any member selects its group: there is no separate group
        # chip to click any more.
        first_member = next(
            w for w, (group, _) in bar._group_members.items() if group == 0
        )
        bar.toggle_chip(first_member)
        bar.ungroup_selected()

        assert len(bar.get_filters().groups) == 1
        assert len(bar._group_members) == 2

    def test_ungroup_with_nothing_selected_does_nothing(self, qapp):
        bar = _tag_bar()
        self._two_groups(bar)

        bar.ungroup_selected()

        assert len(bar.get_filters().groups) == 2


class TestRemovingOneGroupMember:
    """Groups could only be made and unmade whole.

    Getting "(beach or surf or lake)" down to "(beach or surf)" meant
    ungrouping and rebuilding it, which is tedious enough that a user
    reasonably just leaves the wrong filter in place.
    """

    def conditions(self, *names):
        from tagorganizer.widgets.tag_bar import Condition

        return [Condition(kind="tag", value=name) for name in names]

    def test_a_member_is_removed_and_the_group_survives(self):
        from tagorganizer.widgets.tag_bar import remove_group_member

        groups = [self.conditions("beach", "surf", "lake")]
        remaining, dissolved = remove_group_member(groups, 0, 1)

        assert [c.value for c in remaining[0]] == ["beach", "lake"]
        assert dissolved == []

    def test_a_group_of_two_dissolves_into_an_ordinary_chip(self):
        """(beach) is not a disjunction, it is just beach."""
        from tagorganizer.widgets.tag_bar import remove_group_member

        groups = [self.conditions("beach", "surf")]
        remaining, dissolved = remove_group_member(groups, 0, 1)

        assert remaining == []
        assert [c.value for c in dissolved] == ["beach"]

    def test_the_removed_member_does_not_come_back_as_a_chip(self):
        """Removing it from the group means removing it from the filter."""
        from tagorganizer.widgets.tag_bar import remove_group_member

        groups = [self.conditions("beach", "surf")]
        _, dissolved = remove_group_member(groups, 0, 0)

        assert [c.value for c in dissolved] == ["surf"]

    def test_other_groups_are_untouched(self):
        from tagorganizer.widgets.tag_bar import remove_group_member

        groups = [self.conditions("a", "b", "c"), self.conditions("x", "y", "z")]
        remaining, _ = remove_group_member(groups, 0, 0)

        assert [c.value for c in remaining[1]] == ["x", "y", "z"]

    def test_removing_from_the_second_group_leaves_the_first_alone(self):
        from tagorganizer.widgets.tag_bar import remove_group_member

        groups = [self.conditions("a", "b", "c"), self.conditions("x", "y", "z")]
        remaining, _ = remove_group_member(groups, 1, 2)

        assert [c.value for c in remaining[0]] == ["a", "b", "c"]
        assert [c.value for c in remaining[1]] == ["x", "y"]

    def test_an_out_of_range_group_changes_nothing(self):
        from tagorganizer.widgets.tag_bar import remove_group_member

        groups = [self.conditions("a", "b")]
        remaining, dissolved = remove_group_member(groups, 5, 0)

        assert [c.value for c in remaining[0]] == ["a", "b"]
        assert dissolved == []

    def test_an_out_of_range_member_changes_nothing(self):
        from tagorganizer.widgets.tag_bar import remove_group_member

        groups = [self.conditions("a", "b")]
        remaining, dissolved = remove_group_member(groups, 0, 9)

        assert [c.value for c in remaining[0]] == ["a", "b"]
        assert dissolved == []

    def test_the_original_list_is_not_mutated(self):
        """The caller rebuilds its widgets from the result."""
        from tagorganizer.widgets.tag_bar import remove_group_member

        groups = [self.conditions("a", "b", "c")]
        remove_group_member(groups, 0, 0)

        assert len(groups[0]) == 3


class TestDeletingAMemberChip:
    """The point of drawing members as their own chips: Delete just works.

    Getting "(beach or surf or lake)" down to "(beach or surf)" no longer
    means ungrouping and rebuilding it.
    """

    def _group_of(self, bar, *names):
        for name in names:
            bar.add_tag(name)
        for entry in list(bar.selected_tags):
            bar.toggle_chip(entry.widget)
        bar.group_selected()

    def member(self, bar, label):
        return next(w for w in bar._group_members if w.text() == label)

    def test_deleting_one_member_shrinks_the_group(self, qapp):
        bar = _tag_bar()
        self._group_of(bar, "beach", "surf", "lake")

        bar.toggle_chip(self.member(bar, "surf"))
        bar.remove_selected()

        assert [c.value for c in bar.get_filters().groups[0]] == ["beach", "lake"]

    def test_the_group_still_shows_its_remaining_members(self, qapp):
        bar = _tag_bar()
        self._group_of(bar, "beach", "surf", "lake")

        bar.toggle_chip(self.member(bar, "surf"))
        bar.remove_selected()

        assert [w.text() for w in bar._group_widgets] == [
            "(",
            "beach",
            "or",
            "lake",
            ")",
        ]

    def test_deleting_down_to_one_dissolves_the_group(self, qapp):
        """(beach) is not a disjunction, it is just beach."""
        bar = _tag_bar()
        self._group_of(bar, "beach", "surf")

        bar.toggle_chip(self.member(bar, "surf"))
        bar.remove_selected()

        filters = bar.get_filters()
        assert filters.groups == []
        assert filters.tags == ["beach"]

    def test_deleting_two_members_at_once(self, qapp):
        """Removing one must not shift the position of the other."""
        bar = _tag_bar()
        self._group_of(bar, "a", "b", "c", "d")

        bar.toggle_chip(self.member(bar, "a"))
        bar.toggle_chip(self.member(bar, "c"))
        bar.remove_selected()

        assert [c.value for c in bar.get_filters().groups[0]] == ["b", "d"]

    def test_a_loose_chip_beside_a_group_still_deletes(self, qapp):
        bar = _tag_bar()
        self._group_of(bar, "beach", "surf")
        bar.add_tag("loose")

        bar.toggle_chip(bar.selected_tags[0].widget)
        bar.remove_selected()

        assert bar.get_filters().tags in (None, [])
        assert len(bar.get_filters().groups) == 1


class TestRemovingSeveralMembersAtOnce:
    """Removing two members of one group used to shift the other group's slots.

    "(a or b) (c or d)" with a and b deleted came out as "a and d": the first
    removal dissolved the group, and the second then hit the next group's
    member at the same position.
    """

    def _groups(self, bar, *groups):
        for names in groups:
            for name in names:
                bar.add_tag(name)
            for entry in list(bar.selected_tags):
                if entry.name in names:
                    bar.toggle_chip(entry.widget)
            bar.group_selected()

    def _member(self, bar, label):
        return next(w for w in bar._group_members if w.text() == label)

    def test_two_members_of_one_group_leave_the_other_group_intact(self, qapp):
        bar = _tag_bar()
        self._groups(bar, ["a", "b"], ["c", "d"])

        bar.toggle_chip(self._member(bar, "a"))
        bar.toggle_chip(self._member(bar, "b"))
        bar.remove_selected()

        filters = bar.get_filters()
        assert [[c.value for c in g] for g in filters.groups] == [["c", "d"]]
        assert filters.tags in (None, [])

    def test_a_dissolved_group_restores_its_survivor_and_spares_the_rest(self, qapp):
        bar = _tag_bar()
        self._groups(bar, ["a", "b", "c"], ["d", "e"])

        bar.toggle_chip(self._member(bar, "a"))
        bar.toggle_chip(self._member(bar, "b"))
        bar.toggle_chip(self._member(bar, "d"))
        bar.remove_selected()

        filters = bar.get_filters()
        # Each group is left with one member, so each dissolves into a chip.
        assert filters.groups == []
        assert set(filters.tags) == {"c", "e"}


class TestFlagChipsSurviveUngrouping:
    """No GPS, No Time and Wrong dir were dropped when their group was broken up."""

    def _flag_into_group(self, bar, flag):
        bar.add_tag(flag)
        bar.add_tag("beach")
        bar.toggle_chip(bar.bool[flag].widget)
        bar.toggle_chip(next(e.widget for e in bar.selected_tags if e.name == "beach"))
        bar.group_selected()

    def test_ungrouping_restores_no_gps(self, qapp):
        bar = _tag_bar()
        self._flag_into_group(bar, "No GPS")

        bar.toggle_chip(next(w for w in bar._group_members if w.text() == "beach"))
        bar.ungroup_selected()

        assert bar.get_filters().no_gps is True

    def test_ungrouping_restores_no_time(self, qapp):
        bar = _tag_bar()
        self._flag_into_group(bar, "No Time")

        bar.toggle_chip(next(w for w in bar._group_members if w.text() == "beach"))
        bar.ungroup_selected()

        assert bar.get_filters().no_time is True

    def test_a_flag_left_alone_by_a_dissolving_group_comes_back(self, qapp):
        bar = _tag_bar()
        self._flag_into_group(bar, "Wrong dir")

        bar.toggle_chip(next(w for w in bar._group_members if w.text() == "beach"))
        bar.remove_selected()

        assert bar.get_filters().wrong_dir is True


class TestUnnamedFacesChip:
    def test_the_chip_sets_the_filter_with_the_configured_people_tag(self, qapp):
        bar = _tag_bar()
        bar.add_tag("Unnamed faces")

        filters = bar.get_filters()
        assert filters.unnamed_faces is True
        assert filters.people_tag == "Family"
        assert filters.tags == []

    def test_in_a_group_it_carries_the_people_tag(self, qapp):
        from tagorganizer.widgets.tag_bar import Condition

        bar = _tag_bar()
        TestFlagChipsSurviveUngrouping()._flag_into_group(bar, "Unnamed faces")

        (group,) = bar.get_filters().groups
        assert Condition("unnamed_faces", "Family") in group
        assert bar.get_filters().unnamed_faces is False
        labels = {w.text() for w in bar._group_members}
        assert "Unnamed faces" in labels

    def test_ungrouping_brings_the_chip_back(self, qapp):
        bar = _tag_bar()
        TestFlagChipsSurviveUngrouping()._flag_into_group(bar, "Unnamed faces")

        bar.toggle_chip(next(w for w in bar._group_members if w.text() == "beach"))
        bar.ungroup_selected()

        assert bar.get_filters().unnamed_faces is True


class TestWrongDirInAGroup:
    def test_its_condition_carries_the_library_folders(self, qapp):
        """The query layer needs the folders to test against. The chip used to
        hand it True, and grouping Wrong dir raised 'bool is not iterable'."""
        from tagorganizer.widgets.tag_bar import Condition

        bar = _tag_bar()
        TestFlagChipsSurviveUngrouping()._flag_into_group(bar, "Wrong dir")

        (group,) = bar.get_filters().groups
        assert Condition("wrong_dir", [Path("/photos"), Path("/videos")]) in group


class TestOneAreaChip:
    """A second area selection used to strand the first chip on the bar.

    The bar is put inside a widget here, as the main window does. Left as a
    bare layout, setParent(None) does not take a button out of it, and the
    count below would be wrong for a reason that has nothing to do with the
    app.
    """

    def _bar(self):
        from qtpy.QtWidgets import QWidget

        bar = _tag_bar()
        host = QWidget()
        host.setLayout(bar)
        self._host = host
        return bar

    def _area_chips(self, bar):
        return [
            bar.itemAt(i).widget()
            for i in range(bar.count())
            if bar.itemAt(i).widget() is not None
            and bar.itemAt(i).widget().objectName() == "Area"
        ]

    def test_a_second_area_replaces_the_first_chip(self, qapp):
        bar = self._bar()
        bar.selected_area.set_values(1.0, 2.0, 3.0, 4.0)
        bar.add_area_tag()
        bar.selected_area.set_values(5.0, 6.0, 7.0, 8.0)
        bar.add_area_tag()

        assert len(self._area_chips(bar)) == 1

    def test_the_new_bounds_are_kept_when_the_old_chip_goes(self, qapp):
        bar = self._bar()
        bar.selected_area.set_values(1.0, 2.0, 3.0, 4.0)
        bar.add_area_tag()
        bar.selected_area.set_values(5.0, 6.0, 7.0, 8.0)
        bar.add_area_tag()

        assert bar.get_filters().min_longitude == 5.0

    def test_the_remaining_chip_can_be_removed(self, qapp):
        bar = self._bar()
        bar.selected_area.set_values(1.0, 2.0, 3.0, 4.0)
        bar.add_area_tag()
        bar.selected_area.set_values(5.0, 6.0, 7.0, 8.0)
        bar.add_area_tag()

        bar.toggle_chip(bar.selected_area.widget)
        bar.remove_selected()

        assert self._area_chips(bar) == []
        assert bar.get_filters().min_longitude is None


class TestResetAndForget:
    def test_reset_forgets_selected_chips(self, qapp):
        """A chip that was selected before a profile switch must not be grouped after it."""
        bar = _tag_bar()
        bar.add_tag("beach")
        bar.toggle_chip(bar.selected_tags[0].widget)

        bar.reset()

        assert bar.selected_chips() == []

    def test_reset_does_not_redraw(self, qapp):
        bar = _tag_bar()
        bar.add_tag("beach")
        calls = bar.main.update_items_calls

        bar.reset()

        assert bar.main.update_items_calls == calls

    def test_forget_removes_a_loose_chip_and_a_grouped_member(self, qapp):
        bar = _tag_bar()
        bar.add_tag("beach")
        bar.add_tag("surf")
        bar.add_tag("lake")
        for entry in list(bar.selected_tags):
            if entry.name in ("surf", "lake"):
                bar.toggle_chip(entry.widget)
        bar.group_selected()

        assert bar.forget_tag("surf") is True
        assert bar.forget_tag("beach") is True

        # Removing surf leaves (lake) alone, which is no longer a disjunction,
        # so lake comes back as an ordinary chip.
        filters = bar.get_filters()
        assert filters.tags == ["lake"]
        assert filters.groups == []
        assert bar.forget_tag("missing") is False
