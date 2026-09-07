"""Read the original capture date out of each file's EXIF.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from datetime import datetime
from pathlib import Path

from tagorganizer.plugins import Plugin
from tagorganizer.metadata import date_from_filename, video_date
from tagorganizer.widgets.helper import load_exif

CHUNK = 10


class UpdateTimestamps(Plugin):
    name = "Update Timestamps in DB"
    description = "Read the capture date from EXIF for items that have none."
    category = "Maintenance"
    accepts_selection = True

    def _date_for(self, path, ctx):
        """EXIF, then the container, then the filename.

        EXIF first because it is the camera's own record of when the shutter
        opened, and the container next because it is still the file's own
        record. The filename comes last: it is the only one of the three that
        is a guess.
        """
        tags = load_exif(path)
        if "EXIF DateTimeOriginal" in tags:
            text = str(tags["EXIF DateTimeOriginal"])
            try:
                return datetime.strptime(text, "%Y:%m:%d %H:%M:%S")
            except ValueError:
                # A camera that writes a malformed date should not stop the
                # whole run; say so and fall through to the other readers.
                ctx.message(f"Cannot parse date '{text}' for {path}")

        from_container = video_date(path)
        if from_container is not None:
            return from_container

        return date_from_filename(path.name)

    def run(self, ctx):
        items = [item for item in ctx.items() if item.date is None]
        total = len(items)
        done = 0
        fixed = 0
        pending = []

        for item in items:
            if ctx.cancelled:
                break
            path = Path(item.uri)
            if path.is_file():
                found = self._date_for(path, ctx)
                if found is not None:
                    item.date = found
                    pending.append(item)
                    fixed += 1
            done += 1
            if len(pending) >= CHUNK:
                ctx.update(pending)
                pending = []
                yield total, done

        ctx.update(pending)
        ctx.message(f"items without a timestamp: {total}")
        ctx.message(f"added a timestamp to {fixed} items")
        yield total, done
