"""The unused tags report: tags no photo carries, anywhere in their subtree.

A parent such as People is in use when any tag under it is, even though no
photo carries People itself. Only reported; nothing is deleted.
"""

from pathlib import Path

import pytest
from sqlmodel import Session

from tagorganizer import db
from tagorganizer.models import Item, ItemTagLink, Tag
from tagorganizer.plugins.builtin.list_unused_tags import ListUnusedTags
from tagorganizer.plugins.context import TaskContext
from tagorganizer.scope import Scope


@pytest.fixture
def vocabulary(temp_db):
    """People > Alice (used), People > Bob, Old > Older, Beach (used), Empty."""
    with Session(temp_db) as session:
        roots = {name: Tag(name=name) for name in ("People", "Old", "Beach", "Empty")}
        session.add_all(roots.values())
        session.commit()
        children = {
            "Alice": Tag(name="Alice", parent_id=roots["People"].id),
            "Bob": Tag(name="Bob", parent_id=roots["People"].id),
            "Older": Tag(name="Older", parent_id=roots["Old"].id),
        }
        session.add_all(children.values())
        item = Item(uri="/p/a.jpg")
        session.add(item)
        session.commit()
        for tag in (children["Alice"], roots["Beach"]):
            session.add(ItemTagLink(item_id=item.id, tag_id=tag.id))
        session.commit()


def test_the_unused_tags_by_their_full_path(vocabulary):
    assert db.get_unused_tags() == ["Empty", "Old", "Old/Older", "People/Bob"]


def test_no_tags_means_nothing_to_report(temp_db):
    assert db.get_unused_tags() == []


def test_the_task_lists_them_and_counts(vocabulary, tmp_path):
    messages = []
    ctx = TaskContext(Scope.LIBRARY, Path(tmp_path), Path(tmp_path), messages.append)

    steps = list(ListUnusedTags().run(ctx))

    assert steps
    assert messages == [
        "Empty",
        "Old",
        "Old/Older",
        "People/Bob",
        "unused tags: 4",
    ]


def test_the_task_deletes_nothing(vocabulary, tmp_path):
    ctx = TaskContext(Scope.LIBRARY, Path(tmp_path), Path(tmp_path), lambda t: None)
    list(ListUnusedTags().run(ctx))
    assert len(db.get_all_tags()) == 7


def test_declaration():
    plugin = ListUnusedTags()
    assert plugin.category == "Reports"
    assert plugin.accepts_selection is False
    assert plugin.auto is False
