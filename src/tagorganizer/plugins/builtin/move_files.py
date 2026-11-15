"""Move files that live outside the configured library into it.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from pathlib import Path

from tagorganizer.plugins import Plugin
from tagorganizer.plugins.builtin._move import destination_for, move_item

CHUNK = 10


class MoveFiles(Plugin):
    name = "Move Files to Default Dirs"
    description = "Move files outside the configured directories into them."
    category = "Files"
    # Moving an arbitrary subset of a library invites confusion about what
    # just happened to which files.
    accepts_selection = False

    def run(self, ctx):
        items = ctx.items_outside_library()
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

            target = destination_for(item, ctx.photos, ctx.videos)
            if target is None:
                ctx.message(f"[Error] cannot handle {source.suffix} for {item.uri}")
                continue
            # Undated items are filed under no-date/, which FixNoDateFiles
            # empties once a date is found. That is the intended destination,
            # so this is a note, not an error.
            if not item.date:
                ctx.message(
                    f"[Note] item {item.uri} has no date; filing it under no-date"
                )

            if move_item(item, target, ctx):
                # Persisted at once. A failure partway through a batch used to
                # leave moved files the database did not know about.
                ctx.update([item])
                moved += 1

        ctx.message(f"items outside the library: {total}")
        ctx.message(f"moved {moved} items")
        yield total, done
