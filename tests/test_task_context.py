"""The API boundary plugins see.

Everything a plugin may touch goes through this object, so these tests are the
contract: plugins never import db, and this is what keeps that possible.
"""

from pathlib import Path

import pytest
from sqlmodel import Session, select

from tagorganizer import db
from tagorganizer.models import Item, ItemTagLink, Tag
from tagorganizer.plugins.context import TaskContext
from tagorganizer.scope import Scope, resolve_scope


@pytest.fixture
def items(temp_db):
    with Session(temp_db) as session:
        rows = [Item(uri=f"/p/{i}.jpg") for i in range(4)]
        for row in rows:
            session.add(row)
        session.commit()
        for row in rows:
            session.refresh(row)
        return [row.id for row in rows]


def context(scope, sink=None):
    return TaskContext(
        scope=scope,
        photos=Path("/photos"),
        videos=Path("/videos"),
        message_sink=sink if sink is not None else (lambda text: None),
    )


class TestItems:
    def test_the_library_scope_yields_everything(self, items):
        assert len(list(context(Scope.LIBRARY).items())) == 4

    def test_a_selection_yields_only_those(self, items):
        found = list(context(resolve_scope(items[:2])).items())
        assert sorted(i.id for i in found) == sorted(items[:2])

    def test_count_matches_what_items_yields(self, items):
        ctx = context(resolve_scope(items[:3]))
        assert ctx.count() == len(list(ctx.items()))

    def test_count_of_the_whole_library(self, items):
        assert context(Scope.LIBRARY).count() == 4


class TestTagging:
    def test_add_tag_creates_the_tag_and_links_it(self, items):
        ctx = context(Scope.LIBRARY)
        item = next(iter(ctx.items()))
        ctx.add_tag(item, "Alice")

        with db.new_session() as session:
            tag = session.exec(select(Tag).where(Tag.name == "Alice")).first()
            assert tag is not None
            link = session.exec(
                select(ItemTagLink).where(ItemTagLink.tag_id == tag.id)
            ).first()
            assert link.item_id == item.id

    def test_adding_the_same_tag_twice_is_harmless(self, items):
        """A plugin re-run over the same photos must not duplicate links.

        ItemTagLink has a composite primary key, so a second insert would
        raise rather than being ignored.
        """
        ctx = context(Scope.LIBRARY)
        item = next(iter(ctx.items()))
        ctx.add_tag(item, "Alice")
        ctx.add_tag(item, "Alice")

        with db.new_session() as session:
            assert len(session.exec(select(ItemTagLink)).all()) == 1

    def test_tag_lookup_folds_case_like_the_rest_of_the_app(self, items):
        """Otherwise a plugin would create a second 'alice' beside 'Alice'."""
        ctx = context(Scope.LIBRARY)
        item = next(iter(ctx.items()))
        ctx.add_tag(item, "Alice")
        ctx.add_tag(item, "alice")

        with db.new_session() as session:
            assert len(session.exec(select(Tag)).all()) == 1

    def test_two_items_can_share_a_tag(self, items):
        ctx = context(Scope.LIBRARY)
        first, second = list(ctx.items())[:2]
        ctx.add_tag(first, "Beach")
        ctx.add_tag(second, "Beach")

        with db.new_session() as session:
            assert len(session.exec(select(ItemTagLink)).all()) == 2
            assert len(session.exec(select(Tag)).all()) == 1


class TestUpdate:
    def test_changes_are_persisted(self, items):
        ctx = context(Scope.LIBRARY)
        item = next(iter(ctx.items()))
        item.uri_md5 = "abc"
        ctx.update([item])

        assert db.get_items_by_ids([item.id])[0].uri_md5 == "abc"

    def test_updating_nothing_is_harmless(self, items):
        context(Scope.LIBRARY).update([])


class TestMessagesAndCancellation:
    def test_messages_reach_the_sink(self, items):
        seen = []
        context(Scope.LIBRARY, seen.append).message("hello")
        assert seen == ["hello"]

    def test_not_cancelled_initially(self, items):
        assert context(Scope.LIBRARY).cancelled is False

    def test_cancel_flips_the_flag(self, items):
        ctx = context(Scope.LIBRARY)
        ctx.cancel()
        assert ctx.cancelled is True


class TestPaths:
    def test_the_configured_directories_are_available(self, items):
        ctx = context(Scope.LIBRARY)
        assert ctx.photos == Path("/photos")
        assert ctx.videos == Path("/videos")
