"""Tests for profile and database-name handling.

next_database_name takes an existence predicate rather than touching the disk,
so the search can be exercised directly.
"""

import logging
import pathlib

import pytest
from sqlalchemy import create_engine, text

from conftest import alembic_head

from tagorganizer.config import ProfileNotFoundError, next_database_name


def _stored_revision(path):
    """The migration revision a database file is stamped with."""
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as conn:
            return conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    finally:
        engine.dispose()


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
        assert pathlib.Path(error.config_file) == pathlib.Path("/tmp/config.ini")
        assert "holidays" in str(error)


class TestReadConfigRaises:
    def test_missing_profile_raises_instead_of_exiting(self, tmp_path):
        """A bad config file must not be able to kill a running GUI."""
        from tagorganizer.config import ConfigManager

        config_file = tmp_path / "config.ini"
        config_file.write_text("[work]\ndatabase = x\nphoto_path = .\nvideo_path = .\n")

        with pytest.raises(ProfileNotFoundError) as caught:
            ConfigManager(config_file=config_file, profile="default")
        assert caught.value.profile == "default"

    def test_manager_state_unchanged_when_exception_raised(self, tmp_path):
        """A refused switch must leave the manager on the profile it was showing.

        The switch goes through set_current_profile, which is where the names
        are put back. Calling read_config directly would only test that it
        raises before it assigns anything.
        """
        from tagorganizer import db
        from tagorganizer.config import ConfigManager

        config_file = tmp_path / "config.ini"
        config_file.write_text(
            f"[work]\ndatabase = {tmp_path}/work.db\n"
            f"photo_path = {tmp_path}\nvideo_path = {tmp_path}\n"
        )
        manager = ConfigManager(config_file=config_file, profile="work")
        try:
            before = (
                manager.config_file,
                manager.profile,
                manager.db,
                manager.photos,
                manager.videos,
            )
            with pytest.raises(ProfileNotFoundError):
                manager.set_current_profile("default")

            after = (
                manager.config_file,
                manager.profile,
                manager.db,
                manager.photos,
                manager.videos,
            )
            assert after == before
        finally:
            db.engine.dispose()


class TestCreateNewProfile:
    def test_create_default_profile_succeeds(self, tmp_path, monkeypatch):
        """First-run scenario: there is no config file yet.

        Building the manager has to write a default config and open the library
        it names, without the TypeError an unset config used to raise.
        """
        import tagorganizer.config as config_module
        from tagorganizer import db
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

        manager = ConfigManager(config_file=config_file, profile="default")
        try:
            assert config_file.exists()
            assert "default" in manager.config.sections()
            assert manager.db == str(data_dir / "media-default.db")
            assert (data_dir / "media-default.db").exists()
            assert manager.photos == photo_dir.resolve()
            assert manager.videos == video_dir.resolve()
        finally:
            db.engine.dispose()

    def test_create_DEFAULT_uppercase_is_rejected(self, tmp_path):
        """The literal [DEFAULT] section is forbidden (configparser's reserved section).

        The name is caught twice: configparser already counts DEFAULT as present,
        so the "already exists" check would refuse it too. The explicit guard is
        what gives the reason, so the logged message is what is asserted.
        """
        from tagorganizer import db
        from tagorganizer.config import ConfigManager

        config_file = tmp_path / "config.ini"
        config_file.write_text(
            f"[work]\ndatabase = {tmp_path}/work.db\n"
            f"photo_path = {tmp_path}\nvideo_path = {tmp_path}\n"
        )
        manager = ConfigManager(config_file=config_file, profile="work")
        # caplog is not used: opening the library above ran alembic's
        # fileConfig, which replaces the root handlers caplog attached to.
        logger = logging.getLogger("tagorganizer.config")
        messages = []
        handler = logging.Handler()
        handler.emit = lambda record: messages.append(record.getMessage())
        logger.addHandler(handler)
        try:
            before = config_file.read_text()
            manager.create_new_profile("DEFAULT", tmp_path / "data", ".", ".")
        finally:
            logger.removeHandler(handler)
            db.engine.dispose()

        assert "DEFAULT" not in manager.config.sections()
        assert config_file.read_text() == before
        assert any("'DEFAULT' is reserved" in text for text in messages), messages


class TestOpeningAnExistingLibrary:
    """A database from a previous release must still open after an upgrade.

    read_config runs create_db() before upgrade_db(). create_db() builds every
    table in the current models, so a migration that adds a table finds it
    already present and the upgrade fails - which stops the application
    starting at all, on exactly the databases that hold the user's photos.
    """

    def _library_at_previous_release(self, tmp_path, monkeypatch):
        """A database exactly as the previous release would have left it.

        Migrated up to the revision before head rather than built from today's
        models: a real user's database does not contain the tables the newest
        migration is about to add, and building it with create_all would hide
        the very mismatch this test exists to catch.
        """

        from alembic.script import ScriptDirectory
        from alembic.config import Config as AlembicConfig

        from tagorganizer import db, migrations

        db_file = tmp_path / "library.db"
        db.set_engine(str(db_file))
        monkeypatch.setenv("TAGORGANIZER_DB_URL", f"sqlite:///{db_file}")

        root = pathlib.Path(migrations.__file__).parent
        alembic_config = AlembicConfig(str(root.parent / "alembic.ini"))
        alembic_config.set_main_option("script_location", str(root))
        script = ScriptDirectory.from_config(alembic_config)
        head = script.get_current_head()
        previous = script.get_revision(head).down_revision

        migrations.upgrade_db(previous)
        db.engine.dispose()
        return db_file

    def test_an_existing_library_still_opens(self, tmp_path, monkeypatch):
        """Opening a previous release's library migrates it to head, in place.

        The database is checked before and after: it must start behind the
        newest migration, and end at it. Asserting only that nothing raised
        would pass for a library left untouched.
        """
        from tagorganizer import db
        from tagorganizer.config import ConfigManager

        db_file = self._library_at_previous_release(tmp_path, monkeypatch)
        assert _stored_revision(db_file) != alembic_head(), "precondition"

        config_file = tmp_path / "config.ini"
        config_file.write_text(
            f"[DEFAULT]\nprofile = main\n\n[main]\n"
            f"database = {db_file}\nphoto_path = {tmp_path}\n"
            f"video_path = {tmp_path}\n"
        )

        manager = ConfigManager(config_file=config_file, profile="main")
        try:
            assert manager.db == str(db_file)
            assert _stored_revision(db_file) == alembic_head()
        finally:
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


class TestAFailedLoadChangesNothing:
    """A refused profile or config must leave the working one in place."""

    def _two_profiles(self, tmp_path):
        config_file = tmp_path / "config.ini"
        config_file.write_text(
            "[DEFAULT]\nprofile = a\n\n"
            f"[a]\ndatabase = {tmp_path}/a.db\nphoto_path = {tmp_path}\n"
            f"video_path = {tmp_path}\n\n"
            f"[b]\ndatabase = {tmp_path}/b.db\nphoto_path = {tmp_path}\n"
            f"video_path = {tmp_path}\n"
        )
        return config_file

    def test_the_default_section_is_refused_as_a_profile(self, tmp_path):
        """configparser reports [DEFAULT] as present, and selecting it used to
        raise KeyError. It is not a profile, so it is a not-found error.

        The DEFAULT section here carries every setting a profile needs. Without
        the guard it would load and open shared.db. Matching the base class alone
        would also pass for a DEFAULT that merely failed validation, so the
        message is checked too.
        """
        from tagorganizer.config import ConfigManager

        config_file = tmp_path / "config.ini"
        config_file.write_text(
            f"[DEFAULT]\nprofile = a\ndatabase = {tmp_path}/shared.db\n"
            f"photo_path = {tmp_path}\nvideo_path = {tmp_path}\n\n"
            f"[a]\ndatabase = {tmp_path}/a.db\nphoto_path = {tmp_path}\n"
            f"video_path = {tmp_path}\n"
        )
        with pytest.raises(ProfileNotFoundError, match="not found") as caught:
            ConfigManager(config_file=config_file, profile="DEFAULT")
        assert type(caught.value) is ProfileNotFoundError

    def test_a_profile_missing_a_setting_is_refused_by_name(self, tmp_path):
        from tagorganizer.config import ConfigManager, InvalidProfileError

        config_file = tmp_path / "config.ini"
        config_file.write_text(f"[half]\ndatabase = {tmp_path}/h.db\nphoto_path = .\n")
        with pytest.raises(InvalidProfileError, match="video_path"):
            ConfigManager(config_file=config_file, profile="half")

    def test_an_invalid_profile_is_still_a_profile_error_for_callers(self):
        """main.py catches ProfileNotFoundError; a subclass keeps that working."""
        from tagorganizer.config import InvalidProfileError

        assert issubclass(InvalidProfileError, ProfileNotFoundError)

    def test_a_database_that_will_not_open_keeps_the_previous_profile(
        self, tmp_path, monkeypatch
    ):
        from tagorganizer import config as config_module
        from tagorganizer import db
        from tagorganizer.config import ConfigManager

        config_file = self._two_profiles(tmp_path)
        (tmp_path / "b.db").write_bytes(b"")  # exists, so the migration path runs

        manager = ConfigManager(config_file=config_file, profile="a")
        try:
            before = str(db.engine.url)

            def refuse(*args, **kwargs):
                raise RuntimeError("migration refused")

            monkeypatch.setattr(config_module, "upgrade_db", refuse)
            with pytest.raises(RuntimeError):
                manager.set_current_profile("b")

            assert manager.profile == "a"
            assert pathlib.Path(manager.db) == tmp_path / "a.db"
            assert str(db.engine.url) == before
        finally:
            db.engine.dispose()

    def test_a_refused_config_file_keeps_the_previous_one(self, tmp_path):
        from tagorganizer import db
        from tagorganizer.config import ConfigManager

        config_file = self._two_profiles(tmp_path)
        bad = tmp_path / "bad.ini"
        bad.write_text("[elsewhere]\ndatabase = x\n")
        manager = ConfigManager(config_file=config_file, profile="a")
        try:
            with pytest.raises(ProfileNotFoundError):
                manager.set_config_file(bad)
            assert manager.config_file == config_file
            assert manager.profile == "a"
        finally:
            db.engine.dispose()
