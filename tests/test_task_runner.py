"""Task work must leave the GUI thread.

Tasks used to be stepped by a QTimer on the GUI thread, which is why they were
sliced into 500 ms chunks - hashing ten files between yields was already
marginal for large videos, and a plugin doing real work per photo would freeze
the window outright.

These tests use a real QApplication because thread affinity is the thing under
test and cannot be faked.
"""

import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    widgets = pytest.importorskip("qtpy.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


@pytest.fixture
def runner(qapp):
    """A TaskRunner that is always shut down, so threads never leak."""
    from tagorganizer.tasks import TaskRunner

    made = TaskRunner()
    try:
        yield made
    finally:
        made.shutdown()


def wait_until(predicate, timeout_ms=5000):
    """Spin the GUI event loop until predicate holds, or give up."""
    from qtpy.QtCore import QCoreApplication, QThread

    for _ in range(timeout_ms // 10):
        QCoreApplication.processEvents()
        if predicate():
            return True
        QThread.msleep(10)
    QCoreApplication.processEvents()
    return predicate()


class TestRunsOffTheGuiThread:
    def test_the_generator_body_runs_on_another_thread(self, runner):
        gui_thread = threading.get_ident()
        seen = []

        def work():
            seen.append(threading.get_ident())
            yield 1, 1

        runner.enqueue(work())
        assert wait_until(runner.is_idle), "task never finished"
        assert seen, "the generator never ran"
        assert seen[0] != gui_thread

    def test_progress_arrives_on_the_gui_thread(self, runner):
        """The progress bar is a widget; touching it off-thread is undefined."""
        gui_thread = threading.get_ident()
        seen = []

        def work():
            yield 2, 1
            yield 2, 2

        runner.progress.connect(
            lambda total, current: seen.append(threading.get_ident())
        )
        runner.enqueue(work())
        assert wait_until(lambda: len(seen) >= 2), "progress never arrived"
        assert all(ident == gui_thread for ident in seen)

    def test_every_progress_value_is_delivered(self, runner):
        got = []

        def work():
            for i in range(5):
                yield 5, i

        runner.progress.connect(lambda total, current: got.append(current))
        runner.enqueue(work())
        assert wait_until(lambda: len(got) == 5), f"only got {got}"
        assert got == [0, 1, 2, 3, 4]


class TestFailingTasks:
    def test_an_exception_is_reported_and_does_not_propagate(self, runner):
        def work():
            yield 1, 0
            raise RuntimeError("boom")

        messages = []
        runner.message.connect(messages.append)
        runner.enqueue(work())
        assert wait_until(
            lambda: any("boom" in m for m in messages)
        ), f"the failure was never reported; got {messages}"

    def test_a_failing_task_does_not_stop_the_next_one(self, runner):
        """One bad plugin must not silently kill the queue behind it."""
        ran = []

        def bad():
            raise RuntimeError("boom")
            yield  # pragma: no cover

        def good():
            ran.append(True)
            yield 1, 1

        runner.enqueue(bad())
        runner.enqueue(good())
        assert wait_until(lambda: ran == [True]), "the second task never ran"
        assert runner.is_idle()


class TestCancellation:
    def test_cancel_stops_a_long_task(self, runner):
        def forever():
            n = 0
            while True:
                n += 1
                yield 1_000_000, n

        runner.enqueue(forever())
        assert wait_until(lambda: not runner.is_idle())
        runner.cancel()
        assert wait_until(runner.is_idle), "cancel did not stop the task"

    def test_cancel_drops_work_that_had_not_started(self, runner):
        """Held open with events rather than a long loop.

        A task that merely takes a while can finish before cancel lands, which
        made this test pass or fail depending on machine speed.
        """
        ran = []
        started = threading.Event()
        release = threading.Event()

        def slow():
            started.set()
            release.wait(5)
            yield 1, 1

        def later():
            ran.append(True)
            yield 1, 1

        runner.enqueue(slow())
        runner.enqueue(later())
        assert started.wait(5), "the first task never started"

        runner.cancel()
        release.set()

        assert wait_until(runner.is_idle)
        assert ran == []


class TestProfileSwitch:
    def test_the_worker_is_idle_before_the_engine_is_replaced(self, runner, tmp_path):
        """Switching profiles disposes the engine.

        If the worker is still inside a task holding a session on the old
        database when that happens, the switch tears the ground out from under
        a running query. stop() must not return until the worker has finished.
        """
        from tagorganizer import db

        previous = db.engine
        started = threading.Event()
        release = threading.Event()

        def busy():
            started.set()
            release.wait(5)
            yield 1, 1

        try:
            db.set_engine(str(tmp_path / "first.db"))
            runner.enqueue(busy())
            assert started.wait(5), "the task never started"

            # The worker is provably inside the task at this point, which is
            # the state a profile switch must not interrupt.
            runner.cancel()
            release.set()
            assert wait_until(runner.is_idle), "worker still running at switch time"

            db.set_engine(str(tmp_path / "second.db"))
            db.engine.dispose()
        finally:
            db.engine = previous
