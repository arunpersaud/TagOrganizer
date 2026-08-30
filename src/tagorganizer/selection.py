"""The set of items the user has picked.

Kept out of any widget: the grid is one of several things that will feed this -
selecting on the map is next - and a selection owned by the widget that happens
to be showing one page of it is the wrong shape for that.
"""

from collections.abc import Iterable, Iterator


class Selection:
    """An insertion-ordered set of item ids.

    Ids rather than Item objects: only the id is ever needed, the objects the
    previous list held were detached from their session and could go stale, and
    membership has to be O(1) because show_images tests it once per tile on
    every page render - which a range selection can make expensive.
    """

    def __init__(self, item_ids: Iterable[int] | None = None):
        # A dict preserves insertion order and gives O(1) membership; the
        # standard library has no ordered set.
        self._ids: dict[int, None] = {}
        if item_ids is not None:
            self.add_many(item_ids)

    def add(self, item_id: int) -> None:
        self._ids[item_id] = None

    def add_many(self, item_ids: Iterable[int]) -> None:
        for item_id in item_ids:
            self._ids[item_id] = None

    def discard(self, item_id: int) -> None:
        self._ids.pop(item_id, None)

    def toggle(self, item_id: int) -> bool:
        """Flip one id. Returns True when it is now selected."""
        if item_id in self._ids:
            del self._ids[item_id]
            return False
        self._ids[item_id] = None
        return True

    def clear(self) -> None:
        self._ids.clear()

    def ids(self) -> list[int]:
        return list(self._ids)

    def __contains__(self, item_id: int) -> bool:
        return item_id in self._ids

    def __len__(self) -> int:
        return len(self._ids)

    def __iter__(self) -> Iterator[int]:
        return iter(self._ids)
