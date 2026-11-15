"""Report items whose files live outside the configured library.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from pathlib import Path

from tagorganizer.plugins import Plugin
from tagorganizer import config, db


class ListFilesOutsideDirs(Plugin):
    name = "Check for Files outside of Default Dirs"
    description = "List items stored outside the configured directories."
    category = "Reports"
    accepts_selection = False

    def run(self, ctx):
        items = db.get_all_items_not_in_dir([ctx.photos, ctx.videos], config.ALL_SUFFIX)
        total = len(items)
        done = 0

        for item in items:
            if ctx.cancelled:
                break
            done += 1
            if done % 10 == 0:
                yield total, done
            path = Path(item.uri)
            if not path.is_file():
                ctx.message(f"[Error] item {item.uri} does not exist")
            else:
                ctx.message(f"File: {path}")

        ctx.message(f"items outside the photo/video directories: {total}")
        yield total, done
