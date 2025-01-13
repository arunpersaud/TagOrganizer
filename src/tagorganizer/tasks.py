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
from .widgets.helper import load_exif


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
        self.register_generator(task_add_timestamp_to_db())
        self.start()

    def db_update_locations(self):
        self.register_generator(task_add_geolocation_to_db())
        self.start()

    def move_files(self):
        self.register_generator(
            task_move_files(self.main.config.photos, self.main.config.videos)
        )
        self.start()


def task_add_timestamp_to_db():
    print("[INFO] Updating timestamps in db")
    items = db.get_items_without_date()

    total = len(items)
    current = 0
    N = 10

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
                    print(f"Cannot parse date '{date_str}' for {entry.uri}")
                    continue
                entry.date = date_obj
                need_update.append(entry)
        db.update_items_in_db(need_update)
        current += N
        yield total, current
    print("[INFO] Done updating timestamps in db")


def convert_to_degrees(value, ref):
    d = float(value.values[0])
    m = float(value.values[1])
    s = float(value.values[2])

    f = d + (m / 60.0) + (s / 3600.0)
    if ref not in ["E", "N"]:
        f = -f
    return f


def task_add_geolocation_to_db():
    print("[INFO] Updating geolocations in db")
    items = db.get_items_without_location()

    total = len(items)
    current = 0
    N = 10

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

                lon = convert_to_degrees(lon_values, lon_ref)
                lat = convert_to_degrees(lat_values, lat_ref)

                entry.longitude = lon
                entry.latitude = lat

                need_update.append(entry)
        db.update_items_in_db(need_update)
        current += N
        yield total, current
    print("[INFO] Done updating geolocation in db")


def task_move_files(photo_dir: Path, video_dir: Path):
    print("[INFO] sorting files into default dirs")
    items = db.get_all_items_not_in_dir([photo_dir, video_dir], ["jpg", "jpeg"])

    total = len(items)
    current = 0
    N = 10

    print("   ", photo_dir)
    print("   ", video_dir)

    for chunk in chunked(items, N):
        need_update = []
        for item in chunk:
            filepath = Path(item.uri)
            if not filepath.is_file():
                print(f"[Error] item {item.uri} does not exist")
                continue

            ext = filepath.suffix.lower()
            if ext in [".jpg", ".jpeg"]:
                correct_dir = Path(photo_dir)
            elif ext in [".mp4", ".avi", ".mov"]:
                correct_dir = Path(video_dir)
            else:
                print(f"[Error] item {item.uri} cannot handle {ext}")
                continue

            if item.date:
                year = item.date.year
                month = item.date.month
                day = item.date.day
            else:
                print(f"[Error] item {item.uri} has no date set")
                continue

            # Construct the new directory path using the date components
            correct_path = (
                correct_dir
                / f"{year:04d}"
                / f"{month:02d}"
                / f"{day:02d}"
                / filepath.name
            )
            # lower the case for the extension
            correct_path = correct_path.with_suffix(ext)

            if correct_path.exists():
                print(f"File already exists in the correct directory: {correct_path}")
                continue

            # Move the file
            try:
                correct_path.parent.mkdir(parents=True, exist_ok=True)

                shutil.move(filepath, correct_path)
                item.uri = str(correct_path)
                need_update.append(item)
                print(f"Moved {filepath} to {correct_path}")
            except Exception:
                print(f"Failed to move {filepath} to {correct_path}")
        db.update_items_in_db(need_update)
        current += N
        yield total, current
    print("[INFO] done sorting files into default dirs")
