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

# The menu bar reads left to right, so the tasks reached for most often come
# first. Categories a plugin invents follow, alphabetically, so the order is
# stable rather than depending on which file happened to load first.
CATEGORY_ORDER = ("Maintenance", "Files", "Reports")


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
        self._disabled: set[str] = set()

    def add(self, plugin: Plugin) -> None:
        if not getattr(plugin, "name", ""):
            raise ValueError(
                f"{type(plugin).__name__} has no name; it would appear as a "
                "blank menu entry"
            )
        self._plugins.append(plugin)

    def set_disabled(self, names) -> None:
        """Switch plugins off by name.

        A disabled plugin stays in the registry rather than being dropped at
        load time: the settings window lists it so it can be switched back on,
        which is impossible if it was never loaded. Names matching nothing are
        ignored, since a plugin can be uninstalled while the config still
        mentions it.
        """
        self._disabled = set(names)

    def is_disabled(self, plugin: Plugin) -> bool:
        return plugin.name in self._disabled

    def every(self) -> list[Plugin]:
        """Every plugin, disabled ones included. For the settings window."""
        return list(self._plugins)

    def all(self) -> list[Plugin]:
        """Every enabled plugin, in registration order.

        A copy: the menu builder iterates this, and a caller sorting it in
        place would silently reorder the menu for everyone else.
        """
        return [p for p in self._plugins if not self.is_disabled(p)]

    def by_category(self) -> "OrderedDict[str, list[Plugin]]":
        """Enabled plugins grouped for the menu bar, in a deliberate order."""
        grouped: dict[str, list[Plugin]] = {}
        for plugin in self.all():
            grouped.setdefault(plugin.category, []).append(plugin)

        def rank(category):
            if category in CATEGORY_ORDER:
                return (0, CATEGORY_ORDER.index(category), "")
            return (1, 0, category)

        return OrderedDict(
            (category, grouped[category]) for category in sorted(grouped, key=rank)
        )

    def auto_plugins(self) -> list[Plugin]:
        """Those enabled plugins that also run themselves after an import."""
        return [plugin for plugin in self.all() if plugin.auto]
