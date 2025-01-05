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

from qtpy.QtCore import QTimer
from more_itertools import chunked

from . import db
from .widgets.helper import load_exif


class TaskManager:
    def __init__(self):
        self.generators = deque()
        self.timer = QTimer()
        self.timer.timeout.connect(self.run_next_task)
        self.current_gen_index = 0

    def register_generator(self, gen):
        self.generators.append(gen)

    def start(self, interval=1000):
        self.timer.start(interval)

    def stop(self):
        self.timer.stop()

    def run_next_task(self):
        if not self.generators:
            self.stop()
            return

        gen = self.generators[0]
        try:
            next(gen)
        except StopIteration:
            self.generators.popleft()


def task_add_timestamp_to_db():
    print("[INFO] Updating timestamps in db")
    items = db.get_items_without_date()

    for chunk in chunked(items, 10):
        need_update = []
        for entry in chunk:
            filepath = Path(entry.uri)
            if not filepath.is_file():
                continue
            tags = load_exif(filepath)
            if "EXIF DateTimeOriginal" in tags:
                date_str = str(tags["EXIF DateTimeOriginal"])
                date_obj = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
                entry.date = date_obj
                need_update.append(entry)
        db.update_items_in_db(need_update)
        yield
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

    for chunk in chunked(items, 10):
        need_update = []
        for entry in chunk:
            filepath = Path(entry.uri)
            if not filepath.is_file():
                continue
            tags = load_exif(filepath)

            if "GPS GPSLongitude" in tags and "GPS GPSLatitude" in tags:
                lon_values = tags["GPS GPSLongitude"]
                lat_values = tags["GPS GPSLatitude"]

                lon_ref = tags.get("GPS GPSLongitudeRef", "E")
                lat_ref = tags.get("GPS GPSLatitudeRef", "N")

                lon = convert_to_degrees(lon_values, lon_ref)
                lat = convert_to_degrees(lat_values, lat_ref)

                entry.longitude = lon
                entry.latitude = lat

                need_update.append(entry)
        db.update_items_in_db(need_update)
        yield
    print("[INFO] Done updating geolocation in db")
