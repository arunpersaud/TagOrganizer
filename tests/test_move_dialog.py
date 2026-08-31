"""Tests for the move to profile dialog.

These tests verify:
- selectable_profiles excludes the current profile and preserves order
"""

from tagorganizer.widgets.move_dialog import selectable_profiles


class TestSelectableProfiles:
    """selectable_profiles must filter the current profile and preserve order."""

    def test_excludes_current_profile(self):
        """Current profile is not in the selectable list."""
        all_profiles = ["profile1", "profile2", "profile3"]
        current = "profile2"
        result = selectable_profiles(all_profiles, current)
        assert "profile2" not in result
        assert "profile1" in result
        assert "profile3" in result

    def test_preserves_order(self):
        """Order of other profiles is preserved."""
        all_profiles = ["a", "b", "c", "d"]
        current = "b"
        result = selectable_profiles(all_profiles, current)
        assert result == ["a", "c", "d"]

    def test_single_profile_config(self):
        """With only one profile, the list is empty."""
        all_profiles = ["only_one"]
        current = "only_one"
        result = selectable_profiles(all_profiles, current)
        assert result == []

    def test_multiple_profiles_with_first_selected(self):
        """Excluding first profile preserves the rest."""
        all_profiles = ["first", "second", "third"]
        current = "first"
        result = selectable_profiles(all_profiles, current)
        assert result == ["second", "third"]

    def test_multiple_profiles_with_last_selected(self):
        """Excluding last profile preserves the rest."""
        all_profiles = ["first", "second", "third"]
        current = "third"
        result = selectable_profiles(all_profiles, current)
        assert result == ["first", "second"]
