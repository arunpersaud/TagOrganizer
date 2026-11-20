"""List the tags that no photo carries.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

from tagorganizer.plugins import Plugin


class ListUnusedTags(Plugin):
    name = "List Unused Tags"
    description = "List the tags no photo carries, to tidy up in the tag editor."
    category = "Reports"
    # Whether a tag is used anywhere is a whole-library question.
    accepts_selection = False

    def run(self, ctx):
        unused = ctx.unused_tags()
        total = len(unused)
        for done, name in enumerate(unused, start=1):
            if ctx.cancelled:
                break
            ctx.message(name)
            yield total, done
        ctx.message(f"unused tags: {total}")
        yield total, total
