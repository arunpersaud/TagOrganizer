"""One entry point where scope is resolved and failures are contained.

Menu clicks and the post-import auto chain both go through run_plugin, so
there is a single place that decides what a plugin acts on.
"""

import os
from pathlib import Path

import pytest

from tagorganizer.plugins import Plugin
from tagorganizer.scope import Scope, resolve_scope

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _Messages:
    def __init__(self):
        self.sent = []

    def add(self, text):
        self.sent.append(text)


class _Config:
    def __init__(self, path):
        self.photos = Path(path)
        self.videos = Path(path)


class _Main:
    def __init__(self, path):
        self.messages = _Messages()
        self.config = _Config(path)


@pytest.fixture
def task_manager(qapp, tmp_path):
    """A TaskManager whose worker is always shut down afterwards."""
    from tagorganizer.tasks import TaskManager

    manager = TaskManager(_Main(tmp_path))
    try:
        yield manager
    finally:
        manager.shutdown()


class Recorder(Plugin):
    name = "Recorder"

    def __init__(self):
        self.seen = None

    def run(self, ctx):
        self.seen = ctx.scope
        yield 1, 1


class TestScopeResolution:
    def test_a_plugin_receives_the_scope_it_was_queued_with(
        self, temp_db, task_manager
    ):
        plugin = Recorder()
        task_manager.run_plugin(plugin, resolve_scope([1, 2]))
        assert task_manager.wait_for_idle()
        assert plugin.seen.is_selection is True
        assert list(plugin.seen.item_ids) == [1, 2]

    def test_the_library_scope_is_passed_through(self, temp_db, task_manager):
        plugin = Recorder()
        task_manager.run_plugin(plugin, Scope.LIBRARY)
        assert task_manager.wait_for_idle()
        assert plugin.seen == Scope.LIBRARY


class TestReporting:
    def test_the_status_message_names_the_scope(self, temp_db, task_manager):
        """A single menu entry acts on the selection or the library, so the
        message has to say which it just did."""
        task_manager.run_plugin(Recorder(), resolve_scope([1, 2, 3]))
        assert task_manager.wait_for_idle()
        assert any(
            "3 selected items" in m for m in task_manager.main.messages.sent
        ), task_manager.main.messages.sent

    def test_the_message_names_the_plugin(self, temp_db, task_manager):
        task_manager.run_plugin(Recorder(), Scope.LIBRARY)
        assert task_manager.wait_for_idle()
        assert any("Recorder" in m for m in task_manager.main.messages.sent)


class TestContextWiring:
    def test_the_plugin_gets_the_configured_directories(
        self, temp_db, task_manager, tmp_path
    ):
        class Paths(Plugin):
            name = "Paths"

            def __init__(self):
                self.photos = None

            def run(self, ctx):
                self.photos = ctx.photos
                yield 1, 1

        plugin = Paths()
        task_manager.run_plugin(plugin, Scope.LIBRARY)
        assert task_manager.wait_for_idle()
        assert plugin.photos == tmp_path

    def test_plugin_messages_reach_the_status_bar(self, temp_db, task_manager):
        class Chatty(Plugin):
            name = "Chatty"

            def run(self, ctx):
                ctx.message("halfway")
                yield 1, 1

        task_manager.run_plugin(Chatty(), Scope.LIBRARY)
        assert task_manager.wait_for_idle()
        assert "halfway" in task_manager.main.messages.sent


class TestFailureIsolation:
    def test_a_plugin_that_raises_is_reported_not_fatal(self, temp_db, task_manager):
        class Explodes(Plugin):
            name = "Explodes"

            def run(self, ctx):
                raise RuntimeError("kaboom")
                yield  # pragma: no cover

        task_manager.run_plugin(Explodes(), Scope.LIBRARY)
        assert task_manager.wait_for_idle()
        assert any(
            "kaboom" in m for m in task_manager.main.messages.sent
        ), task_manager.main.messages.sent

    def test_a_failing_plugin_does_not_stop_the_next(self, temp_db, task_manager):
        ran = []

        class Explodes(Plugin):
            name = "Explodes"

            def run(self, ctx):
                raise RuntimeError("kaboom")
                yield  # pragma: no cover

        class Works(Plugin):
            name = "Works"

            def run(self, ctx):
                ran.append(True)
                yield 1, 1

        task_manager.run_plugin(Explodes(), Scope.LIBRARY)
        task_manager.run_plugin(Works(), Scope.LIBRARY)
        assert task_manager.wait_for_idle()
        assert ran == [True]


class TestLoadingIntoTheManager:
    def test_broken_plugins_are_reported_once(self, temp_db, task_manager, tmp_path):
        """A plugin that fails to load must say so, not disappear."""
        bad = tmp_path / "bad.py"
        bad.write_text("raise RuntimeError('nope')\n")

        task_manager.load_plugins([tmp_path])

        assert any("bad.py" in m for m in task_manager.main.messages.sent)
        assert task_manager.registry.all() == []
