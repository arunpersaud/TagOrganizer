"""Real MainWindow fixtures, shared by every test that needs a built window.

Importing this module imports QtWebEngine, which has to happen before any
QApplication exists: constructing the map widget aborts the process otherwise.
Test modules import it at collection time, which is before any test runs.

Every window is built against a throwaway config. ConfigManager opens the real
library when it is not given one, which is not something a test may do.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Imported at module scope, and before qtpy.QtWidgets: QtWebEngine has to be
# loaded before any QApplication exists, or constructing the map widget aborts
# the process. Doing it inside a fixture is already too late.
pytest.importorskip("tagorganizer.widgets.map")


@pytest.fixture
def database_opens(monkeypatch):
    """Every database path the code under test asks to open, in order.

    Each call still goes through to the real set_engine. Recording is what lets
    a test see a database that was opened on the way to the one it asked for.
    """
    from tagorganizer import db

    opened = []
    real = db.set_engine

    def record(path):
        opened.append(str(path))
        real(path)

    monkeypatch.setattr(db, "set_engine", record)
    return opened


@pytest.fixture
def window_for(qapp, tmp_path, monkeypatch, database_opens):
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
            # The preloader fires every 100 ms for as long as the window lives.
            # Left running, it calls into whichever database is open when some
            # later test pumps events, and an unhandled error there aborts Qt.
            window.grid.preloader.stop()
            window.tasks.shutdown()
            window.close()
        db.engine = previous


def menu_titles(window):
    from qtpy.QtWidgets import QMenu

    return [
        menu.title() for menu in window.menu_bar.findChildren(QMenu) if menu.title()
    ]
