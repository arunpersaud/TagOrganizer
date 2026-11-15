"""Report files sitting in the library directories that were never imported.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from tagorganizer.plugins import Plugin

# The thumbnail cache lives beside the photos, and .DS_Store is noise: neither
# is a missing import, and reporting them would bury the real answers.
IGNORED = ("thumbnails", ".DS_Store")


class ListFilesNotInDb(Plugin):
    name = "Check for Files in Default Dirs"
    description = "List files in the library directories that are not in the database."
    category = "Reports"
    # Which files were never imported is a whole-library question.
    accepts_selection = False

    def run(self, ctx):
        groups = [("Photos", ctx.photos), ("Videos", ctx.videos)]
        files = []
        for label, root in groups:
            files.extend((label, path) for path in sorted(root.rglob("*")))

        total = len(files)
        done = 0
        missing = 0
        reported_label = None

        for label, path in files:
            if ctx.cancelled:
                break
            done += 1
            if done % 10 == 0:
                yield total, done
            if path.is_dir() or any(part in str(path) for part in IGNORED):
                continue
            if ctx.has_item(path):
                continue

            if label != reported_label:
                ctx.message(f"   {label} not in the database:")
                reported_label = label
            ctx.message(f"      {path}")
            missing += 1

        ctx.message(f"files on disk but not in the database: {missing}")
        yield total, done
