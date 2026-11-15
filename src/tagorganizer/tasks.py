"""
Copyright 2024 Arun Persaud.

This file is part of TagOrganizer.

TagOrganizer is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or (at
your option) any later version.

TagOrganizer is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with TagOrganizer. If not, see <https://www.gnu.org/licenses/>.

"""

import inspect
import logging
import threading
from collections import deque
from dataclasses import dataclass, field

from qtpy.QtWidgets import QProgressBar, QLabel
from qtpy.QtCore import (
    QCoreApplication,
    QMetaObject,
    QMutex,
    QMutexLocker,
    QObject,
    Qt,
    QThread,
    Signal,
    Slot,
)

from .plugins import Registry
from .plugins.context import TaskContext
from .scope import Scope, resolve_scope

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class _Job:
    """One generator waiting for, or in, the worker, with its cancel flag.

    The flag lives on the job rather than on the runner. A runner-wide flag
    that the next enqueue clears would let a cancelled task keep running the
    moment the user queued something new behind it.
    """

    gen: object
    ctx: TaskContext | None = None
    stop: threading.Event = field(default_factory=threading.Event)

    def request_stop(self) -> None:
        self.stop.set()
        # Plugins poll the context, not the runner, so both must be told.
        if self.ctx is not None:
            self.ctx.cancel()


class TaskRunner(QObject):
    """Steps task generators on a dedicated thread.

    One thread, not a pool: tasks are sequential, and the database runs in
    rollback-journal mode where concurrent writers contend. A single worker
    removes the question entirely.

    The generator body runs on the worker; ``progress`` and ``message`` are
    signals, so their receivers run on the GUI thread where the widgets live.
    """

    progress = Signal(int, int)
    message = Signal(str)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self._queue: deque[_Job] = deque()
        self._current: _Job | None = None
        self._lock = QMutex()
        self._draining = False

        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.start()

    def is_idle(self) -> bool:
        with QMutexLocker(self._lock):
            return not self._draining and not self._queue

    def enqueue(self, gen, ctx: TaskContext | None = None) -> None:
        """Add work and make sure the worker is awake.

        ``ctx`` is the context the generator was built with, if any. Cancelling
        the runner cancels it too, so a plugin polling ``ctx.cancelled`` stops.

        _drain is posted unconditionally rather than only when the worker looks
        idle. Deciding that from here means reading a flag the worker is
        concurrently changing, and the window between 'it looked busy' and 'it
        just finished' loses the wake-up entirely - which showed up as a task
        that silently never ran. An extra post is free: _drain returns at once
        if it is already running.
        """
        with QMutexLocker(self._lock):
            self._queue.append(_Job(gen, ctx))
        # Queued, so _drain runs on the worker thread rather than this one.
        QMetaObject.invokeMethod(self, "_drain", Qt.QueuedConnection)

    def cancel(self) -> None:
        """Drop pending work and ask the running task to stop at its next yield.

        Both halves matter: the running plugin is told through its context, and
        the runner itself stops stepping it, so a plugin that ignores the flag
        still cannot run past its next yield.
        """
        with QMutexLocker(self._lock):
            self._queue.clear()
            if self._current is not None:
                self._current.request_stop()

    def shutdown(self, timeout_ms=10_000) -> bool:
        """Cancel, then wait for the worker to exit. False if it did not in time.

        Waiting without a bound would hang the application on close whenever a
        plugin is slow to reach its next yield. The worker only ever needs the
        event loop to be free, and the GUI thread is the one blocking here, so
        the wait cannot deadlock against queued messages.
        """
        self.cancel()
        self._thread.quit()
        if self._thread.wait(timeout_ms):
            return True
        logger.warning("task worker still busy %s ms after cancel", timeout_ms)
        return False

    @Slot()
    def _drain(self):
        # No re-entrancy guard is needed: every _drain arrives as a queued
        # call on this one worker thread, and the thread's event loop is busy
        # for as long as this method runs, so a second one cannot start until
        # this returns. _draining exists so is_idle can see work in flight.
        with QMutexLocker(self._lock):
            self._draining = True

        ran = False
        while True:
            with QMutexLocker(self._lock):
                if not self._queue:
                    self._draining = False
                    self._current = None
                    break
                job = self._queue.popleft()
                self._current = job
            ran = True
            self._step(job)
            with QMutexLocker(self._lock):
                self._current = None

        # Only a drain that did work says so. Each enqueue posts a drain, so an
        # unconditional emit reported "Task done" once per queued item.
        if ran:
            self.finished.emit()

    def _step(self, job: _Job) -> None:
        if job.stop.is_set():
            job.gen.close()
            return
        try:
            for total, current in job.gen:
                if job.stop.is_set():
                    break
                self.progress.emit(total, current)
        except Exception as error:
            # A failing task must not stop the queue or take the app down.
            logger.exception("task failed")
            self.message.emit(f"Task failed: {error}")
        finally:
            # A generator abandoned mid-way runs its finally blocks only when
            # closed; leaving that to the garbage collector delays them.
            job.gen.close()


def _steps(plugin, ctx):
    """Run a plugin's run() on the worker, as a generator the runner steps.

    Calling run() here, on the GUI thread, would execute the plugin's work in
    the menu handler and abort the application if it raised. Calling it inside
    this generator defers the call to the worker's first step, and the runner
    reports any exception it raises like any other task failure.

    A run() that is not a generator function is refused by name: it has no
    yields, so it cannot report progress or be cancelled, and the message says
    what to change rather than leaving a bare TypeError.
    """
    result = plugin.run(ctx)
    if not inspect.isgenerator(result):
        raise TypeError(f"{plugin.name}: run() must be a generator (use yield)")
    yield from result


class TaskManager:
    """Owns the worker and the status-bar progress widgets.

    Keeps register_generator/start/stop so existing callers are unchanged, but
    the generators are now stepped on a worker thread rather than by a timer on
    the GUI thread.
    """

    def __init__(self, main):
        self.main = main

        self.registry = Registry()
        self.broken = []

        self.runner = TaskRunner()
        self.runner.progress.connect(self._on_progress)
        # Resolved at emit time, not now: the manager is built before the
        # main window has its message widget.
        # Queued explicitly: a plain callable connected here would run on the
        # thread that emits, which is the worker, and the message widget is a
        # GUI object. The queued call is delivered on the GUI thread.
        self.runner.message.connect(
            self._show_message, Qt.ConnectionType.QueuedConnection
        )
        self.runner.finished.connect(self._on_finished)

        self.progressbar_label = QLabel("Task")
        self.progressbar = QProgressBar()
        self.progressbar.setMaximumWidth(200)
        self.progressbar_label.setVisible(False)
        self.progressbar.setVisible(False)

    def register_widgets(self, statusbar):
        statusbar.addPermanentWidget(self.progressbar_label)
        statusbar.addPermanentWidget(self.progressbar)

    def register_generator(self, gen, ctx=None):
        self.runner.enqueue(gen, ctx)

    def start(self, interval=500):
        """Show the progress widgets.

        ``interval`` is accepted and ignored: there is no timer any more. The
        parameter stays so the existing call sites keep working.
        """
        self._set_progress_visible(True)

    def stop(self, timeout_ms=10_000) -> bool:
        """Cancel outstanding work and wait until the worker has let go.

        Callers switch databases straight after this, which disposes the
        engine. A worker still inside a task holds a session on the old
        database, and writes it makes after the switch would land in the new
        one. So when this returns False the caller must not switch.
        """
        self.runner.cancel()
        idle = self.wait_for_idle(timeout_ms)
        if idle:
            self._set_progress_visible(False)
        return idle

    def run_from_menu(self, plugin, selected_ids):
        """Run a menu entry on the scope its plugin's rule gives.

        A selection-aware plugin acts on the selection when there is one; any
        other plugin always gets the library. The rule lives here rather than
        in the menu handler so it can be tested without a window.
        """
        if plugin.accepts_selection:
            scope = resolve_scope(selected_ids)
        else:
            scope = Scope.LIBRARY
        self.run_plugin(plugin, scope)

    def load_plugins(self, directories=None):
        """Find the plugins and report any that could not be loaded.

        A broken plugin is named in the status bar rather than silently
        missing: "my plugin does not appear" has to be answerable.
        """
        from .plugins.discovery import load_plugins, plugin_paths

        self.registry, self.broken = load_plugins(
            plugin_paths() if directories is None else directories
        )
        for broken in self.broken:
            self.main.messages.add(
                f"Plugin {broken.path.name} failed to load: {broken.error}"
            )

    def run_plugin(self, plugin, scope):
        """Build the context, start the plugin, and name the scope it got."""
        ctx = TaskContext(
            scope=scope,
            photos=self.main.config.photos,
            videos=self.main.config.videos,
            # Plugins run on the worker, so their messages go through the
            # runner's queued signal rather than straight to the message widget.
            message_sink=self.runner.message.emit,
            sharing_profiles=tuple(self.main.config.other_profiles_sharing_photos()),
        )
        self.main.messages.add(f"{plugin.name}: running on {scope.describe()}")
        self.register_generator(_steps(plugin, ctx), ctx)
        self.start()

    def shutdown(self, timeout_ms=10_000) -> bool:
        """Stop the worker thread. False if it is still busy after the timeout.

        A QThread still running when its C++ object is destroyed aborts the
        process, so every owner - the main window, and any test that builds a
        manager - has to call this. A False return means the caller must not
        tear the window down yet.
        """
        return self.runner.shutdown(timeout_ms)

    def wait_for_idle(self, timeout_ms=10_000) -> bool:
        """Spin the event loop until the worker has finished.

        Events are pumped before the idleness check, and once more after it:
        progress and messages are queued signals, so the worker can already be
        idle while its last message is still in flight. Returning early left
        callers looking at a status bar that had not caught up yet.

        The trailing pump covers the interleaving where the worker emits its
        last message and goes idle *between* the pump and the check above. No
        test forces that window - it cannot be scheduled deterministically -
        so treat this line as load-bearing even though nothing goes red if it
        is removed.
        """
        for _ in range(timeout_ms // 10):
            QCoreApplication.processEvents()
            if self.runner.is_idle():
                QCoreApplication.processEvents()
                return True
            QThread.msleep(10)
        QCoreApplication.processEvents()
        return self.runner.is_idle()

    def _set_progress_visible(self, visible):
        self.progressbar_label.setVisible(visible)
        self.progressbar.setVisible(visible)

    def _show_message(self, text):
        self.main.messages.add(text)

    def _on_progress(self, total, current):
        self.progressbar.setMaximum(total)
        self.progressbar.setValue(current)

    def _on_finished(self):
        self._set_progress_visible(False)
        self.main.messages.add("Task done")
        # A plugin may have added, changed or removed photos and tags, and the
        # views were drawn before it ran. Without this they stay stale until
        # something else happens to redraw them.
        self.main.refresh_after_data_change()
