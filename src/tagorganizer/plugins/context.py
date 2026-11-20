"""What a plugin is allowed to touch.

This class is the whole public API. Plugins never import ``db``, so the
database layer stays free to change as long as these methods keep their
meaning. Anything a plugin needs that is not here is a gap in the API rather
than a reason to reach past it.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer.

TagOrganizer is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or (at
your option) any later version.

TagOrganizer is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with TagOrganizer. If not, see <https://www.gnu.org/licenses/>.
"""

import threading
from pathlib import Path

from .. import config, db
from ..models import ItemTagLink
from ..scope import Scope


class TaskContext:
    """Handed to a plugin's ``run``; the only thing it should need."""

    def __init__(
        self,
        scope: Scope,
        photos: Path,
        videos: Path,
        message_sink,
        sharing_profiles: tuple[str, ...] = (),
    ):
        self.scope = scope
        self.photos = photos
        self.videos = videos
        # Other profiles that keep their photos in the same folder. Their
        # items are not visible through items(), so a plugin that acts on the
        # shared folder as a whole must check this first.
        self.sharing_profiles = tuple(sharing_profiles)
        self._message_sink = message_sink
        # An Event rather than a bool: it is set on the GUI thread and read on
        # the worker, and the Event makes that visibility guarantee explicit.
        self._cancelled = threading.Event()

    def items(self):
        """Every item in scope.

        The whole set is loaded rather than streamed: the tasks this replaces
        already worked that way, and a plugin that filters in Python needs the
        list anyway.
        """
        return iter(db.get_all_items(self.scope))

    def add_tag(self, item, name: str) -> None:
        """Tag an item, creating the tag if it is new.

        Goes through db.add_tag, so hierarchy and case-insensitive lookup
        behave exactly as they do when the user tags by hand - a plugin must
        not be able to create a second "alice" beside an existing "Alice".

        Linking is skipped when the link already exists: ItemTagLink has a
        composite primary key, so re-running a plugin over the same photos
        would otherwise raise instead of being a no-op.
        """
        tag_id = db.add_tag(name)
        with db.new_session() as session:
            if session.get(ItemTagLink, (item.id, tag_id)) is None:
                session.add(ItemTagLink(item_id=item.id, tag_id=tag_id))
                session.commit()

    def items_under_no_date(self):
        """Items whose file sits in a 'no-date' folder, awaiting a date."""
        return db.get_items_under_no_date()

    def items_outside_library(self):
        """Items stored outside the configured photo and video folders."""
        return db.get_all_items_not_in_dir(
            [self.photos, self.videos], config.ALL_SUFFIX
        )

    def unused_tags(self) -> list[str]:
        """Full paths of the tags no photo carries anywhere in their subtree."""
        return db.get_unused_tags()

    def has_item(self, path) -> bool:
        """Whether a file on disk is already recorded as an item."""
        return db.check_item_in_db(str(path)) is not None

    def update(self, items) -> None:
        """Persist the changes made to items from items() and the like.

        Only items loaded from the library; a new Item raises ValueError.
        """
        if items:
            db.update_items_in_db(items)

    def save_face_counts(self, items) -> None:
        """Store the face_count of each item, skipping any deleted meanwhile."""
        db.set_face_counts([(item.id, item.face_count) for item in items])

    def message(self, text: str) -> None:
        """Say something in the status bar."""
        self._message_sink(text)

    @property
    def cancelled(self) -> bool:
        """True once the user has stopped the task; check it between yields."""
        return self._cancelled.is_set()

    def cancel(self) -> None:
        """Ask the plugin to stop. Called by the runner, not by plugins."""
        self._cancelled.set()
