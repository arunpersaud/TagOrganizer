"""What a task acts on: the whole library, or a chosen set of items.

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

from dataclasses import dataclass


@dataclass(frozen=True)
class Scope:
    """A set of item ids, or None meaning every item in the library.

    Frozen because a scope is decided once, when the task is queued. A task can
    run for minutes while the user carries on clicking, so a scope that could
    drift underneath it would act on photos the user never chose.
    """

    item_ids: tuple[int, ...] | None = None

    @property
    def is_selection(self) -> bool:
        return self.item_ids is not None

    def describe(self) -> str:
        """Name this scope for the status bar.

        A single menu entry acts on the selection or the library depending on
        what is selected, so the message has to say which it chose.
        """
        if not self.is_selection:
            return "the whole library"
        count = len(self.item_ids)
        return f"{count} selected item" + ("" if count == 1 else "s")


# The whole library. A module-level singleton rather than a class attribute:
# a frozen dataclass cannot hold an instance of itself at class-creation time.
Scope.LIBRARY = Scope(None)


def resolve_scope(selected_ids) -> Scope:
    """A task acts on the selection when there is one, the library otherwise."""
    if not selected_ids:
        return Scope.LIBRARY
    return Scope(tuple(selected_ids))
