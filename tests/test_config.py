"""Tests for profile and database-name handling.

next_database_name takes an existence predicate rather than touching the disk,
so the search can be exercised directly.
"""

import pytest

from tagorganizer.config import ProfileNotFoundError, next_database_name


class TestNextDatabaseName:
    def test_unused_plain_name_is_preferred(self):
        assert next_database_name("work", lambda name: False) == "media-work.db"

    def test_falls_back_to_the_first_numbered_name(self):
        taken = {"media-work.db"}
        assert next_database_name("work", taken.__contains__) == "media-work-00000.db"

    def test_skips_every_taken_numbered_name(self):
        """The original loop never advanced its counter and hung here forever."""
        taken = {"media-work.db", "media-work-00000.db", "media-work-00001.db"}
        assert next_database_name("work", taken.__contains__) == "media-work-00002.db"

    def test_gives_up_rather_than_looping_forever(self):
        assert next_database_name("work", lambda name: True, limit=5) is None


class TestProfileNotFoundError:
    def test_carries_the_profile_and_the_file(self):
        error = ProfileNotFoundError("holidays", "/tmp/config.ini")
        assert error.profile == "holidays"
        assert str(error.config_file) == "/tmp/config.ini"
        assert "holidays" in str(error)


class TestReadConfigRaises:
    def test_missing_profile_raises_instead_of_exiting(self, tmp_path):
        """A bad config file must not be able to kill a running GUI."""
        from tagorganizer.config import ConfigManager

        config_file = tmp_path / "config.ini"
        config_file.write_text("[work]\ndatabase = x\nphoto_path = .\nvideo_path = .\n")

        manager = ConfigManager.__new__(ConfigManager)
        manager.config = None
        manager.profile = "default"
        manager.config_file = config_file

        with pytest.raises(ProfileNotFoundError) as caught:
            manager.read_config()
        assert caught.value.profile == "default"
