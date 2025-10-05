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

from collections import deque
from datetime import datetime
from pathlib import Path
import shutil

from qtpy.QtWidgets import QProgressBar, QLabel
from qtpy.QtCore import QTimer
from more_itertools import chunked

from . import db
from . import config
from .widgets.helper import load_exif, calculate_md5, calculate_xxhash


class TaskManager:
    def __init__(self, main):
        self.main = main

        self.generators = deque()
        self.timer = QTimer()
        self.timer.timeout.connect(self.run_next_task)
        self.current_gen_index = 0

        self.progressbar_label = QLabel("Task")
        self.progressbar = QProgressBar()
        self.progressbar.setMaximumWidth(200)
        self.progressbar_label.setVisible(False)
        self.progressbar.setVisible(False)

    def register_widgets(self, statusbar):
        statusbar.addPermanentWidget(self.progressbar_label)
        statusbar.addPermanentWidget(self.progressbar)

    def register_generator(self, gen):
        self.generators.append(gen)

    def start(self, interval=500):
        self.timer.start(interval)
        self.progressbar_label.setVisible(True)
        self.progressbar.setVisible(True)

    def stop(self):
        self.timer.stop()
        self.generators = deque()
        self.progressbar_label.setVisible(False)
        self.progressbar.setVisible(False)
        self.main.messages.add("Task done")

    def run_next_task(self):
        if not self.generators:
            self.stop()
            return

        gen = self.generators[0]
        try:
            total, current = next(gen)
            self.progressbar.setMaximum(total)
            self.progressbar.setValue(current)
        except StopIteration:
            self.generators.popleft()
            if not self.generators:
                self.progressbar_label.setVisible(False)
                self.progressbar.setVisible(False)

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

                    shutil.move(filepath, correct_path)
                    item.uri = str(correct_path)
                    item.uri_md5 = calculate_md5(item.uri)
                    item.data_xxhash = calculate_xxhash(correct_path)
                    need_update.append(item)
                    moved += 1
                    self.main.messages.add(f"Moved {filepath} to {correct_path}")
                except Exception:
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
                res = db.check_item_in_db(str(file))
                if res is None:
                    self.main.messages.add(f"      {file}")
            current += N
            yield total, current

    def task_fix_no_date_files(self, photo_dir: Path, video_dir: Path):
        """Move items from 'no-date' to their correct date-based location if date is now available."""
        self.main.messages.add("Task: Moving files out of 'no-date' if date is now set")

        # Find all items whose path includes 'no-date'
        items = db.get_all_items_with_location()  # Use a broad search
        items = [
            item
            for item in items
            if "/no-date/" in item.uri or "\\no-date\\" in item.uri
        ]

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
                    shutil.move(filepath, correct_path)

                    item.uri = str(correct_path)
                    item.uri_md5 = calculate_md5(item.uri)
                    item.data_xxhash = calculate_xxhash(correct_path)
                    need_update.append(item)
                    moved += 1
                    self.main.messages.add(
                        f"Moved from no-date: {filepath} → {correct_path}"
                    )
                except Exception as e:
                    self.main.messages.add(f"[Error] Failed to move {filepath}: {e}")

            db.update_items_in_db(need_update)
            current += len(chunk)
            yield total, current

        self.main.messages.add(f"Total items in 'no-date': {total}")
        self.main.messages.add(f"Moved {moved} items to correct date folders")
