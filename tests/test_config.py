"""Tests for profile and database-name handling.

next_database_name takes an existence predicate rather than touching the disk,
so the search can be exercised directly.
"""

import configparser
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

    def test_manager_state_unchanged_when_exception_raised(self, tmp_path):
        """Manager must be coherent after ProfileNotFoundError, to allow
        keeping the old profile when a new config file is invalid."""
        from tagorganizer.config import ConfigManager

        config_file = tmp_path / "config.ini"
        config_file.write_text(
            "[work]\ndatabase = old_db\nphoto_path = .\nvideo_path = .\n"
        )

        manager = ConfigManager.__new__(ConfigManager)
        old_config = {
            "work": {"database": "old_db", "photo_path": ".", "video_path": "."}
        }
        old_db = "old_db_path"
        old_photos = "old_photos_path"
        old_videos = "old_videos_path"
        manager.config = old_config
        manager.profile = "default"
        manager.config_file = config_file
        manager.db = old_db
        manager.photos = old_photos
        manager.videos = old_videos

        with pytest.raises(ProfileNotFoundError):
            manager.read_config()
        # Manager state unchanged after exception
        assert manager.config == old_config
        assert manager.db == old_db
        assert manager.photos == old_photos
        assert manager.videos == old_videos


class TestCreateNewProfile:
    def test_create_default_profile_succeeds(self, tmp_path, monkeypatch):
        """First-run scenario: creating the 'default' profile should succeed."""
        import tagorganizer.config as config_module
        from tagorganizer.config import ConfigManager

        # Sandbox all filesystem lookups to tmp_path
        data_dir = tmp_path / "data"
        config_file = tmp_path / "config.ini"
        photo_dir = tmp_path / "photos"
        video_dir = tmp_path / "videos"

        monkeypatch.setattr(config_module, "config_dir", tmp_path)
        monkeypatch.setattr(config_module, "default_config_file_path", config_file)
        monkeypatch.setattr(
            "platformdirs.user_data_dir", lambda *a, **kw: str(data_dir)
        )
        monkeypatch.setattr("platformdirs.user_pictures_dir", lambda: str(photo_dir))
        monkeypatch.setattr("platformdirs.user_videos_dir", lambda: str(video_dir))

        # Create manager when config doesn't exist
        manager = ConfigManager.__new__(ConfigManager)
        manager.config = configparser.ConfigParser()
        manager.profile = "default"
        manager.config_file = config_file

        # This should succeed
        manager.create_new_profile("default", data_dir, str(photo_dir), str(video_dir))

        # Config file should be written with the default profile
        assert config_file.exists()
        assert "default" in manager.config.sections()

    def test_create_DEFAULT_uppercase_is_rejected(self, tmp_path):
        """The literal [DEFAULT] section is forbidden (configparser's reserved section)."""
        from tagorganizer.config import ConfigManager
        import configparser

        config_file = tmp_path / "config.ini"
        data_dir = tmp_path / "data"

        manager = ConfigManager.__new__(ConfigManager)
        manager.config = configparser.ConfigParser()
        manager.config_file = config_file

        # Attempting to create "DEFAULT" (uppercase) should be rejected
        manager.create_new_profile("DEFAULT", data_dir, ".", ".")

        # Should not appear in config
        assert "DEFAULT" not in manager.config.sections()
        # And config file should not be written (nothing to write)
        if config_file.exists():
            text = config_file.read_text()
            assert "[DEFAULT]" not in text
