"""Extract the little animated preview shown when hovering a video.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from pathlib import Path

from tagorganizer.plugins import Plugin
from tagorganizer import config
from tagorganizer.widgets.helper import build_video_preview, preview_file

# Previews are built at the grid's default tile width; a hover shows them
# scaled to whatever the tile currently is.
PREVIEW_WIDTH = 150
CHUNK = 5


class VideoPreviews(Plugin):
    name = "Build Video Previews"
    description = "Extract a sprite sheet for every video that lacks one."
    category = "Maintenance"
    accepts_selection = True
    auto = True
    # A preview is cached under the item's md5, so hashing must have run first.
    after = ("Update Hashes in DB",)

    def run(self, ctx):
        """Incremental: an existing sheet is left alone, so interrupting the
        task loses nothing and re-running it is cheap."""
        items = [
            item
            for item in ctx.items()
            if Path(item.uri).suffix.lower() in config.VIDEO_SUFFIX
        ]
        total = len(items)
        done = 0
        built = 0
        skipped = 0

        for item in items:
            if ctx.cancelled:
                break
            if (
                item.uri_md5
                and preview_file(item.uri_md5, PREVIEW_WIDTH, ctx.photos).is_file()
            ):
                skipped += 1
            elif build_video_preview(item, PREVIEW_WIDTH, ctx.photos):
                built += 1
            else:
                skipped += 1
            done += 1
            if done % CHUNK == 0:
                yield total, done

        ctx.message(f"videos needing a preview: {total}")
        ctx.message(f"built {built}, skipped {skipped}")
        # Always yields at least once, so a library with no videos drives the
        # progress bar to completion instead of appearing to hang.
        yield total, done
