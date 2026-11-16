"""Tests for filtering by an explicit set of item ids.

The id filter uses a temp table to materialise ids out of the statement,
because SQLite's 32766-variable cap is per prepared statement. This approach
keeps ORDER BY and LIMIT in SQL rather than redoing them in Python.
"""

from datetime import datetime

import pytest
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


class TestOrderingAgreement:
    def test_get_images_and_get_image_range_agree_on_order_without_filter(
        self, temp_db
    ):
        """get_images and get_image_range must return items in the same order.

        This is critical for grid indexing: an index must mean the same item
        everywhere. The two orderings disagree if one sorts in Python.
        """
        with Session(temp_db) as session:
            # Create items sharing one date (to test tiebreaker ordering)
            shared_date = datetime(2020, 1, 1)
            for i in range(5):
                session.add(Item(uri=f"/p/{i}.jpg", date=shared_date))
            session.commit()

        # get_images page 0 should return first 25 items in standard order
        items_from_get_images = db.get_images(0, None)

        # get_image_range for the same items should match exactly
        items_from_range = db.get_image_range(0, 25, None)

        assert len(items_from_get_images) == len(items_from_range)
        for i, (img, rng) in enumerate(
            zip(items_from_get_images, items_from_range, strict=False)
        ):
            assert img.id == rng.id, (
                f"Mismatch at index {i}: get_images has {img.id}, get_image_range has {rng.id}"
            )

    def test_get_images_and_get_image_range_agree_on_order_with_id_filter(
        self, temp_db
    ):
        """Ordering agreement must also hold with an id filter applied."""
        with Session(temp_db) as session:
            shared_date = datetime(2020, 1, 1)
            for i in range(10):
                session.add(Item(uri=f"/p/{i}.jpg", date=shared_date))
            session.commit()
            all_ids = [i.id for i in session.exec(db.select(Item)).all()]

        # Filter to first 5 ids
        filters = Filters(item_ids=all_ids[:5])
        items_from_get_images = db.get_images(0, filters)
        items_from_range = db.get_image_range(0, 25, filters)

        assert len(items_from_get_images) == len(items_from_range)
        for i, (img, rng) in enumerate(
            zip(items_from_get_images, items_from_range, strict=False)
        ):
            assert img.id == rng.id, (
                f"Mismatch at index {i}: get_images has {img.id}, get_image_range has {rng.id}"
            )


class TestFilterQueryContractEnforcement:
    def test_filter_query_requires_session_for_id_filter(self, temp_db):
        """filter_query must have a session to materialise id filters.

        Calling without session but with item_ids set should raise TypeError,
        not silently return all rows. This guards against the silent failure
        mode where a user filtering to 3 items would see their entire library.
        """
        with Session(temp_db) as session:
            for i in range(5):
                session.add(Item(uri=f"/p/{i}.jpg"))
            session.commit()
            ids = [i.id for i in session.exec(db.select(Item)).all()]

        filters = Filters(item_ids=ids[:2])
        query = db.select(db.func.count(Item.id))

        # Should raise TypeError when session is not provided
        with pytest.raises(TypeError):
            db.filter_query(query, filters)  # Missing required session parameter


class TestLargeSelections:
    def test_get_image_range_survives_70000_ids(self, temp_db):
        """get_image_range must handle selections larger than SQLite's limit."""
        with Session(temp_db) as session:
            session.add(Item(uri="/p/real.jpg"))
            session.commit()
            real_id = session.exec(db.select(Item)).first().id

        padded = [*range(real_id + 1, real_id + 70_000), real_id]
        filters = Filters(item_ids=padded)

        # Should return 1 item (the real one), not raise OperationalError
        result = db.get_image_range(0, 25, filters)
        assert len(result) == 1
        assert result[0].id == real_id

    def test_get_times_and_location_from_images_survives_70000_ids(self, temp_db):
        """get_times_and_location must handle selections larger than SQLite's limit."""
        with Session(temp_db) as session:
            test_date = datetime(2020, 6, 15, 12, 0, 0)
            session.add(
                Item(
                    uri="/p/real.jpg",
                    date=test_date,
                    latitude=40.7128,
                    longitude=-74.0060,
                )
            )
            session.commit()
            real_id = session.exec(db.select(Item)).first().id

        padded = [*range(real_id + 1, real_id + 70_000), real_id]
        filters = Filters(item_ids=padded)

        # Should return 1 date and 1 coordinate, not raise OperationalError
        dates, coords = db.get_times_and_location_from_images(filters)
        assert len(dates) == 1
        assert dates[0] == test_date
        assert len(coords) == 1
        assert coords[0] == (40.7128, -74.0060)
