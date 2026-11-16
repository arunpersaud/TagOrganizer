"""Which drag-and-drop moves in the tag tree are allowed, decided without Qt.

The tree widget only knows what was dropped where. Whether the database may
take that drop - reserved filter buttons cannot be moved, and a tag cannot be
made to sit under one of its own descendants - is a rule about the tags, so
it lives here where a test can call it directly.
"""

from collections.abc import Iterable, Mapping


def descendants(parents: Mapping[int, int | None], tag_id: int) -> set[int]:
    """Every tag below ``tag_id``, at any depth.

    ``parents`` maps each tag id to its parent id, or None at the top level.
    """
    children: dict[int, list[int]] = {}
    for child, parent in parents.items():
        if parent is not None:
            children.setdefault(parent, []).append(child)

    found: set[int] = set()
    pending = list(children.get(tag_id, []))
    while pending:
        current = pending.pop()
        if current in found:
            # Stored data can already contain a loop; do not spin on it.
            continue
        found.add(current)
        pending.extend(children.get(current, []))
    return found


def refuse_move(
    moving: Iterable[int | None],
    target: int | None,
    target_is_reserved: bool,
    parents: Mapping[int, int | None],
) -> str | None:
    """Why this drop must not happen, or None if it may.

    ``moving`` holds the ids of the dragged tags; a reserved filter button has
    no id and is passed as None. ``target`` is the tag dropped onto, or None
    for a drop at the top level, which ``target_is_reserved`` tells apart from
    a drop onto a reserved button.

    Refusing the whole drop, rather than moving the tags that are allowed to
    move, is deliberate: a multi-select that is half refused would leave the
    user unsure which tags went where.
    """
    moving = list(moving)
    if not moving:
        return "Nothing to move."
    if any(tag_id is None for tag_id in moving) or target_is_reserved:
        return "The built-in filter tags cannot be moved or used as a parent."
    if target is not None and target in moving:
        return "A tag cannot be moved under itself."
    if target is not None:
        for tag_id in moving:
            if target in descendants(parents, tag_id):
                return (
                    "That would make a tag its own ancestor; "
                    "move the parent first, or pick another target."
                )
    return None
