"""The plugin API.

A plugin declares how it appears in the app and implements ``run``, which is a
generator yielding ``(total, current)`` as it works. Everything it may touch
arrives through the context object it is handed - plugins never import ``db``,
which is what lets the database layer keep changing without breaking them.

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

from collections import OrderedDict


class Plugin:
    """One unit of work the user can run.

    Subclass it, set ``name``, and implement ``run``. The shipped tasks are
    written against exactly this interface, so anything they can do, a plugin
    in the user's own plugins directory can do too.
    """

    #: Menu entry text. Required.
    name: str = ""
    #: Shown as the menu tooltip and in the settings list.
    description: str = ""
    #: Which menu this appears under.
    category: str = "Tasks"
    #: False for work that only makes sense over the whole library.
    accepts_selection: bool = True
    #: Also run after images are imported.
    auto: bool = False

    def run(self, ctx):
        """Do the work, yielding ``(total, current)`` as progress."""
        raise NotImplementedError(f"{type(self).__name__} does not implement run()")


class Registry:
    """Every plugin the app knows about, in a stable order.

    The Tasks menu, the post-import auto chain and the settings page are all
    built from this one list, so they cannot drift apart the way three
    hand-maintained lists did.
    """

    def __init__(self):
        self._plugins = []

    def add(self, plugin: Plugin) -> None:
        if not getattr(plugin, "name", ""):
            raise ValueError(
                f"{type(plugin).__name__} has no name; it would appear as a "
                "blank menu entry"
            )
        self._plugins.append(plugin)

    def all(self) -> list[Plugin]:
        """Every plugin, in registration order.

        A copy: the menu builder iterates this, and a caller sorting it in
        place would silently reorder the menu for everyone else.
        """
        return list(self._plugins)

    def by_category(self) -> "OrderedDict[str, list[Plugin]]":
        """Plugins grouped for the menu bar, categories in first-seen order."""
        grouped = OrderedDict()
        for plugin in self._plugins:
            grouped.setdefault(plugin.category, []).append(plugin)
        return grouped

    def auto_plugins(self) -> list[Plugin]:
        """Those that also run themselves after an import."""
        return [plugin for plugin in self._plugins if plugin.auto]
