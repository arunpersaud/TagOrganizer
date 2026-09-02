"""Tasks restricted to a selection must touch only the selected rows."""

import pytest
from sqlmodel import Session

from tagorganizer import db
from tagorganizer.models import Item
from tagorganizer.scope import resolve_scope


@pytest.fixture
def items(temp_db):
    with Session(temp_db) as session:
        rows = [Item(uri=f"/p/{i}.jpg") for i in range(5)]
        for row in rows:
            session.add(row)
        session.commit()
        for row in rows:
            session.refresh(row)
        return [row.id for row in rows]


class TestHashQueryScope:
    def test_the_library_scope_returns_everything(self, items):
        assert len(db.get_items_without_hashes()) == 5

    def test_a_selection_returns_only_those_items(self, items):
        found = db.get_items_without_hashes(resolve_scope(items[:2]))
        assert sorted(i.id for i in found) == sorted(items[:2])

    def test_a_selection_of_one(self, items):
        found = db.get_items_without_hashes(resolve_scope([items[3]]))
        assert [i.id for i in found] == [items[3]]


class TestDateQueryScope:
    def test_the_library_scope_returns_everything(self, items):
        assert len(db.get_items_without_date()) == 5

    def test_a_selection_returns_only_those_items(self, items):
        found = db.get_items_without_date(resolve_scope(items[:3]))
        assert sorted(i.id for i in found) == sorted(items[:3])


class TestLocationQueryScope:
    def test_the_library_scope_returns_everything(self, items):
        assert len(db.get_items_without_location()) == 5

    def test_a_selection_returns_only_those_items(self, items):
        found = db.get_items_without_location(resolve_scope(items[1:3]))
        assert sorted(i.id for i in found) == sorted(items[1:3])


class TestAllItemsScope:
    def test_the_library_scope_returns_everything(self, items):
        assert len(db.get_all_items()) == 5

    def test_a_selection_returns_only_those_items(self, items):
        found = db.get_all_items(resolve_scope(items[:2]))
        assert sorted(i.id for i in found) == sorted(items[:2])


class TestLargeSelections:
    """A selection larger than SQLite's 32766-variable statement cap must
    still work: this is why the ids go in a temp table rather than an IN
    clause. The cap is per prepared statement, so splitting into OR'd IN
    clauses would not get under it."""

    def test_a_selection_of_forty_thousand_ids(self, items):
        huge = list(range(10_000, 50_000)) + items[:1]
        found = db.get_items_without_hashes(resolve_scope(huge))
        assert [i.id for i in found] == items[:1]


class TestScopeIsolation:
    """The temp table is reused across queries on a pooled connection."""

    def test_a_second_query_is_not_affected_by_the_first(self, items):
        db.get_items_without_hashes(resolve_scope(items[:1]))
        found = db.get_items_without_hashes(resolve_scope(items[2:4]))
        assert sorted(i.id for i in found) == sorted(items[2:4])

    def test_a_library_query_after_a_selection_still_sees_everything(self, items):
        db.get_items_without_hashes(resolve_scope(items[:1]))
        assert len(db.get_items_without_hashes()) == 5
