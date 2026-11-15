"""Tests for profile and database-name handling.

next_database_name takes an existence predicate rather than touching the disk,
so the search can be exercised directly.
"""

import configparser
import pathlib

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
        """First-run scenario with config=None: read_config must initialize
        config before calling create_default_config."""
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

        # Simulate real first-run: manager with config=None, calling read_config
        manager = ConfigManager.__new__(ConfigManager)
        manager.config = None
        manager.profile = "default"
        manager.config_file = config_file

        # This must succeed, not raise TypeError
        manager.read_config()

        # Config file should be written with the default profile
        assert config_file.exists()
        assert "default" in manager.config.sections()
        # Manager's db, photos, videos should be initialized
        assert manager.db is not None
        assert manager.photos is not None
        assert manager.videos is not None

    def test_create_DEFAULT_uppercase_is_rejected(self, tmp_path):
        """The literal [DEFAULT] section is forbidden (configparser's reserved section)."""
        from tagorganizer.config import ConfigManager

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


class TestOpeningAnExistingLibrary:
    """A database from a previous release must still open after an upgrade.

    read_config runs create_db() before upgrade_db(). create_db() builds every
    table in the current models, so a migration that adds a table finds it
    already present and the upgrade fails - which stops the application
    starting at all, on exactly the databases that hold the user's photos.
    """

    def _library_at_previous_release(self, tmp_path):
        """A database exactly as the previous release would have left it.

        Migrated up to the revision before head rather than built from today's
        models: a real user's database does not contain the tables the newest
        migration is about to add, and building it with create_all would hide
        the very mismatch this test exists to catch.
        """
        import os

        from alembic.script import ScriptDirectory
        from alembic.config import Config as AlembicConfig

        from tagorganizer import db, migrations

        db_file = tmp_path / "library.db"
        db.set_engine(str(db_file))
        os.environ["TAGORGANIZER_DB_URL"] = f"sqlite:///{db_file}"

        root = pathlib.Path(migrations.__file__).parent
        alembic_config = AlembicConfig(str(root.parent / "alembic.ini"))
        alembic_config.set_main_option("script_location", str(root))
        script = ScriptDirectory.from_config(alembic_config)
        head = script.get_current_head()
        previous = script.get_revision(head).down_revision

        migrations.upgrade_db(previous)
        db.engine.dispose()
        return db_file

    def test_an_existing_library_still_opens(self, tmp_path):
        from tagorganizer import db
        from tagorganizer.config import ConfigManager

        db_file = self._library_at_previous_release(tmp_path)
        config_file = tmp_path / "config.ini"
        config_file.write_text(
            f"[DEFAULT]\nprofile = main\n\n[main]\n"
            f"database = {db_file}\nphoto_path = {tmp_path}\n"
            f"video_path = {tmp_path}\n"
        )

        manager = ConfigManager.__new__(ConfigManager)
        manager.config = None
        manager.profile = "main"
        manager.config_file = config_file

        manager.read_config()

        db.engine.dispose()


class TestConfigIsChosenBeforeAnyDatabaseOpens:
    """--config must not open the default library on the way to the named one.

    This is not hypothetical: a scratch script reached the real library this
    way during the lineage work, because --config was applied only after
    MainWindow had already been constructed.
    """

    def _write_config(self, tmp_path, db_file):
        config_file = tmp_path / "chosen.ini"
        config_file.write_text(
            f"[DEFAULT]\nprofile = main\n\n[main]\ndatabase = {db_file}\n"
            f"photo_path = {tmp_path}\nvideo_path = {tmp_path}\n"
        )
        return config_file

    def test_the_named_config_is_used(self, tmp_path):
        from tagorganizer import db
        from tagorganizer.config import ConfigManager

        db_file = tmp_path / "chosen.db"
        manager = ConfigManager(
            config_file=self._write_config(tmp_path, db_file), profile="main"
        )
        try:
            assert str(manager.db) == str(db_file)
            assert db_file.exists()
        finally:
            db.engine.dispose()

    def test_no_other_database_is_opened_on_the_way(self, tmp_path, monkeypatch):
        import tagorganizer.config as config_module

        opened = []
        real = config_module.db.set_engine
        monkeypatch.setattr(
            config_module.db,
            "set_engine",
            lambda path: (opened.append(str(path)), real(path))[1],
        )

        db_file = tmp_path / "chosen.db"
        config_module.ConfigManager(
            config_file=self._write_config(tmp_path, db_file), profile="main"
        )
        try:
            assert opened == [str(db_file)]
        finally:
            config_module.db.engine.dispose()


class TestDisabledPluginSetting:
    """Which plugins are switched off is global, not per profile.

    It lives in [DEFAULT], which already holds the current profile - the one
    section configparser does not report as a profile, so it cannot show up in
    the Profiles menu.
    """

    def _manager(self, tmp_path, extra=""):
        from tagorganizer.config import ConfigManager

        config_file = tmp_path / "config.ini"
        config_file.write_text(
            f"[DEFAULT]\nprofile = main\n{extra}\n\n[main]\n"
            f"database = {tmp_path}/m.db\nphoto_path = {tmp_path}\n"
            f"video_path = {tmp_path}\n"
        )
        return ConfigManager(config_file=config_file, profile="main")

    def test_nothing_is_disabled_by_default(self, tmp_path):
        from tagorganizer import db

        manager = self._manager(tmp_path)
        try:
            assert manager.get_disabled_plugins() == set()
        finally:
            db.engine.dispose()

    def test_a_stored_list_is_read_back(self, tmp_path):
        from tagorganizer import db

        manager = self._manager(tmp_path, "disabled_plugins = Alpha;Beta")
        try:
            assert manager.get_disabled_plugins() == {"Alpha", "Beta"}
        finally:
            db.engine.dispose()

    def test_names_containing_spaces_survive(self, tmp_path):
        """Plugin names are menu labels, so they have spaces in them."""
        from tagorganizer import db

        manager = self._manager(
            tmp_path, "disabled_plugins = Update Hashes in DB;Build Video Previews"
        )
        try:
            assert manager.get_disabled_plugins() == {
                "Update Hashes in DB",
                "Build Video Previews",
            }
        finally:
            db.engine.dispose()

    def test_setting_them_persists_to_the_file(self, tmp_path):
        from tagorganizer import db
        from tagorganizer.config import ConfigManager

        manager = self._manager(tmp_path)
        try:
            manager.set_disabled_plugins({"Alpha"})
            reloaded = ConfigManager(config_file=manager.config_file, profile="main")
            assert reloaded.get_disabled_plugins() == {"Alpha"}
        finally:
            db.engine.dispose()

    def test_clearing_them_persists_too(self, tmp_path):
        from tagorganizer import db
        from tagorganizer.config import ConfigManager

        manager = self._manager(tmp_path, "disabled_plugins = Alpha")
        try:
            manager.set_disabled_plugins(set())
            reloaded = ConfigManager(config_file=manager.config_file, profile="main")
            assert reloaded.get_disabled_plugins() == set()
        finally:
            db.engine.dispose()

    def test_the_profile_setting_is_not_clobbered(self, tmp_path):
        """[DEFAULT] also holds the current profile."""
        from tagorganizer import db

        manager = self._manager(tmp_path)
        try:
            manager.set_disabled_plugins({"Alpha"})
            assert "profile = main" in manager.config_file.read_text()
        finally:
            db.engine.dispose()

    def test_it_does_not_become_a_profile(self, tmp_path):
        from tagorganizer import db

        manager = self._manager(tmp_path, "disabled_plugins = Alpha")
        try:
            assert manager.get_profiles() == ["main"]
        finally:
            db.engine.dispose()


class TestProfilesSharingAPhotoFolder:
    """A photo folder's thumbnail cache is shared by every profile on it."""

    def _manager(self, tmp_path, profile):
        from tagorganizer.config import ConfigManager

        shared = tmp_path / "shared"
        other = tmp_path / "other"
        config_file = tmp_path / "config.ini"
        config_file.write_text(
            "[DEFAULT]\nprofile = a\n\n"
            f"[a]\ndatabase = {tmp_path}/a.db\nphoto_path = {shared}\n"
            f"video_path = {tmp_path}\n\n"
            f"[b]\ndatabase = {tmp_path}/b.db\nphoto_path = {shared}/\n"
            f"video_path = {tmp_path}\n\n"
            f"[c]\ndatabase = {tmp_path}/c.db\nphoto_path = {other}\n"
            f"video_path = {tmp_path}\n"
        )
        return ConfigManager(config_file=config_file, profile=profile)

    def test_a_profile_on_the_same_folder_is_reported(self, tmp_path):
        from tagorganizer import db

        manager = self._manager(tmp_path, "a")
        try:
            assert manager.other_profiles_sharing_photos() == ["b"]
        finally:
            db.engine.dispose()

    def test_a_profile_on_another_folder_is_not(self, tmp_path):
        from tagorganizer import db

        manager = self._manager(tmp_path, "c")
        try:
            assert manager.other_profiles_sharing_photos() == []
        finally:
            db.engine.dispose()

    def test_the_sharing_is_symmetric(self, tmp_path):
        from tagorganizer import db

        manager = self._manager(tmp_path, "b")
        try:
            assert manager.other_profiles_sharing_photos() == ["a"]
        finally:
            db.engine.dispose()
