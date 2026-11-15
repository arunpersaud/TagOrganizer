"""Move files out of 'no-date' once their capture date is known.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from pathlib import Path

from tagorganizer.plugins import Plugin
from tagorganizer.plugins.builtin._move import destination_for, move_item

CHUNK = 10


class FixNoDateFiles(Plugin):
    name = "Move Files with new date set"
    description = "Move items out of 'no-date' once a date has been found."
    category = "Files"
    accepts_selection = False

    def run(self, ctx):
        items = ctx.items_under_no_date()
        total = len(items)
        done = 0
        moved = 0

        for item in items:
            if ctx.cancelled:
                break
            done += 1
            if done % CHUNK == 0:
                yield total, done
            source = Path(item.uri)
            if not source.is_file():
                ctx.message(f"[Error] item {item.uri} does not exist")
                continue
            if not item.date:
                ctx.message(f"[Skip] item {item.uri} still has no date")
                continue

            target = destination_for(item, ctx.photos, ctx.videos)
            if target is None:
                ctx.message(f"[Error] Unknown file type: {item.uri}")
                continue

            if move_item(item, target, ctx):
                # Persisted at once; see MoveFiles.
                ctx.update([item])
                moved += 1

        ctx.message(f"items in 'no-date': {total}")
        ctx.message(f"moved {moved} items to dated folders")
        yield total, done
