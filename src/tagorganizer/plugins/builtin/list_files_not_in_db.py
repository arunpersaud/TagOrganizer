"""Report files sitting in the library directories that were never imported.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from tagorganizer.plugins import Plugin

# The thumbnail cache lives beside the photos, and .DS_Store is noise: neither
# is a missing import, and reporting them would bury the real answers.
IGNORED = ("thumbnails", ".DS_Store")


def _is_ignored(root, path) -> bool:
    """Whether a file is cache or OS noise rather than a possible import.

    Matched on whole path components below the library root. A substring test
    against the full path hid any photo whose folder name merely contained
    "thumbnails", and judged the directories above the library as well.
    """
    return any(part in IGNORED for part in path.relative_to(root).parts)


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
            files.extend((label, root, path) for path in sorted(root.rglob("*")))

        total = len(files)
        done = 0
        missing = 0
        reported_label = None

        for label, root, path in files:
            if ctx.cancelled:
                break
            done += 1
            if done % 10 == 0:
                yield total, done
            if path.is_dir() or _is_ignored(root, path):
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
