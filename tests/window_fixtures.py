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

    def build(plugins_dir=None, disabled_plugins=None):
        from tagorganizer.main import MainWindow

        home = tmp_path / f"home{len(built)}"
        home.mkdir()
        config_file = home / "config.ini"
        # disabled_plugins is a global setting, so it lives in [DEFAULT].
        disabled_line = (
            f"disabled_plugins = {disabled_plugins}\n" if disabled_plugins else ""
        )
        config_file.write_text(
            f"[DEFAULT]\nprofile = default\n{disabled_line}\n[default]\n"
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


def menu_action(window, menu_title, text):
    """The action named ``text`` in the menu titled ``menu_title``, or None."""
    from qtpy.QtWidgets import QMenu

    for menu in window.menu_bar.findChildren(QMenu):
        if menu.title() == menu_title:
            for action in menu.actions():
                if action.text() == text:
                    return action
    return None


def menu_titles(window):
    from qtpy.QtWidgets import QMenu

    return [
        menu.title() for menu in window.menu_bar.findChildren(QMenu) if menu.title()
    ]


def add_profile(window, name, tmp_path):
    """Give a window a second profile, and return the path of its database.

    The database itself is not created here; moving into it or switching to it
    creates it, as it would for a user.
    """
    home = tmp_path / f"profile-{name}"
    home.mkdir(exist_ok=True)
    window.config.create_new_profile(name, home, str(home), str(home))
    return window.config.get_profile_database(name)


def answer_move_dialog(monkeypatch, profile):
    """Make the move dialog accept, choosing ``profile``, without showing it."""
    from qtpy.QtWidgets import QDialog

    from tagorganizer import main as main_module

    class AcceptingDialog:
        def __init__(self, profiles, count):
            self.profiles = profiles

        def exec_(self):
            return QDialog.DialogCode.Accepted

        def selected_profile(self):
            return profile

    monkeypatch.setattr(main_module, "MoveToProfileDialog", AcceptingDialog)


def database_uris(path):
    """The uri of every photo in the database at ``path``, read on its own engine.

    The window's own engine is left alone, so this reads the other profile the
    way the move left it.
    """
    from sqlalchemy import create_engine
    from sqlmodel import Session, select

    from tagorganizer.models import Item

    engine = create_engine(f"sqlite:///{path}")
    try:
        with Session(engine) as session:
            return sorted(item.uri for item in session.exec(select(Item)).all())
    finally:
        engine.dispose()
