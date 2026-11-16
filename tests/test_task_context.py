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
            session.add(Item(uri="/photos/2020/01/01/a.jpg"))
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

    An AST check rather than a behavioural one: the point is the import, and a
    plugin that reaches db through a helper would pass a behavioural test.
    """

    def test_no_builtin_plugin_imports_db(self):
        import ast
        from pathlib import Path

        import tagorganizer.plugins.builtin as builtin

        offenders = []
        for path in sorted(Path(builtin.__file__).parent.glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom):
                    names = [alias.name for alias in node.names]
                    module = node.module or ""
                    if module == "tagorganizer.db" or (
                        module in ("tagorganizer", "..", ".", "..db") and "db" in names
                    ):
                        offenders.append(f"{path.name}:{node.lineno}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "tagorganizer.db":
                            offenders.append(f"{path.name}:{node.lineno}")
        assert offenders == []
