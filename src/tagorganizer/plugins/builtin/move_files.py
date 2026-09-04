"""Move files that live outside the configured library into it.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from pathlib import Path

from tagorganizer.plugins import Plugin
from tagorganizer import config, db
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
        items = db.get_all_items_not_in_dir([ctx.photos, ctx.videos], config.ALL_SUFFIX)
        total = len(items)
        done = 0
        moved = 0
        pending = []

        for item in items:
            if ctx.cancelled:
                break
            done += 1
            source = Path(item.uri)
            if not source.is_file():
                ctx.message(f"[Error] item {item.uri} does not exist")
                continue

            target = destination_for(item, ctx.photos, ctx.videos)
            if target is None:
                ctx.message(f"[Error] cannot handle {source.suffix} for {item.uri}")
                continue
            if not item.date:
                ctx.message(f"[Error] item {item.uri} has no date set")

            if move_item(item, target, ctx):
                pending.append(item)
                moved += 1
            if len(pending) >= CHUNK:
                ctx.update(pending)
                pending = []
                yield total, done

        ctx.update(pending)
        ctx.message(f"items outside the library: {total}")
        ctx.message(f"moved {moved} items")
        yield total, done
