"""The Tasks menu is generated, and the scope rule is applied at click time.

The menu, the post-import chain and the settings page all read one registry,
so they cannot drift apart the way three hand-maintained lists did.
"""

import ast
import inspect
import textwrap

from tagorganizer import main as main_module
from tagorganizer.plugins.discovery import load_plugins, plugin_paths


def source_tree(func):
    return ast.parse(textwrap.dedent(inspect.getsource(func)))


def attribute_calls(tree, name):
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == name
    ]


def plain_calls(tree, name):
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


class TestMenuGeneration:
    def test_the_tasks_menu_is_no_longer_hand_written(self):
        source = inspect.getsource(main_module.MainWindow.__init__)
        assert '"Tasks": [' not in source

    def test_the_menu_is_built_from_the_registry(self):
        tree = source_tree(main_module.MainWindow.build_plugin_menu)
        assert attribute_calls(tree, "by_category")

    def test_the_plugins_are_loaded_before_the_menu_is_built(self):
        source = inspect.getsource(main_module.MainWindow.__init__)
        assert "load_plugins" in source
        assert source.index("load_plugins") < source.index("build_plugin_menu")


class TestScopeAtClickTime:
    def test_the_scope_is_resolved_when_the_entry_is_clicked(self):
        """Resolved at click, not at build: the menu is built once and the
        selection changes constantly."""
        tree = source_tree(main_module.MainWindow.build_plugin_menu)
        assert plain_calls(tree, "resolve_scope")

    def test_a_library_only_plugin_never_gets_a_selection(self):
        source = inspect.getsource(main_module.MainWindow.build_plugin_menu)
        assert "accepts_selection" in source

    def test_the_plugin_is_bound_per_entry(self):
        """Without a default argument every entry would run the last plugin,
        because the lambda would close over the loop variable."""
        tree = source_tree(main_module.MainWindow.build_plugin_menu)
        lambdas = [n for n in ast.walk(tree) if isinstance(n, ast.Lambda)]
        assert lambdas, "the entries are not connected through a lambda"
        assert any(
            lam.args.defaults for lam in lambdas
        ), "no lambda binds its plugin as a default argument"


class TestAutoRun:
    def test_importing_images_queues_the_auto_plugins(self):
        tree = source_tree(main_module.MainWindow.add_directory)
        assert attribute_calls(tree, "auto_plugins")


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

    def test_the_categories_are_the_expected_three(self):
        registry, _ = self._shipped()
        assert set(registry.by_category()) == {"Maintenance", "Files", "Reports"}

    def test_nothing_that_moves_files_runs_automatically(self):
        registry, _ = self._shipped()
        auto = {p.name for p in registry.auto_plugins()}
        assert "Move Files to Default Dirs" not in auto
        assert "Move Files with new date set" not in auto


class TestSettingsWiring:
    def test_the_edit_menu_offers_settings(self):
        source = inspect.getsource(main_module.MainWindow.__init__)
        assert "Settings" in source

    def test_opening_settings_passes_the_plugin_directories(self):
        """The window exists largely to answer 'where do I put a plugin'."""
        tree = source_tree(main_module.MainWindow.open_settings)
        assert plain_calls(tree, "plugin_paths")

    def test_it_lists_every_plugin_including_disabled_ones(self):
        """all() hides disabled plugins, so the window would not show them."""
        tree = source_tree(main_module.MainWindow.open_settings)
        assert attribute_calls(tree, "every")

    def test_the_choice_is_persisted(self):
        tree = source_tree(main_module.MainWindow.open_settings)
        assert attribute_calls(tree, "set_disabled_plugins")

    def test_the_menus_are_rebuilt_so_the_change_shows_at_once(self):
        tree = source_tree(main_module.MainWindow.open_settings)
        assert attribute_calls(tree, "build_plugin_menu")

    def test_disabled_plugins_are_applied_at_startup(self):
        source = inspect.getsource(main_module.MainWindow.__init__)
        assert "get_disabled_plugins" in source

    def test_rebuilding_removes_the_previous_menus(self):
        """Otherwise every visit to Settings adds another Maintenance menu.

        removeAction alone is not enough and this test used to accept it:
        unhooking the action leaves the menu still parented to the bar, and
        the duplicates came back. Only a real window caught that, so this now
        insists the widget is disposed of as well.
        """
        source = inspect.getsource(main_module.MainWindow.build_plugin_menu)
        assert "removeAction" in source
        assert "deleteLater" in source or "setParent(None)" in source
