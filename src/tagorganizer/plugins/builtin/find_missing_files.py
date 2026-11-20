"""Record which library entries no longer have a file on disk.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from pathlib import Path

from tagorganizer.plugins import Plugin

CHUNK = 100


class FindMissingFiles(Plugin):
    name = "Find Missing Files"
    description = (
        "Check that every photo's file is still on disk, for the Missing file filter."
    )
    category = "Maintenance"
    accepts_selection = True

    def run(self, ctx):
        items = list(ctx.items())
        total = len(items)
        missing = 0
        done = 0
        pending = []

        for item in items:
            if ctx.cancelled:
                break
            done += 1
            gone = not Path(item.uri).is_file()
            missing += gone
            # Assigned even when unchanged: an item never checked is None, and
            # it has been checked now.
            item.file_missing = gone
            pending.append(item)
            if len(pending) >= CHUNK:
                ctx.update(pending)
                pending = []
            yield total, done

        ctx.update(pending)
        if done < total:
            ctx.message(f"missing: {missing} of {done} checked (cancelled)")
        else:
            ctx.message(f"missing: {missing} of {total}")
        if missing:
            # Nothing is removed here: a drive that is not plugged in looks
            # exactly like a deleted file.
            ctx.message(
                "Show them with the Missing file filter. Check the drive is "
                "mounted before removing them from the library."
            )
