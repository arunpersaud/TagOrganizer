"""Delete cached thumbnails that nothing in the library points at.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from tagorganizer.plugins import Plugin
from tagorganizer.widgets.helper import cached_hashes


class PruneThumbnailCache(Plugin):
    name = "Clear Unused Thumbnails"
    description = (
        "Delete cached thumbnails and previews for photos no longer in the library."
    )
    category = "Maintenance"
    # Library-only by necessity, not preference: against a selection every
    # unselected photo's cache would look orphaned and be deleted.
    accepts_selection = False

    def run(self, ctx):
        known = {item.uri_md5 for item in ctx.items() if item.uri_md5}

        cached = list(cached_hashes(ctx.photos))
        total = len(cached)
        done = 0
        removed = 0
        freed = 0

        for md5, path in cached:
            if ctx.cancelled:
                break
            done += 1
            if md5 not in known:
                try:
                    freed += path.stat().st_size
                    path.unlink()
                    removed += 1
                except OSError as error:
                    ctx.message(f"could not remove {path}: {error}")
            if done % 50 == 0:
                yield total, done

        ctx.message(f"cached files: {total}")
        ctx.message(f"removed {removed}, freeing {freed // 1024} KiB")
        yield total, done
