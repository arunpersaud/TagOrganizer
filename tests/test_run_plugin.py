"""One entry point where scope is resolved and failures are contained.

Menu clicks and the post-import auto chain both go through run_plugin, so
there is a single place that decides what a plugin acts on.
"""

import os
import threading
import time
from pathlib import Path

import pytest

from tagorganizer.plugins import Plugin
from tagorganizer.scope import Scope, resolve_scope

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _Messages:
    def __init__(self):
        self.sent = []
        self.threads = []

    def add(self, text):
        self.sent.append(text)
        self.threads.append(threading.get_ident())


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


class TestMessageThread:
    def test_plugin_messages_are_added_on_the_gui_thread(self, temp_db, task_manager):
        """The message widget is a QTextEdit, so a plugin's message must be
        queued to the GUI thread rather than added from the worker."""

        class Chatty(Plugin):
            name = "Chatty"

            def run(self, ctx):
                ctx.message("from the worker")
                yield 1, 1

        gui_thread = threading.get_ident()
        task_manager.run_plugin(Chatty(), Scope.LIBRARY)
        assert task_manager.wait_for_idle()
        sent = task_manager.main.messages
        threads = [
            ident
            for text, ident in zip(sent.sent, sent.threads, strict=False)
            if text == "from the worker"
        ]
        assert threads == [gui_thread]


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


class TestStopping:
    """stop() is the gate the profile switch goes through, so these call it."""

    def test_stop_does_not_return_while_the_task_is_still_in_a_step(
        self, temp_db, task_manager
    ):
        release = threading.Event()
        started = threading.Event()
        finished_its_step = []

        class Slow(Plugin):
            name = "Slow"

            def run(self, ctx):
                started.set()
                release.wait(5)
                finished_its_step.append(True)
                yield 1, 1

        task_manager.run_plugin(Slow(), Scope.LIBRARY)
        # Without this the worker may not have picked the task up yet, and
        # cancel would drop it unstarted, which proves nothing about waiting.
        assert started.wait(5), "the task never started"
        timer = threading.Timer(0.3, release.set)
        timer.start()
        try:
            assert task_manager.stop() is True
        finally:
            timer.cancel()
            release.set()
        assert finished_its_step == [True], "stop() returned before the task let go"

    def test_stop_reports_failure_when_the_task_does_not_let_go(
        self, temp_db, task_manager
    ):
        """The caller must refuse the switch on False, so this must not claim
        the worker is idle when it is not."""
        release = threading.Event()
        started = threading.Event()

        class Stuck(Plugin):
            name = "Stuck"

            def run(self, ctx):
                started.set()
                release.wait(5)
                yield 1, 1

        task_manager.run_plugin(Stuck(), Scope.LIBRARY)
        assert started.wait(5), "the task never started"
        try:
            assert task_manager.stop(timeout_ms=200) is False
        finally:
            release.set()
        assert task_manager.wait_for_idle()

    def test_stop_cancels_the_running_plugin(self, temp_db, task_manager):
        class Forever(Plugin):
            name = "Forever"

            def run(self, ctx):
                # Paced: an unthrottled loop queues a progress signal per
                # spin, and draining that backlog on the GUI thread is what
                # made this test take twenty seconds.
                while not ctx.cancelled:
                    time.sleep(0.001)
                    yield 1, 1

        task_manager.run_plugin(Forever(), Scope.LIBRARY)
        assert task_manager.wait_for_idle(timeout_ms=200) is False
        assert task_manager.stop() is True
        assert task_manager.runner.is_idle()
