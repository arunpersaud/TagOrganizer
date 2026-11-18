"""The Tasks menu is generated, and the scope rule is applied at click time.

The menu, the post-import chain and the settings page all read one registry,
so they cannot drift apart the way three hand-maintained lists did. These
drive a real window: the menu entries are the actions on it, and choosing one
is triggering the action.
"""

import pytest

from tagorganizer.plugins.discovery import load_plugins, plugin_paths
from window_fixtures import menu_action


class TestMenuGeneration:
    def test_the_menu_entries_are_exactly_the_enabled_plugins(self, window_for):
        """Hand-written menus drift from the registry; this compares them."""
        window = window_for()
        entries = {
            action.text() for menu in window._plugin_menus for action in menu.actions()
        }

        assert entries == {plugin.name for plugin in window.tasks.registry.all()}

    def test_each_category_is_a_menu_holding_its_own_plugins(self, window_for):
        window = window_for()
        by_category = window.tasks.registry.by_category()

        for category, plugins in by_category.items():
            menu = window.menu[category]
            assert menu.title() == category
            assert {action.text() for action in menu.actions()} == {
                plugin.name for plugin in plugins
            }


class TestScopeAtClickTime:
    """Which scope a plugin gets is behaviour, checked in test_run_plugin.py
    against TaskManager.run_from_menu. What is left here is the wiring: that
    each menu entry hands its own plugin and the live selection to it.
    """

    def test_each_entry_runs_its_own_plugin_with_the_selection_at_click_time(
        self, window_for, monkeypatch
    ):
        """The menu is built once and the selection changes constantly, so the
        selection must be read when the entry is chosen, and each entry must
        name its own plugin rather than the last one built.
        """
        window = window_for()
        runs = []
        monkeypatch.setattr(
            window.tasks,
            "run_from_menu",
            lambda plugin, ids: runs.append((plugin.name, sorted(ids))),
        )
        window.selection.add_many([5, 7])
        actions = [action for menu in window._plugin_menus for action in menu.actions()]
        assert len(actions) >= 8, "precondition: the shipped plugins are in the menu"

        for action in actions:
            action.trigger()

        assert [name for name, _ in runs] == [action.text() for action in actions]
        assert all(ids == [5, 7] for _, ids in runs)


class TestAutoRun:
    def test_importing_images_runs_the_auto_plugins(
        self, window_for, tmp_path, monkeypatch
    ):
        """A plugin marked auto runs itself after an import, without being asked."""
        import tagorganizer.main as main_module

        home = tmp_path / "auto"
        (home / "plugins").mkdir(parents=True)
        marker = tmp_path / "ran.txt"
        (home / "plugins" / "auto.py").write_text(
            "from tagorganizer.plugins import Plugin\n"
            "\n"
            "class AutoMarker(Plugin):\n"
            '    name = "Auto marker"\n'
            '    category = "Tags"\n'
            "    auto = True\n"
            "\n"
            "    def run(self, ctx):\n"
            f"        open({str(marker)!r}, 'w').write('ran')\n"
            "        yield 1, 1\n"
        )
        photos = tmp_path / "photos-to-import"
        photos.mkdir()
        (photos / "a.jpg").write_bytes(b"not really a jpeg")

        class ChosenDirectory:
            @staticmethod
            def getExistingDirectory(*args, **kwargs):
                return str(photos)

        monkeypatch.setattr(main_module, "QFileDialog", ChosenDirectory)
        window = window_for(plugins_dir=home)

        window.add_directory()

        assert window.tasks.wait_for_idle(), "the auto task never finished"
        assert marker.read_text() == "ran"

    def _import_with_recorder(
        self, window_for, tmp_path, monkeypatch, whole_library=False
    ):
        """A window whose only auto plugin writes down the ids it was given."""
        import tagorganizer.main as main_module

        home = tmp_path / "recorder"
        (home / "plugins").mkdir(parents=True)
        marker = tmp_path / "scope.txt"
        (home / "plugins" / "recorder.py").write_text(
            "from tagorganizer.plugins import Plugin\n"
            "\n"
            "class ScopeRecorder(Plugin):\n"
            '    name = "Scope recorder"\n'
            '    category = "Tags"\n'
            "    auto = True\n"
            f"    auto_whole_library = {whole_library!r}\n"
            "\n"
            "    def run(self, ctx):\n"
            f"        open({str(marker)!r}, 'w').write(repr(ctx.scope.item_ids))\n"
            "        yield 1, 1\n"
        )
        photos = tmp_path / "photos-to-import"
        photos.mkdir()
        (photos / "a.jpg").write_bytes(b"not really a jpeg")

        class ChosenDirectory:
            @staticmethod
            def getExistingDirectory(*args, **kwargs):
                return str(photos)

        monkeypatch.setattr(main_module, "QFileDialog", ChosenDirectory)
        return window_for(plugins_dir=home), marker, photos

    def test_an_import_reads_dates_and_gps(self, window_for, tmp_path, monkeypatch):
        """The whole point: add a folder, and the photos have dates and places."""
        from datetime import datetime, timezone

        import tagorganizer.main as main_module
        from synthetic_media import write_mp4
        from tagorganizer import db

        photos = tmp_path / "photos-to-import"
        photos.mkdir()
        video = write_mp4(
            photos / "clip.mp4",
            when=datetime(2021, 3, 5, 12, tzinfo=timezone.utc),
            gps=(48.1, 11.5),
        )

        class ChosenDirectory:
            @staticmethod
            def getExistingDirectory(*args, **kwargs):
                return str(photos)

        monkeypatch.setattr(main_module, "QFileDialog", ChosenDirectory)
        window = window_for()

        window.add_directory()

        assert window.tasks.wait_for_idle(), "the automatic tasks never finished"
        [item] = db.get_items_by_ids([db.check_item_in_db(str(video))])
        # The container holds UTC; the item stores the same instant as local.
        taken = datetime(2021, 3, 5, 12, tzinfo=timezone.utc)
        assert item.date == taken.astimezone().replace(tzinfo=None)
        assert (item.latitude, item.longitude) == pytest.approx((48.1, 11.5))

    def test_auto_tasks_see_only_the_imported_photos(
        self, window_for, tmp_path, monkeypatch
    ):
        """A big library is not reread for every folder added to it."""
        from tagorganizer import db

        window, marker, photos = self._import_with_recorder(
            window_for, tmp_path, monkeypatch
        )
        db.add_images([str(tmp_path / "already-here.jpg")])

        window.add_directory()

        assert window.tasks.wait_for_idle(), "the auto task never finished"
        new_id = db.check_item_in_db(str(photos / "a.jpg"))
        assert marker.read_text() == repr((new_id,))
        log = window.messages.text_edit.toPlainText()
        assert "Scope recorder: running on 1 imported item" in log

    def test_a_catch_up_task_gets_the_whole_library(
        self, window_for, tmp_path, monkeypatch
    ):
        """Work an interrupted import left undone is picked up by the next one."""
        window, marker, _ = self._import_with_recorder(
            window_for, tmp_path, monkeypatch, whole_library=True
        )

        window.add_directory()

        assert window.tasks.wait_for_idle(), "the auto task never finished"
        assert marker.read_text() == "None"

    def test_an_import_with_nothing_new_runs_no_auto_task(
        self, window_for, tmp_path, monkeypatch
    ):
        """Nothing to do, and certainly not the whole library."""
        window, marker, _ = self._import_with_recorder(
            window_for, tmp_path, monkeypatch
        )
        window.add_directory()
        assert window.tasks.wait_for_idle(), "the first import never finished"
        marker.unlink()

        window.add_directory()

        assert window.tasks.wait_for_idle()
        assert not marker.exists()


class TestShippedPlugins:
    def _shipped(self):
        registry, broken = load_plugins([plugin_paths()[0]])
        return registry, broken

    def test_the_shipped_plugins_all_load(self):
        registry, broken = self._shipped()
        assert broken == [], broken
        assert len(registry.all()) >= 8

    def test_every_task_the_app_had_is_still_offered(self):
        registry, _ = self._shipped()
        names = {p.name for p in registry.all()}
        # A subset check, not equality: adding a plugin must not fail this,
        # but losing one of the original eight must.
        assert names >= {
            "Update Timestamps in DB",
            "Update Locations in DB",
            "Update Hashes in DB",
            "Check for Files in Default Dirs",
            "Check for Files outside of Default Dirs",
            "Move Files with new date set",
            "Move Files to Default Dirs",
            "Build Video Previews",
        }

    def test_hashes_run_before_video_previews(self):
        """A preview's cache key is the md5, which is empty until hashing has
        run. A preview built first would be written under the wrong name and
        never found again - the task would appear to succeed while nothing
        ever animated."""
        registry, _ = self._shipped()
        auto = [p.name for p in registry.auto_plugins()]
        assert auto.index("Update Hashes in DB") < auto.index("Build Video Previews")

    def test_an_import_hashes_dates_locates_and_previews(self):
        registry, _ = self._shipped()
        auto = {p.name for p in registry.auto_plugins()}
        assert auto >= {
            "Update Hashes in DB",
            "Update Timestamps in DB",
            "Update Locations in DB",
            "Build Video Previews",
        }

    def test_hashes_and_previews_catch_up_on_the_whole_library(self):
        """Both check cheaply for what is left, so a cancelled import's photos
        get done by the next import; dates and GPS reread every file without
        one, so they only look at the new photos."""
        registry, _ = self._shipped()
        catch_up = {p.name for p in registry.auto_plugins() if p.auto_whole_library}
        assert catch_up == {"Update Hashes in DB", "Build Video Previews"}

    def test_the_core_categories_are_all_present(self):
        """A superset check: shipping a plugin under a new category must not
        fail this, but losing one of the three must."""
        registry, _ = self._shipped()
        assert set(registry.by_category()) >= {"Maintenance", "Files", "Reports"}

    def test_the_core_categories_come_first_and_in_order(self):
        registry, _ = self._shipped()
        order = list(registry.by_category())
        assert order[:3] == ["Maintenance", "Files", "Reports"]

    def test_nothing_that_moves_files_runs_automatically(self):
        registry, _ = self._shipped()
        auto = {p.name for p in registry.auto_plugins()}
        assert "Move Files to Default Dirs" not in auto
        assert "Move Files with new date set" not in auto


class TestSettingsWiring:
    def test_the_edit_menu_offers_settings(self, window_for):
        assert menu_action(window_for(), "Edit", "Settings...") is not None

    def test_opening_settings_offers_every_plugin_and_the_plugin_directories(
        self, window_for, monkeypatch
    ):
        """all() hides disabled plugins, so the window must be given every one,
        and it is told where user plugins live."""
        import tagorganizer.widgets.settings as settings_module

        opened = []

        class RecordingSettings:
            def __init__(self, *args):
                opened.append(args)

            def exec(self):
                return 0

        monkeypatch.setattr(settings_module, "SettingsDialog", RecordingSettings)
        window = window_for(disabled_plugins="Update Hashes in DB")

        window.open_settings()

        _, plugins, _, disabled, paths, _ = opened[0]
        assert "Update Hashes in DB" in {plugin.name for plugin in plugins}
        assert disabled == {"Update Hashes in DB"}
        assert paths == plugin_paths()

    def test_a_plugin_switched_off_is_saved_and_leaves_the_menus_at_once(
        self, window_for, monkeypatch
    ):
        """The change must show without a restart, and survive one."""
        import tagorganizer.widgets.settings as settings_module

        class SwitchingOff:
            def __init__(self, *args):
                pass

            def exec(self):
                return 1

            def disabled_plugins(self):
                return {"Update Hashes in DB"}

        monkeypatch.setattr(settings_module, "SettingsDialog", SwitchingOff)
        window = window_for()
        assert menu_action(window, "Maintenance", "Update Hashes in DB") is not None

        window.open_settings()

        assert menu_action(window, "Maintenance", "Update Hashes in DB") is None
        saved = window.config.config_file.read_text()
        assert "disabled_plugins = Update Hashes in DB" in saved

    def test_a_plugin_switched_off_in_the_config_is_not_in_the_menus_at_startup(
        self, window_for
    ):
        window = window_for(disabled_plugins="Update Hashes in DB")

        assert menu_action(window, "Maintenance", "Update Hashes in DB") is None
        assert menu_action(window, "Files", "Move Files to Default Dirs") is not None
