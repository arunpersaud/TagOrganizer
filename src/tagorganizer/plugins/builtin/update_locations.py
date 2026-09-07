"""Read GPS coordinates out of each file's EXIF.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from pathlib import Path

from tagorganizer.plugins import Plugin
from tagorganizer.metadata import video_gps
from tagorganizer.widgets.helper import load_exif

CHUNK = 10


def to_degrees(value, ref) -> float:
    """EXIF stores coordinates as degrees, minutes and seconds."""
    degrees = float(value.values[0])
    minutes = float(value.values[1])
    seconds = float(value.values[2])

    result = degrees + (minutes / 60.0) + (seconds / 3600.0)
    if ref not in ["E", "N"]:
        result = -result
    return result


class UpdateLocations(Plugin):
    name = "Update Locations in DB"
    description = "Read GPS coordinates from EXIF for items that have none."
    category = "Maintenance"
    accepts_selection = True

    def run(self, ctx):
        items = [
            item
            for item in ctx.items()
            if item.latitude is None or item.longitude is None
        ]
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
                if "GPS GPSLongitude" in tags and "GPS GPSLatitude" in tags:
                    item.longitude = to_degrees(
                        tags["GPS GPSLongitude"],
                        str(tags.get("GPS GPSLongitudeRef", "E")),
                    )
                    item.latitude = to_degrees(
                        tags["GPS GPSLatitude"],
                        str(tags.get("GPS GPSLatitudeRef", "N")),
                    )
                    pending.append(item)
                    fixed += 1
                else:
                    # No EXIF GPS. Videos keep theirs in a container box that
                    # exifread does not read at all.
                    from_container = video_gps(path)
                    if from_container is not None:
                        item.latitude, item.longitude = from_container
                        pending.append(item)
                        fixed += 1
            done += 1
            if len(pending) >= CHUNK:
                ctx.update(pending)
                pending = []
                yield total, done

        ctx.update(pending)
        ctx.message(f"items without a location: {total}")
        ctx.message(f"added a location to {fixed} items")
        yield total, done
