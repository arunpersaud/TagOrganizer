"""The settings window: where things live, and which plugins are on.

The path list exists because "where do I put my plugin?" and "which database
am I actually looking at?" were previously unanswerable from inside the app.
"""

import os


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tagorganizer.plugins import Plugin
from tagorganizer.plugins.discovery import BrokenPlugin
from tagorganizer.widgets.settings import SettingsDialog, describe_paths


class Alpha(Plugin):
    name = "Alpha"
    description = "Does the alpha thing."
    category = "Maintenance"


class Beta(Plugin):
    name = "Beta"
    category = "Files"


class _Config:
    def __init__(self, tmp_path):
        self.config_file = tmp_path / "config.ini"
        self.db = tmp_path / "media.db"
        self.photos = tmp_path / "photos"
        self.videos = tmp_path / "videos"


class TestDescribePaths:
    """A pure function, so the list itself is testable without a window."""

    def test_it_reports_the_config_file_and_database(self, tmp_path):
        found = dict(describe_paths(_Config(tmp_path), [tmp_path / "plugins"]))
        assert found["Config file"] == tmp_path / "config.ini"
        assert found["Database"] == tmp_path / "media.db"

    def test_it_reports_the_media_directories(self, tmp_path):
        found = dict(describe_paths(_Config(tmp_path), []))
        assert found["Photos"] == tmp_path / "photos"
        assert found["Videos"] == tmp_path / "videos"

    def test_every_plugin_directory_is_listed(self, tmp_path):
        """Both the shipped one and the user's, which is the whole point."""
        directories = [tmp_path / "shipped", tmp_path / "mine"]
        labels = [label for label, _ in describe_paths(_Config(tmp_path), directories)]
        assert labels.count("Plugins") == 2

    def test_the_labels_are_in_a_stable_order(self, tmp_path):
        first = [label for label, _ in describe_paths(_Config(tmp_path), [])]
        second = [label for label, _ in describe_paths(_Config(tmp_path), [])]
        assert first == second


class TestPluginList:
    def test_every_plugin_is_listed(self, qapp, tmp_path):
        dialog = SettingsDialog(_Config(tmp_path), [Alpha(), Beta()], [], set(), [])
        assert dialog.plugin_names() == ["Alpha", "Beta"]

    def test_an_enabled_plugin_is_checked(self, qapp, tmp_path):
        dialog = SettingsDialog(_Config(tmp_path), [Alpha()], [], set(), [])
        assert dialog.disabled_plugins() == set()

    def test_a_disabled_plugin_starts_unchecked(self, qapp, tmp_path):
        dialog = SettingsDialog(_Config(tmp_path), [Alpha(), Beta()], [], {"Alpha"}, [])
        assert dialog.disabled_plugins() == {"Alpha"}

    def test_unchecking_disables_it(self, qapp, tmp_path):
        from qtpy.QtCore import Qt

        dialog = SettingsDialog(_Config(tmp_path), [Alpha(), Beta()], [], set(), [])
        dialog.plugin_list.item(0).setCheckState(Qt.Unchecked)
        assert dialog.disabled_plugins() == {"Alpha"}

    def test_checking_re_enables_it(self, qapp, tmp_path):
        from qtpy.QtCore import Qt

        dialog = SettingsDialog(_Config(tmp_path), [Alpha(), Beta()], [], {"Alpha"}, [])
        dialog.plugin_list.item(0).setCheckState(Qt.Checked)
        assert dialog.disabled_plugins() == set()

    def test_the_description_is_shown_as_a_tooltip(self, qapp, tmp_path):
        dialog = SettingsDialog(_Config(tmp_path), [Alpha()], [], set(), [])
        assert "alpha thing" in dialog.plugin_list.item(0).toolTip()


class TestBrokenPlugins:
    def test_a_broken_plugin_is_shown_with_its_error(self, qapp, tmp_path):
        broken = [BrokenPlugin(tmp_path / "bad.py", "boom", "Traceback...")]
        dialog = SettingsDialog(_Config(tmp_path), [], broken, set(), [])

        text = dialog.broken_text()
        assert "bad.py" in text and "boom" in text

    def test_nothing_is_shown_when_all_plugins_loaded(self, qapp, tmp_path):
        dialog = SettingsDialog(_Config(tmp_path), [Alpha()], [], set(), [])
        assert dialog.broken_text() == ""

    def test_a_broken_plugin_cannot_be_enabled(self, qapp, tmp_path):
        """It never loaded, so there is nothing to switch on."""
        broken = [BrokenPlugin(tmp_path / "bad.py", "boom", "Traceback...")]
        dialog = SettingsDialog(_Config(tmp_path), [], broken, set(), [])
        assert dialog.plugin_names() == []


class TestPathsAreVisible:
    def test_the_paths_appear_in_the_window(self, qapp, tmp_path):
        dialog = SettingsDialog(
            _Config(tmp_path), [], [], set(), [tmp_path / "plugins"]
        )
        shown = dialog.paths_text()
        assert str(tmp_path / "config.ini") in shown
        assert str(tmp_path / "plugins") in shown

    def test_the_paths_can_be_selected_for_copying(self, qapp, tmp_path):
        """Reading a path off the screen and retyping it is no use."""
        from qtpy.QtCore import Qt

        dialog = SettingsDialog(_Config(tmp_path), [], [], set(), [])
        assert dialog.paths_view.textInteractionFlags() & Qt.TextSelectableByMouse
