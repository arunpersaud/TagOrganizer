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

    def test_a_photo_deleted_mid_run_does_not_lose_the_batch(self, items):
        """Tasks run for minutes over items loaded at the start; the user may
        delete one meanwhile, and the others in its batch must still be saved."""
        ctx = context(Scope.LIBRARY)
        first, second = list(ctx.items())[:2]
        db.delete_item(first.id)
        first.uri_md5 = "gone"
        second.uri_md5 = "kept"

        ctx.update([first, second])

        assert db.get_items_by_ids([second.id])[0].uri_md5 == "kept"
        assert db.get_items_by_ids([first.id]) == []

    def test_a_second_save_writes_only_the_new_change(self, items):
        """A task saving the same item twice must not replay its first change
        over an edit the user made in between."""
        ctx = context(Scope.LIBRARY)
        item = next(iter(ctx.items()))
        item.uri = "/p/moved.jpg"
        ctx.update([item])
        with Session(db.engine) as session:
            session.get(Item, item.id).uri = "/p/user.jpg"
            session.commit()
        item.uri_md5 = "abc"

        ctx.update([item])

        assert db.get_items_by_ids([item.id])[0].uri == "/p/user.jpg"

    def test_an_item_never_saved_is_refused(self, items):
        """update changes rows; it would otherwise drop a new item silently."""
        with pytest.raises(ValueError, match="never saved"):
            context(Scope.LIBRARY).update([Item(uri="/p/new.jpg")])

    def test_only_what_the_task_changed_is_written(self, items):
        """A date the user set while the hashing task ran must survive it."""
        from datetime import datetime

        ctx = context(Scope.LIBRARY)
        item = next(iter(ctx.items()))
        with Session(db.engine) as session:
            row = session.get(Item, item.id)
            row.date = datetime(2020, 1, 1)
            session.commit()
        item.uri_md5 = "abc"

        ctx.update([item])

        [saved] = db.get_items_by_ids([item.id])
        assert (saved.uri_md5, saved.date) == ("abc", datetime(2020, 1, 1))


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


class TestPluginQueries:
    """The queries the shipped plugins use, which keep them off the database."""

    def test_items_outside_the_library_are_found(self, items):
        """The fixture items live under /p, which is neither photos nor videos."""
        assert len(list(context(Scope.LIBRARY).items_outside_library())) == 4

    def test_items_inside_the_library_are_not(self, temp_db):
        with Session(temp_db) as session:
            # A native path, as add_directory stores it: backslashes on Windows.
            session.add(Item(uri=str(Path("/photos/2020/01/01/a.jpg"))))
            session.commit()
        assert list(context(Scope.LIBRARY).items_outside_library()) == []

    def test_items_under_no_date_are_found(self, temp_db):
        with Session(temp_db) as session:
            session.add(Item(uri="/photos/no-date/a.jpg"))
            session.add(Item(uri="/photos/2020/01/01/b.jpg"))
            session.commit()
        found = context(Scope.LIBRARY).items_under_no_date()
        assert [item.uri for item in found] == ["/photos/no-date/a.jpg"]

    def test_has_item_says_whether_a_path_is_recorded(self, items):
        ctx = context(Scope.LIBRARY)
        assert ctx.has_item("/p/0.jpg") is True
        assert ctx.has_item("/p/not-recorded.jpg") is False


class TestBuiltinsStayOffTheDatabase:
    """Shipped plugins reach data only through TaskContext.

    Every shipped plugin is loaded with the database module unavailable. A
    plugin that imports it, in any spelling, fails to load and is reported as
    broken. Imports are what this guards: a plugin reaching the database through
    a helper is the context's concern, not this test's.
    """

    def test_every_shipped_plugin_loads_without_the_database(self, monkeypatch):
        import sys

        import tagorganizer
        from tagorganizer.plugins.discovery import load_plugins, plugin_paths

        # `from tagorganizer import db` returns the package attribute before it
        # looks at sys.modules, so the attribute has to go as well.
        monkeypatch.delattr(tagorganizer, "db", raising=False)
        monkeypatch.setitem(sys.modules, "tagorganizer.db", None)

        _, broken = load_plugins([plugin_paths()[0]])

        assert [b.path.name for b in broken] == [], "a shipped plugin imports db"
