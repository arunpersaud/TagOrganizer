"""Tests for filtering by an explicit set of item ids.

The id filter has to survive a selection larger than SQLite's bound-variable
limit, which is why the ids are chunked rather than passed as one IN clause.
"""

from sqlmodel import Session

from tagorganizer import db
from tagorganizer.models import Item
from tagorganizer.widgets.tag_bar import Filters


class TestChunkIds:
    def test_empty_yields_one_empty_chunk(self):
        """A selection of nothing must still build a clause that matches nothing."""
        assert db.chunk_ids([]) == [[]]

    def test_short_list_is_one_chunk(self):
        assert db.chunk_ids([1, 2, 3]) == [[1, 2, 3]]

    def test_exactly_one_chunk(self):
        ids = list(range(30_000))
        assert db.chunk_ids(ids, size=30_000) == [ids]

    def test_splits_beyond_the_chunk_size(self):
        ids = list(range(70_000))
        chunks = db.chunk_ids(ids, size=30_000)
        assert [len(c) for c in chunks] == [30_000, 30_000, 10_000]
        assert [i for c in chunks for i in c] == ids

    def test_no_chunk_exceeds_sqlite_variable_limit(self):
        """32766 is the measured ceiling; a chunk above it would raise."""
        chunks = db.chunk_ids(list(range(100_000)))
        assert all(len(c) <= 32_766 for c in chunks)


class TestGetItemsByIds:
    def test_returns_the_named_items(self, temp_db):
        with Session(temp_db) as session:
            for i in range(5):
                session.add(Item(uri=f"/p/{i}.jpg"))
            session.commit()
            ids = [i.id for i in session.exec(db.select(Item)).all()]

        found = db.get_items_by_ids(ids[1:3])
        assert {i.uri for i in found} == {"/p/1.jpg", "/p/2.jpg"}

    def test_empty_returns_nothing(self, temp_db):
        assert db.get_items_by_ids([]) == []


class TestItemIdFilter:
    def test_restricts_to_the_given_ids(self, temp_db):
        with Session(temp_db) as session:
            for i in range(5):
                session.add(Item(uri=f"/p/{i}.jpg"))
            session.commit()
            ids = [i.id for i in session.exec(db.select(Item)).all()]

        filters = Filters(item_ids=ids[:2])
        assert db.get_number_of_items(filters) == 2
        assert {i.uri for i in db.get_images(0, filters)} == {"/p/0.jpg", "/p/1.jpg"}

    def test_empty_id_list_matches_nothing(self, temp_db):
        """[] means 'an empty selection', which is not the same as None."""
        with Session(temp_db) as session:
            session.add(Item(uri="/p/0.jpg"))
            session.commit()

        assert db.get_number_of_items(Filters(item_ids=[])) == 0

    def test_none_means_no_id_filter(self, temp_db):
        with Session(temp_db) as session:
            session.add(Item(uri="/p/0.jpg"))
            session.commit()

        assert db.get_number_of_items(Filters(item_ids=None)) == 1

    def test_survives_more_ids_than_sqlite_allows(self, temp_db):
        """Without chunking this raises OperationalError: too many SQL variables."""
        with Session(temp_db) as session:
            session.add(Item(uri="/p/real.jpg"))
            session.commit()
            real_id = session.exec(db.select(Item)).first().id

        # One real id buried in far more ids than SQLite can bind at once.
        padded = [*range(real_id + 1, real_id + 70_000), real_id]
        assert db.get_number_of_items(Filters(item_ids=padded)) == 1
