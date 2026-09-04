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
from datetime import datetime
from pathlib import Path
import shutil

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
from more_itertools import chunked

from . import db
from . import config
from .plugins import Registry
from .plugins.context import TaskContext
from .widgets.helper import (
    build_video_preview,
    calculate_md5,
    calculate_xxhash,
    forget_thumbnail,
    load_exif,
    preview_file,
)

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

    def db_update_timestamps(self):
        self.main.messages.add("Task: Updating timestamps")
        self.register_generator(self.task_add_timestamp_to_db())
        self.start()

    def db_update_locations(self):
        self.main.messages.add("Task: Updating locations")
        self.register_generator(self.task_add_geolocation_to_db())
        self.start()

    def db_update_hashes(self):
        self.main.messages.add("Task: Updating hashes")
        self.register_generator(self.task_update_hashes())
        self.start()

    def build_video_previews(self):
        """Fill in missing animated previews for videos.

        Hashes are queued first. A preview's cache key is item.uri_md5, which is
        empty until task_update_hashes has run, so a preview built ahead of it
        would be written under the wrong name and never found again - the task
        would appear to succeed while nothing ever animated. TaskManager drains
        its generators in order, so registering both here is all the sequencing
        that is needed.
        """
        self.main.messages.add("Task: Building video previews")
        self.register_generator(self.task_update_hashes())
        self.register_generator(self.task_build_video_previews())
        self.start()

    def task_build_video_previews(self):
        """Extract a sprite sheet for every video that has not got one.

        Incremental: an existing sheet is left alone, so interrupting the task
        loses nothing and re-running it is cheap.
        """
        photos_path = self.main.config.photos
        items = [
            item
            for item in db.get_all_items()
            if Path(item.uri).suffix.lower() in config.VIDEO_SUFFIX
        ]

        total = len(items)
        current = 0
        N = 5

        built = 0
        skipped = 0
        for chunk in chunked(items, N):
            for item in chunk:
                if (
                    item.uri_md5
                    and preview_file(item.uri_md5, PREVIEW_WIDTH, photos_path).is_file()
                ):
                    skipped += 1
                    continue
                if build_video_preview(item, PREVIEW_WIDTH, photos_path):
                    built += 1
                else:
                    skipped += 1
            current += len(chunk)
            yield total, current

        # Always yield once, so a library with no videos still drives the
        # progress bar to completion instead of appearing to hang.
        if total == 0:
            yield 0, 0

        self.main.messages.add(f"videos needing a preview: {total}")
        self.main.messages.add(f"built {built}, skipped {skipped}")

    def move_files(self):
        self.main.messages.add("Task: moving files")

        self.register_generator(
            self.task_move_files(self.main.config.photos, self.main.config.videos)
        )
        self.start()

    def fix_no_date_files(self):
        self.main.messages.add("Task: Check files for new dates")
        self.register_generator(
            self.task_fix_no_date_files(
                self.main.config.photos, self.main.config.videos
            )
        )
        self.start()

    def list_files_not_in_db(self):
        """List files that are in photo/video dir, but not in the db."""
        self.main.messages.add("Task: List files that are not in the database")
        self.register_generator(self.task_list_files_not_in_db())
        self.start()

    def list_files_not_in_config_dir(self):
        """List files that are in photo/video dir, but not in the db."""
        self.main.messages.add("Task: List files that are outside of the config dirs")
        self.register_generator(
            self.task_list_files_not_in_config_dir(
                self.main.config.photos, self.main.config.videos
            )
        )
        self.start()

    def task_add_timestamp_to_db(self):
        items = db.get_items_without_date()

        total = len(items)
        current = 0
        N = 10

        fixed = 0
        for chunk in chunked(items, N):
            need_update = []
            for entry in chunk:
                filepath = Path(entry.uri)
                if not filepath.is_file():
                    continue
                tags = load_exif(filepath)
                if "EXIF DateTimeOriginal" in tags:
                    date_str = str(tags["EXIF DateTimeOriginal"])
                    try:
                        date_obj = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
                    except ValueError:
                        self.main.messages.add(
                            f"Cannot parse date '{date_str}' for {entry.uri}"
                        )
                        continue
                    entry.date = date_obj
                    fixed += 1
                    need_update.append(entry)
            db.update_items_in_db(need_update)
            current += N
            yield total, current
        self.main.messages.add(f"total items without timestamp in db={total}")
        self.main.messages.add(f"added timesstamp to {fixed} items")

    def convert_to_degrees(self, value, ref):
        d = float(value.values[0])
        m = float(value.values[1])
        s = float(value.values[2])

        f = d + (m / 60.0) + (s / 3600.0)
        if ref not in ["E", "N"]:
            f = -f
        return f

    def task_add_geolocation_to_db(self):
        items = db.get_items_without_location()

        total = len(items)
        current = 0
        N = 10

        fixed = 0
        for chunk in chunked(items, N):
            need_update = []
            for entry in chunk:
                filepath = Path(entry.uri)
                if not filepath.is_file():
                    continue
                tags = load_exif(filepath)

                if "GPS GPSLongitude" in tags and "GPS GPSLatitude" in tags:
                    lon_values = tags["GPS GPSLongitude"]
                    lat_values = tags["GPS GPSLatitude"]

                    lon_ref = str(tags.get("GPS GPSLongitudeRef", "E"))
                    lat_ref = str(tags.get("GPS GPSLatitudeRef", "N"))

                    lon = self.convert_to_degrees(lon_values, lon_ref)
                    lat = self.convert_to_degrees(lat_values, lat_ref)

                    entry.longitude = lon
                    entry.latitude = lat

                    fixed += 1
                    need_update.append(entry)
            db.update_items_in_db(need_update)
            current += N
            yield total, current
        self.main.messages.add(f"total items without geolocation in db={total}")
        self.main.messages.add(f"added geolocation to {fixed} items")

    def task_update_hashes(self):
        items = db.get_items_without_hashes()

        total = len(items)
        current = 0
        N = 10

        fixed = 0
        for chunk in chunked(items, N):
            need_update = []
            for item in chunk:
                filepath = Path(item.uri)
                if not filepath.is_file():
                    continue
                item.uri_md5 = calculate_md5(item.uri)
                item.data_xxhash = calculate_xxhash(filepath)
                need_update.append(item)
                fixed += 1
            db.update_items_in_db(need_update)
            current += N
            yield total, current
        self.main.messages.add(f"total items without hashes in db={total}")
        self.main.messages.add(f"added hashes to {fixed} items")

    def task_move_files(self, photo_dir: Path, video_dir: Path):
        """Move files to the directories named in the config file.

        We use different directories for photos and videos.
        """
        items = db.get_all_items_not_in_dir([photo_dir, video_dir], config.ALL_SUFFIX)

        total = len(items)
        current = 0
        N = 10

        moved = 0
        for chunk in chunked(items, N):
            need_update = []
            for item in chunk:
                # check that file actually exists
                filepath = Path(item.uri)
                if not filepath.is_file():
                    self.main.messages.add(f"[Error] item {item.uri} does not exist")
                    continue

                # figure out where to save the file
                ext = filepath.suffix.lower()
                if ext in config.PHOTO_SUFFIX:
                    correct_dir = Path(photo_dir)
                elif ext in config.VIDEO_SUFFIX:
                    correct_dir = Path(video_dir)
                else:
                    self.main.messages.add(
                        f"[Error] item {item.uri} cannot handle {ext}"
                    )
                    continue

                # figure out where to save the file
                if item.date:
                    year = item.date.year
                    month = item.date.month
                    day = item.date.day
                    correct_path = (
                        correct_dir
                        / f"{year:04d}"
                        / f"{month:02d}"
                        / f"{day:02d}"
                        / filepath.name
                    )
                else:
                    self.main.messages.add(f"[Error] item {item.uri} has no date set")
                    correct_path = correct_dir / "no-date" / filepath.name

                # lower the case for the extension
                correct_path = correct_path.with_suffix(ext)

                if correct_path.exists():
                    self.main.messages.add(
                        f"File already exists in the correct directory: {correct_path}"
                    )
                    continue

                # Move the file
                try:
                    correct_path.parent.mkdir(parents=True, exist_ok=True)

                    old_md5 = item.uri_md5
                    shutil.move(filepath, correct_path)
                    # The cache is keyed on the uri hash, which changes with the
                    # path, so the old entries could never be hit again.
                    forget_thumbnail(old_md5, self.main.config.photos)
                    item.uri = str(correct_path)
                    item.uri_md5 = calculate_md5(item.uri)
                    item.data_xxhash = calculate_xxhash(correct_path)
                    need_update.append(item)
                    moved += 1
                    self.main.messages.add(f"Moved {filepath} to {correct_path}")
                except Exception:
                    logger.exception("Failed to move %s to %s", filepath, correct_path)
                    self.main.messages.add(
                        f"Failed to move {filepath} to {correct_path}"
                    )
            db.update_items_in_db(need_update)
            current += len(chunk)
            yield total, current
        self.main.messages.add(f"total items outside photo/video dirs: {total}")
        self.main.messages.add(f"moved {moved} items")

    def task_list_files_not_in_config_dir(self, photo_dir: Path, video_dir: Path):
        """Move files to the directories named in the config file.

        We use different directories for photos and videos.
        """
        items = db.get_all_items_not_in_dir([photo_dir, video_dir], config.ALL_SUFFIX)

        total = len(items)
        current = 0
        N = 10

        for chunk in chunked(items, N):
            for item in chunk:
                filepath = Path(item.uri)
                if not filepath.is_file():
                    self.main.messages.add(f"[Error] item {item.uri} does not exist")
                    continue

                self.main.messages.add(f"File: {filepath}")
            current += len(chunk)
            yield total, current
        self.main.messages.add(f"total items outside photo/video dirs: {total}")

    def task_list_files_not_in_db(self):
        """List files that are in the config dirs, but not in the db."""

        current = 0

        photos = list(self.main.config.photos.rglob("*"))
        videos = list(self.main.config.videos.rglob("*"))

        total = len(photos) + len(videos)
        N = 10

        self.main.messages.add(
            f"   Photos in {self.main.config.photos}, but not in db:"
        )
        for chunk in chunked(photos, N):
            for file in chunk:
                if file.is_dir():
                    continue
                if "thumbnails" in str(file):
                    continue
                if ".DS_Store" in str(file):
                    continue
                res = db.check_item_in_db(str(file))
                if res is None:
                    self.main.messages.add(f"      {file}")
            current += N
            yield total, current

        self.main.messages.add(
            f"   Videos in {self.main.config.videos}, but not in db:"
        )
        for chunk in chunked(videos, N):
            for file in chunk:
                if file.is_dir():
                    continue
                if "thumbnails" in str(file):
                    continue
                if ".DS_Store" in str(file):
                    continue
                res = db.check_item_in_db(str(file))
                if res is None:
                    self.main.messages.add(f"      {file}")
            current += N
            yield total, current

    def task_fix_no_date_files(self, photo_dir: Path, video_dir: Path):
        """Move items from 'no-date' to their correct date-based location if date is now available."""
        self.main.messages.add("Task: Moving files out of 'no-date' if date is now set")

        items = db.get_items_under_no_date()

        total = len(items)
        current = 0
        N = 10
        moved = 0

        for chunk in chunked(items, N):
            need_update = []

            for item in chunk:
                filepath = Path(item.uri)

                if not filepath.is_file():
                    self.main.messages.add(f"[Error] item {item.uri} does not exist")
                    continue

                if not item.date:
                    self.main.messages.add(f"[Skip] item {item.uri} still has no date")
                    continue

                ext = filepath.suffix.lower()
                if ext in config.PHOTO_SUFFIX:
                    correct_dir = Path(photo_dir)
                elif ext in config.VIDEO_SUFFIX:
                    correct_dir = Path(video_dir)
                else:
                    self.main.messages.add(f"[Error] Unknown file type: {item.uri}")
                    continue

                year = item.date.year
                month = item.date.month
                day = item.date.day
                correct_path = (
                    correct_dir
                    / f"{year:04d}"
                    / f"{month:02d}"
                    / f"{day:02d}"
                    / filepath.name
                )
                correct_path = correct_path.with_suffix(ext)  # Normalize extension case

                if correct_path.exists():
                    self.main.messages.add(f"File already exists: {correct_path}")
                    continue

                try:
                    correct_path.parent.mkdir(parents=True, exist_ok=True)
                    old_md5 = item.uri_md5
                    shutil.move(filepath, correct_path)
                    # The cache is keyed on the uri hash, which changes with the
                    # path, so the old entries could never be hit again.
                    forget_thumbnail(old_md5, self.main.config.photos)
                    item.uri = str(correct_path)
                    item.uri_md5 = calculate_md5(item.uri)
                    item.data_xxhash = calculate_xxhash(correct_path)
                    need_update.append(item)
                    moved += 1
                    self.main.messages.add(
                        f"Moved from no-date: {filepath} → {correct_path}"
                    )
                except Exception as e:
                    logger.exception("Failed to move %s", filepath)
                    self.main.messages.add(f"[Error] Failed to move {filepath}: {e}")

            db.update_items_in_db(need_update)
            current += len(chunk)
            yield total, current

        self.main.messages.add(f"Total items in 'no-date': {total}")
        self.main.messages.add(f"Moved {moved} items to correct date folders")
