"""Building the real main window.

Nothing else in the suite constructs a MainWindow, and that gap hid three
separate bugs: a broken plugin crashed startup, an undecodable photo aborted
the process, and rebuilding the menus stacked duplicates. Each was found by
running a scratch script by hand. These tests are those scripts, kept.

Every window here is built against a throwaway config. ConfigManager opens the
real library when it is not given one, which is not something a test may do.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Imported at module scope, and before qtpy.QtWidgets: QtWebEngine has to be
# loaded before any QApplication exists, or constructing the map widget aborts
# the process. Doing it inside a fixture is already too late.
pytest.importorskip("tagorganizer.widgets.map")

from qtpy.QtWidgets import QMenu  # noqa: E402


@pytest.fixture
def window_for(qapp, tmp_path, monkeypatch):
    """Build MainWindows against a temp config, and shut them down after.

    The task worker is a real QThread; one still running when its owner is
    destroyed aborts the process.
    """
    from tagorganizer import config, db

    built = []

    def build(plugins_dir=None):
        from tagorganizer.main import MainWindow

        home = tmp_path / f"home{len(built)}"
        home.mkdir()
        config_file = home / "config.ini"
        config_file.write_text(
            f"[DEFAULT]\nprofile = default\n\n[default]\n"
            f"database = {home}/media.db\nphoto_path = {home}\n"
            f"video_path = {home}\n"
        )
        # plugin_paths() reads this, so a test's plugins never come from the
        # user's real config directory.
        monkeypatch.setattr(config, "config_dir", plugins_dir or home)
        window = MainWindow(qapp, config_file=config_file, profile="default")
        built.append(window)
        return window

    previous = db.engine
    try:
        yield build
    finally:
        for window in built:
            window.tasks.shutdown()
            window.close()
        db.engine = previous


def menu_titles(window):
    return [
        menu.title() for menu in window.menu_bar.findChildren(QMenu) if menu.title()
    ]


class TestItStarts:
    def test_the_window_opens_the_config_it_was_given(self, window_for, tmp_path):
        window = window_for()
        assert str(window.config.db).startswith(str(tmp_path))

    def test_the_real_library_is_never_opened(self, window_for, tmp_path):
        """The failure that started all of this: a script that meant to use a
        temp config migrated the user's actual photo library instead."""
        window = window_for()
        assert "Application Support/TagOrganizer/media.db" not in str(window.config.db)

    def test_the_status_bar_has_the_progress_widgets(self, window_for):
        window = window_for()
        assert window.tasks.progressbar is not None


class TestTheMenus:
    def test_the_plugin_categories_are_all_present(self, window_for):
        titles = menu_titles(window_for())
        for expected in ("Maintenance", "Files", "Reports"):
            assert expected in titles

    def test_maintenance_comes_before_the_others(self, window_for):
        """It holds the tasks reached for most often."""
        titles = menu_titles(window_for())
        assert titles.index("Maintenance") < titles.index("Files")
        assert titles.index("Files") < titles.index("Reports")

    def test_every_shipped_plugin_has_an_entry(self, window_for):
        window = window_for()
        entries = set()
        for menu in window._plugin_menus:
            entries.update(action.text() for action in menu.actions())
        assert "Update Hashes in DB" in entries
        assert "Move Files to Default Dirs" in entries

    def test_rebuilding_does_not_duplicate_the_menus(self, window_for):
        """removeAction alone leaves the menu parented to the bar, and every
        visit to Settings added another Maintenance menu."""
        window = window_for()
        before = menu_titles(window)

        window.build_plugin_menu()
        window.build_plugin_menu()

        assert menu_titles(window) == before


class TestBrokenPlugins:
    def test_a_plugin_that_fails_to_import_does_not_stop_startup(
        self, window_for, tmp_path
    ):
        """Reporting the failure used to happen before the message widget
        existed, which turned a bad plugin into a crash on launch."""
        home = tmp_path / "withbroken"
        (home / "plugins").mkdir(parents=True)
        (home / "plugins" / "bad.py").write_text("import no_such_module\n")

        window = window_for(plugins_dir=home)

        assert [b.path.name for b in window.tasks.broken] == ["bad.py"]

    def test_the_working_plugins_still_load(self, window_for, tmp_path):
        home = tmp_path / "withbroken2"
        (home / "plugins").mkdir(parents=True)
        (home / "plugins" / "bad.py").write_text("import no_such_module\n")

        window = window_for(plugins_dir=home)

        assert len(window.tasks.registry.all()) >= 8


class TestUserPlugins:
    GOOD = """
from tagorganizer.plugins import Plugin


class Mine(Plugin):
    name = "My own task"
    category = "Tags"

    def run(self, ctx):
        yield 1, 1
"""

    def test_a_plugin_dropped_in_the_directory_appears(self, window_for, tmp_path):
        home = tmp_path / "withmine"
        (home / "plugins").mkdir(parents=True)
        (home / "plugins" / "mine.py").write_text(self.GOOD)

        window = window_for(plugins_dir=home)

        assert "My own task" in {p.name for p in window.tasks.registry.all()}

    def test_it_gets_its_own_menu(self, window_for, tmp_path):
        home = tmp_path / "withmine2"
        (home / "plugins").mkdir(parents=True)
        (home / "plugins" / "mine.py").write_text(self.GOOD)

        window = window_for(plugins_dir=home)

        assert "Tags" in menu_titles(window)


class TestRunningATask:
    def test_a_task_runs_to_completion_through_the_worker(self, window_for, tmp_path):
        from sqlmodel import Session

        from tagorganizer import db
        from tagorganizer.models import Item
        from tagorganizer.scope import Scope

        window = window_for()
        for index in range(3):
            path = window.config.photos / f"{index}.jpg"
            path.write_bytes(b"data" + str(index).encode())
            with Session(db.engine) as session:
                session.add(Item(uri=str(path)))
                session.commit()

        plugin = next(
            p for p in window.tasks.registry.all() if p.name == "Update Hashes in DB"
        )
        window.tasks.run_plugin(plugin, Scope.LIBRARY)

        assert window.tasks.wait_for_idle(), "the task never finished"
        assert all(item.data_xxhash for item in db.get_all_items())


class TestLineageActions:
    def test_marking_as_derived_without_a_selection_is_reported_not_fatal(
        self, window_for
    ):
        window = window_for()
        window.mark_as_derived()

    def test_clearing_lineage_without_a_photo_is_reported_not_fatal(self, window_for):
        window = window_for()
        window.clear_lineage()
