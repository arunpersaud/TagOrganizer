"""Read the original capture date out of each file's EXIF.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from datetime import datetime
from pathlib import Path

from tagorganizer.plugins import Plugin
from tagorganizer.widgets.helper import load_exif

CHUNK = 10


class UpdateTimestamps(Plugin):
    name = "Update Timestamps in DB"
    description = "Read the capture date from EXIF for items that have none."
    category = "Maintenance"
    accepts_selection = True

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
                tags = load_exif(path)
                if "EXIF DateTimeOriginal" in tags:
                    date_str = str(tags["EXIF DateTimeOriginal"])
                    try:
                        item.date = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
                    except ValueError:
                        # A camera that writes a malformed date should not stop
                        # the whole run; say so and carry on.
                        ctx.message(f"Cannot parse date '{date_str}' for {item.uri}")
                    else:
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
