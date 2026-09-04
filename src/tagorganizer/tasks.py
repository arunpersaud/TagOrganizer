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

import logging
from collections import deque

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

logger = logging.getLogger(__name__)

# Previews are built at the grid's default tile width; a hover shows them
# scaled to whatever the tile currently is.
PREVIEW_WIDTH = 150


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
        self._queue = deque()
        self._lock = QMutex()
        self._draining = False
        self._cancelled = False

        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.start()

    def is_idle(self) -> bool:
        with QMutexLocker(self._lock):
            return not self._draining and not self._queue

    def enqueue(self, gen) -> None:
        """Add work and make sure the worker is awake.

        _drain is posted unconditionally rather than only when the worker looks
        idle. Deciding that from here means reading a flag the worker is
        concurrently changing, and the window between 'it looked busy' and 'it
        just finished' loses the wake-up entirely - which showed up as a task
        that silently never ran. An extra post is free: _drain returns at once
        if it is already running.
        """
        with QMutexLocker(self._lock):
            self._queue.append(gen)
            self._cancelled = False
        # Queued, so _drain runs on the worker thread rather than this one.
        QMetaObject.invokeMethod(self, "_drain", Qt.QueuedConnection)

    def cancel(self) -> None:
        """Drop pending work and ask the running task to stop at its next yield."""
        with QMutexLocker(self._lock):
            self._cancelled = True
            self._queue.clear()

    def shutdown(self) -> None:
        self.cancel()
        self._thread.quit()
        self._thread.wait()

    @Slot()
    def _drain(self):
        # No re-entrancy guard is needed: every _drain arrives as a queued
        # call on this one worker thread, and the thread's event loop is busy
        # for as long as this method runs, so a second one cannot start until
        # this returns. _draining exists so is_idle can see work in flight.
        with QMutexLocker(self._lock):
            self._draining = True

        while True:
            with QMutexLocker(self._lock):
                if self._cancelled or not self._queue:
                    self._draining = False
                    break
                gen = self._queue.popleft()
            try:
                for total, current in gen:
                    with QMutexLocker(self._lock):
                        stopping = self._cancelled
                    if stopping:
                        break
                    self.progress.emit(total, current)
            except Exception as error:
                # A failing task must not stop the queue or take the app down.
                logger.exception("task failed")
                self.message.emit(f"Task failed: {error}")
        self.finished.emit()


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
        self.runner.message.connect(lambda text: self.main.messages.add(text))
        self.runner.finished.connect(self._on_finished)

        # stop() is called on every profile switch, not only after a task, so
        # it has to know whether there was anything to finish.
        self._running = False

        self.progressbar_label = QLabel("Task")
        self.progressbar = QProgressBar()
        self.progressbar.setMaximumWidth(200)
        self.progressbar_label.setVisible(False)
        self.progressbar.setVisible(False)

    def register_widgets(self, statusbar):
        statusbar.addPermanentWidget(self.progressbar_label)
        statusbar.addPermanentWidget(self.progressbar)

    def register_generator(self, gen):
        self.runner.enqueue(gen)

    def start(self, interval=500):
        """Show the progress widgets.

        ``interval`` is accepted and ignored: there is no timer any more. The
        parameter stays so the existing call sites keep working.
        """
        self._running = True
        self._set_progress_visible(True)

    def stop(self):
        """Cancel outstanding work and wait for the worker to let go.

        Callers switch profiles straight after this, which disposes the engine.
        Returning while the worker still held a session on the old database
        would pull the database out from under a running query.
        """
        was_running = self._running
        self._running = False
        self.runner.cancel()
        self.wait_for_idle()
        self._set_progress_visible(False)
        if was_running:
            self.main.messages.add("Task done")

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
            message_sink=self.main.messages.add,
        )
        self.main.messages.add(f"{plugin.name}: running on {scope.describe()}")
        # A plugin whose run() raises immediately produces a generator that
        # raises on first next(), which the worker catches like any other
        # failure - so there is no separate error path here.
        self.register_generator(plugin.run(ctx))
        self.start()

    def shutdown(self):
        """Stop the worker thread.

        A QThread still running when its C++ object is destroyed aborts the
        process, so every owner - the main window, and any test that builds a
        manager - has to call this.
        """
        self.runner.shutdown()

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

    def _on_progress(self, total, current):
        self.progressbar.setMaximum(total)
        self.progressbar.setValue(current)

    def _on_finished(self):
        self._running = False
        self._set_progress_visible(False)
        self.main.messages.add("Task done")
