"""Fill in the md5 and content hashes items are missing.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from pathlib import Path

from .. import Plugin
from ...widgets.helper import calculate_md5, calculate_xxhash

CHUNK = 10


class UpdateHashes(Plugin):
    name = "Update Hashes in DB"
    description = "Compute md5 and content hashes for files that have none."
    category = "Maintenance"
    accepts_selection = True
    # A preview's cache key is the md5, so hashing has to have run before any
    # preview is built. This is also why it runs automatically after an import.
    auto = True

    def run(self, ctx):
        items = [
            item for item in ctx.items() if not item.uri_md5 or not item.data_xxhash
        ]
        total = len(items)
        done = 0
        hashed = 0
        pending = []

        for item in items:
            if ctx.cancelled:
                break
            path = Path(item.uri)
            if path.is_file():
                item.uri_md5 = calculate_md5(item.uri)
                item.data_xxhash = calculate_xxhash(path)
                pending.append(item)
                hashed += 1
            done += 1
            if len(pending) >= CHUNK:
                ctx.update(pending)
                pending = []
                yield total, done

        ctx.update(pending)
        ctx.message(f"items without hashes: {total}")
        ctx.message(f"added hashes to {hashed} items")
        yield total, done
