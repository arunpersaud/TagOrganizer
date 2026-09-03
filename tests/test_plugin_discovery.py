"""Finding plugins, and surviving the broken ones.

A plugin is Python the user chose to install, so there is no sandbox. What is
guaranteed is that a plugin which explodes gets reported rather than taking the
application down or vanishing without explanation.
"""

from tagorganizer.plugins.discovery import load_plugins, plugin_paths

GOOD = """
from tagorganizer.plugins import Plugin


class Good(Plugin):
    name = "Good"

    def run(self, ctx):
        yield 1, 1
"""

RAISES_ON_IMPORT = """
from tagorganizer.plugins import Plugin

raise RuntimeError("no good")


class Never(Plugin):
    name = "Never"
"""

NOT_A_PLUGIN = """
VALUE = 42
"""

# Underscore-prefixed so discovery skips the file itself; it exists only to be
# imported by the plugin below.
SHARED_HELPER = """
from tagorganizer.plugins import Plugin


class Shared(Plugin):
    name = "Shared"

    def run(self, ctx):
        yield 1, 1
"""

IMPORTS_A_PLUGIN_FROM_ELSEWHERE = """
from tagorganizer.plugins import Plugin
from _shared import Shared  # noqa: F401


class Mine(Plugin):
    name = "Mine"

    def run(self, ctx):
        yield 1, 1
"""

TWO_PLUGINS = """
from tagorganizer.plugins import Plugin


class First(Plugin):
    name = "First"

    def run(self, ctx):
        yield 1, 1


class Second(Plugin):
    name = "Second"

    def run(self, ctx):
        yield 1, 1
"""


class TestLoading:
    def test_a_good_plugin_is_registered(self, tmp_path):
        (tmp_path / "good.py").write_text(GOOD)
        registry, broken = load_plugins([tmp_path])
        assert [p.name for p in registry.all()] == ["Good"]
        assert broken == []

    def test_a_file_with_no_plugin_is_ignored(self, tmp_path):
        (tmp_path / "plain.py").write_text(NOT_A_PLUGIN)
        registry, broken = load_plugins([tmp_path])
        assert registry.all() == []
        assert broken == []

    def test_every_plugin_in_a_file_is_found(self, tmp_path):
        (tmp_path / "two.py").write_text(TWO_PLUGINS)
        registry, _ = load_plugins([tmp_path])
        assert sorted(p.name for p in registry.all()) == ["First", "Second"]

    def test_loading_is_sorted_by_filename(self, tmp_path):
        """Menu order must not depend on the order the filesystem returns."""
        (tmp_path / "b.py").write_text(GOOD.replace("Good", "Bee"))
        (tmp_path / "a.py").write_text(GOOD.replace("Good", "Ay"))
        registry, _ = load_plugins([tmp_path])
        assert [p.name for p in registry.all()] == ["Ay", "Bee"]

    def test_directories_are_loaded_in_the_order_given(self, tmp_path):
        """Shipped plugins come before the user's."""
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        (first / "p.py").write_text(GOOD.replace("Good", "Shipped"))
        (second / "p.py").write_text(GOOD.replace("Good", "Mine"))
        registry, _ = load_plugins([first, second])
        assert [p.name for p in registry.all()] == ["Shipped", "Mine"]

    def test_a_plugin_imported_from_elsewhere_is_not_registered_twice(self, tmp_path):
        """Only classes defined in the file count, not ones it imports.

        A plugin that imports a base class or helper from another module would
        otherwise register that module's plugins a second time, giving
        duplicate menu entries that both run the same work.
        """
        import sys

        (tmp_path / "_shared.py").write_text(SHARED_HELPER)
        (tmp_path / "mine.py").write_text(IMPORTS_A_PLUGIN_FROM_ELSEWHERE)

        sys.path.insert(0, str(tmp_path))
        try:
            registry, broken = load_plugins([tmp_path])
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("_shared", None)

        assert broken == [], broken
        assert [p.name for p in registry.all()] == ["Mine"]

    def test_files_starting_with_underscore_are_skipped(self, tmp_path):
        """__init__.py and private helpers are not plugins."""
        (tmp_path / "_helper.py").write_text(GOOD)
        registry, _ = load_plugins([tmp_path])
        assert registry.all() == []


class TestBrokenPlugins:
    def test_an_import_failure_is_recorded_not_raised(self, tmp_path):
        (tmp_path / "bad.py").write_text(RAISES_ON_IMPORT)
        registry, broken = load_plugins([tmp_path])
        assert registry.all() == []
        assert len(broken) == 1
        assert "no good" in broken[0].error

    def test_the_traceback_is_kept_for_diagnosis(self, tmp_path):
        """'My plugin does not appear' has to be answerable."""
        (tmp_path / "bad.py").write_text(RAISES_ON_IMPORT)
        _, broken = load_plugins([tmp_path])
        assert "RuntimeError" in broken[0].traceback

    def test_the_broken_record_names_the_file(self, tmp_path):
        (tmp_path / "bad.py").write_text(RAISES_ON_IMPORT)
        _, broken = load_plugins([tmp_path])
        assert broken[0].path.name == "bad.py"

    def test_a_broken_plugin_does_not_stop_the_others(self, tmp_path):
        (tmp_path / "a_bad.py").write_text(RAISES_ON_IMPORT)
        (tmp_path / "b_good.py").write_text(GOOD)
        registry, broken = load_plugins([tmp_path])
        assert [p.name for p in registry.all()] == ["Good"]
        assert len(broken) == 1

    def test_a_nameless_plugin_is_recorded_as_broken(self, tmp_path):
        """The registry refuses it; discovery must report rather than crash."""
        (tmp_path / "nameless.py").write_text(GOOD.replace('    name = "Good"\n', ""))
        registry, broken = load_plugins([tmp_path])
        assert registry.all() == []
        assert len(broken) == 1

    def test_a_missing_directory_is_not_an_error(self, tmp_path):
        registry, broken = load_plugins([tmp_path / "nope"])
        assert registry.all() == [] and broken == []


class TestPaths:
    def test_reports_the_shipped_and_the_user_directory(self):
        paths = plugin_paths()
        assert len(paths) == 2

    def test_the_user_directory_is_named_plugins(self):
        assert plugin_paths()[1].name == "plugins"

    def test_the_user_directory_sits_beside_the_config_file(self):
        """The settings window shows this path, so it has to be the real one."""
        from tagorganizer.config import config_dir

        assert plugin_paths()[1].parent == config_dir

    def test_the_shipped_directory_is_inside_the_package(self):
        import tagorganizer

        shipped = plugin_paths()[0]
        assert str(shipped).startswith(str(tagorganizer.__path__[0]))
