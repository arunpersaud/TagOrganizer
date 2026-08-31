"""Tests for cross-profile database moves, with and without failures.

This module tests the atomic movement of items (photos) from one profile's
database to another. The critical test is forced mid-transaction failure:
inject a failure after the insert and before the commit, then assert both
databases hold exactly the rows they started with. That test is what makes
the word "atomic" true rather than aspirational.

The duplicate test must assert that the total number of item rows across
BOTH databases is unchanged by a skip. That is the assertion that catches
the data-loss bug (delete by uri instead of by id).
"""

import pytest
from datetime import datetime
from sqlalchemy import create_engine as sa_create_engine
from sqlmodel import Session, SQLModel, select

from tagorganizer import db
from tagorganizer.models import Item, ItemTagLink, Tag
from tagorganizer.dbmove import move_items, prepare_target


@pytest.fixture
def source_and_target(tmp_path):
    """Create two separate databases: source and target.

    Source has items and tags already; target is empty and ready to receive.
    Both are real SQLite databases with proper schema, not mocks.
    """
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"

    # Create source database
    source_engine = sa_create_engine(f"sqlite:///{source_path}")
    SQLModel.metadata.create_all(source_engine)

    # prepare_target will create the target database with full schema
    prepare_target(target_path)

    # Seed source database with items and tags
    with Session(source_engine) as session:
        items = [
            Item(
                uri="/p/a.jpg",
                camera="Canon",
                date=datetime(2020, 1, 1),
                latitude=10.0,
                longitude=20.0,
            ),
            Item(
                uri="/p/b.jpg",
                camera="Nikon",
                date=datetime(2020, 1, 2),
                latitude=11.0,
                longitude=21.0,
            ),
            Item(
                uri="/p/c.jpg",
                camera="Sony",
                date=datetime(2020, 1, 3),
                latitude=12.0,
                longitude=22.0,
            ),
        ]
        for item in items:
            session.add(item)

        parent_tag = Tag(name="Travel")
        session.add(parent_tag)
        session.commit()
        session.refresh(parent_tag)

        child_tag = Tag(name="Japan", parent_id=parent_tag.id)
        session.add(child_tag)
        session.commit()
        session.refresh(child_tag)

        # Refresh items to get their ids
        for item in items:
            session.refresh(item)

        # Tag items[0] and items[1]
        session.add(ItemTagLink(item_id=items[0].id, tag_id=child_tag.id))
        session.add(ItemTagLink(item_id=items[1].id, tag_id=parent_tag.id))
        session.commit()

    source_engine.dispose()

    # Point db.engine at source for the test
    previous = db.engine
    db.set_engine(str(source_path))

    try:
        yield {
            "source_path": source_path,
            "target_path": target_path,
            "source_engine": sa_create_engine(f"sqlite:///{source_path}"),
            "target_engine": sa_create_engine(f"sqlite:///{target_path}"),
        }
    finally:
        db.engine = previous


class TestMoveItemsSuccessful:
    """Successful moves with various item configurations."""

    def test_move_three_items_none_in_target(self, source_and_target):
        """Move three items from source to target when target is empty.

        Assert both appear in the target with all fields preserved,
        are gone from source, and the untouched third remains in source.
        """
        source_path = source_and_target["source_path"]
        target_path = source_and_target["target_path"]

        # Get source item ids
        with Session(source_and_target["source_engine"]) as session:
            items = session.exec(select(Item)).all()
            item_ids = [item.id for item in items]

        # Move the first two
        result = move_items(
            Session(sa_create_engine(f"sqlite:///{source_path}")),
            target_path,
            item_ids[:2],
        )

        assert len(result.moved_ids) == 2
        assert set(result.moved_ids) == set(item_ids[:2])
        assert len(result.skipped_ids) == 0

        # Verify moved items in target
        with Session(source_and_target["target_engine"]) as session:
            target_items = session.exec(select(Item)).all()
            assert len(target_items) == 2

            # Check that fields are preserved (uri and metadata)
            target_uris = {item.uri for item in target_items}
            assert "/p/a.jpg" in target_uris
            assert "/p/b.jpg" in target_uris

            # Check metadata
            for item in target_items:
                if item.uri == "/p/a.jpg":
                    assert item.camera == "Canon"
                    assert item.date == datetime(2020, 1, 1)
                    assert item.latitude == 10.0
                    assert item.longitude == 20.0
                elif item.uri == "/p/b.jpg":
                    assert item.camera == "Nikon"
                    assert item.date == datetime(2020, 1, 2)
                    assert item.latitude == 11.0
                    assert item.longitude == 21.0

        # Verify moved items gone from source
        with Session(source_and_target["source_engine"]) as session:
            source_items = session.exec(select(Item)).all()
            assert len(source_items) == 1
            assert source_items[0].uri == "/p/c.jpg"

    def test_ids_are_reassigned_in_target(self, source_and_target):
        """Ids are not preserved; target assigns new ids to moved items.

        Seed target with rows so its next id overlaps the source's id space,
        then move and assert items exist under whatever ids the target gave.
        """
        source_path = source_and_target["source_path"]
        target_path = source_and_target["target_path"]

        # Seed target with items to advance its id counter
        with Session(source_and_target["target_engine"]) as session:
            for i in range(5):
                session.add(Item(uri=f"/existing/{i}.jpg"))
            session.commit()

        # Get source item ids
        with Session(source_and_target["source_engine"]) as session:
            source_items = session.exec(select(Item)).all()
            source_ids = [item.id for item in source_items]
            source_uris = {item.uri for item in source_items}

        # Move all items
        result = move_items(
            Session(sa_create_engine(f"sqlite:///{source_path}")),
            target_path,
            source_ids,
        )

        # Verify the move succeeded
        assert len(result.moved_ids) == len(source_ids)
        assert len(result.skipped_ids) == 0

        # Verify items exist in target with correct uris but different ids
        with Session(source_and_target["target_engine"]) as session:
            target_items = session.exec(select(Item)).all()
            target_uris = {item.uri for item in target_items}

            # The moved items should be there by uri
            for uri in source_uris:
                assert uri in target_uris

            # But their ids should be different (target started with higher ids)
            moved_target_ids = [
                item.id for item in target_items if item.uri in source_uris
            ]
            # None of the moved ids should match the source ids
            for moved_id in moved_target_ids:
                assert moved_id not in source_ids

    def test_duplicate_uri_is_skipped(self, source_and_target):
        """Duplicate uris are skipped; request all, get two moved, one skipped.

        Target already holds /p/c.jpg; request all three items. Assert
        /p/c.jpg is still in the source (not moved), skipped_ids names it,
        and the total row count across both databases is unchanged by the skip
        (the critical assertion that catches the data-loss bug).
        """
        source_path = source_and_target["source_path"]
        target_path = source_and_target["target_path"]

        # Add c.jpg to target so it's a duplicate
        with Session(source_and_target["target_engine"]) as session:
            session.add(Item(uri="/p/c.jpg", camera="iPhone"))
            session.commit()

        # Get all source item ids
        with Session(source_and_target["source_engine"]) as session:
            source_items = session.exec(select(Item)).all()
            all_ids = [item.id for item in source_items]
            c_item_id = next(item.id for item in source_items if item.uri == "/p/c.jpg")

        # Count rows before move
        with Session(source_and_target["source_engine"]) as session:
            source_count_before = session.exec(select(Item)).all().__len__()
        with Session(source_and_target["target_engine"]) as session:
            target_count_before = session.exec(select(Item)).all().__len__()
        total_before = source_count_before + target_count_before

        # Request all three items to move
        result = move_items(
            Session(sa_create_engine(f"sqlite:///{source_path}")), target_path, all_ids
        )

        # Verify skipped
        assert len(result.moved_ids) == 2
        assert len(result.skipped_ids) == 1
        assert c_item_id in result.skipped_ids

        # Verify /p/c.jpg still in source
        with Session(source_and_target["source_engine"]) as session:
            c_item = session.exec(select(Item).where(Item.uri == "/p/c.jpg")).first()
            assert c_item is not None

        # CRITICAL: total row count across both databases unchanged
        with Session(source_and_target["source_engine"]) as session:
            source_count_after = session.exec(select(Item)).all().__len__()
        with Session(source_and_target["target_engine"]) as session:
            target_count_after = session.exec(select(Item)).all().__len__()
        total_after = source_count_after + target_count_after

        assert total_after == total_before, (
            f"Data loss detected! Total rows before: {total_before}, "
            f"after: {total_after}. This is the bug the plan exists to prevent."
        )

    def test_tag_links_removed_and_reported(self, source_and_target):
        """Moving an item removes its tag links from source and reports tag names.

        Tag a moved item, assert no itemtaglink row referencing it survives
        in the source, that the Tag row itself remains in the source, and
        that its name appears in dropped_tags.
        """
        source_path = source_and_target["source_path"]
        target_path = source_and_target["target_path"]

        # Get the tagged item (items[0] is tagged with "Japan")
        with Session(source_and_target["source_engine"]) as session:
            tagged_item = session.exec(
                select(Item).where(Item.uri == "/p/a.jpg")
            ).first()
            tagged_item_id = tagged_item.id

        # Move that item
        result = move_items(
            Session(sa_create_engine(f"sqlite:///{source_path}")),
            target_path,
            [tagged_item_id],
        )

        assert tagged_item_id in result.moved_ids

        # Verify the tag link is gone from source
        with Session(source_and_target["source_engine"]) as session:
            links = session.exec(
                select(ItemTagLink).where(ItemTagLink.item_id == tagged_item_id)
            ).all()
            assert len(links) == 0

        # Verify the Tag row still exists
        with Session(source_and_target["source_engine"]) as session:
            tags = session.exec(select(Tag)).all()
            assert len(tags) == 2  # Both Travel and Japan still exist

        # Verify tag names are in dropped_tags
        assert "Japan" in result.dropped_tags

    def test_empty_id_list_is_noop(self, source_and_target):
        """Empty id list is a no-op returning empty result."""
        source_path = source_and_target["source_path"]
        target_path = source_and_target["target_path"]

        result = move_items(
            Session(sa_create_engine(f"sqlite:///{source_path}")), target_path, []
        )

        assert len(result.moved_ids) == 0
        assert len(result.skipped_ids) == 0
        assert len(result.dropped_tags) == 0

    def test_chunking_with_large_id_list(self, source_and_target):
        """Pass more than 32766 ids (mostly non-existent) and assert no error.

        This tests that chunking is working correctly to respect SQLite's
        per-statement bound variable limit.
        """
        source_path = source_and_target["source_path"]
        target_path = source_and_target["target_path"]

        # Get real item ids
        with Session(source_and_target["source_engine"]) as session:
            real_items = session.exec(select(Item)).all()
            real_ids = [item.id for item in real_items]

        # Create a massive list with mostly non-existent ids
        large_id_list = list(range(1, 40000)) + real_ids

        # This should not raise OperationalError: too many SQL variables
        result = move_items(
            Session(sa_create_engine(f"sqlite:///{source_path}")),
            target_path,
            large_id_list,
        )

        # Should have moved the real ones
        assert len(result.moved_ids) == len(real_ids)
        assert set(result.moved_ids) == set(real_ids)


class TestMoveItemsAtomicity:
    """Test atomic transaction behavior."""

    def test_forced_mid_transaction_failure_changes_nothing(
        self, source_and_target, monkeypatch
    ):
        """Inject failure after insert, before commit: both databases unchanged.

        This test exercises the REAL move_items function by monkeypatching
        chunk_ids to fail on the 4th call (in DELETE FROM itemtaglink, after
        INSERT). It verifies the exception propagates and both databases are
        rolled back unchanged.

        The test MUST FAIL if session.rollback() is removed from move_items.
        """
        source_path = source_and_target["source_path"]
        target_path = source_and_target["target_path"]

        # Capture state before move
        with Session(source_and_target["source_engine"]) as session:
            source_items_before = session.exec(select(Item)).all()
            source_ids_before = {(item.id, item.uri) for item in source_items_before}
            source_count_before = len(source_items_before)

        with Session(source_and_target["target_engine"]) as session:
            target_items_before = session.exec(select(Item)).all()
            target_ids_before = {(item.id, item.uri) for item in target_items_before}
            target_count_before = len(target_items_before)

        # Get the ids to move
        with Session(source_and_target["source_engine"]) as session:
            items_to_move = session.exec(
                select(Item).where(Item.uri.in_(["/p/a.jpg", "/p/b.jpg"]))
            ).all()
            move_ids = [item.id for item in items_to_move]

        # Patch chunk_ids to fail on the 4th call. chunk_ids is called in this
        # order inside move_items:
        # 1. SELECT movable ids
        # 2. SELECT tag names for dropped_tags
        # 3. INSERT into tgt.item
        # 4. DELETE FROM main.itemtaglink <- FAIL HERE
        # 5. DELETE FROM main.item
        # Failing on call 4 means the INSERT has executed but no DELETEs yet.
        from tagorganizer.db import chunk_ids as real_chunk_ids

        call_count = [0]

        def chunk_ids_with_failure(item_ids, size=30000):
            call_count[0] += 1
            if call_count[0] == 4:
                raise RuntimeError("Injected mid-transaction failure after INSERT")
            return real_chunk_ids(item_ids, size)

        monkeypatch.setattr("tagorganizer.dbmove.chunk_ids", chunk_ids_with_failure)

        # Execute the REAL move_items function with failure injection
        with pytest.raises(RuntimeError, match="Injected mid-transaction failure"):
            move_items(
                Session(sa_create_engine(f"sqlite:///{source_path}")),
                target_path,
                move_ids,
            )

        # Verify both databases are exactly as they were
        with Session(source_and_target["source_engine"]) as session:
            source_items_after = session.exec(select(Item)).all()
            source_ids_after = {(item.id, item.uri) for item in source_items_after}
            source_count_after = len(source_items_after)

        with Session(source_and_target["target_engine"]) as session:
            target_items_after = session.exec(select(Item)).all()
            target_ids_after = {(item.id, item.uri) for item in target_items_after}
            target_count_after = len(target_items_after)

        assert (
            source_ids_before == source_ids_after
        ), "Source database was modified despite transaction failure"
        assert source_count_before == source_count_after

        assert (
            target_ids_before == target_ids_after
        ), "Target database was modified despite transaction failure"
        assert target_count_before == target_count_after
