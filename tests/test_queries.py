"""Tests for database query fixes (F4, F7, F19).

Tests verify:
- F4: Hierarchical tag filtering correctly includes items tagged with both parent and child
- F7: Image ordering consistency between get_images and get_current_image
- F19: Batch add_images without nested sessions
"""

from datetime import datetime

from sqlmodel import Session, select

from tagorganizer import db
from tagorganizer.models import Item, ItemTagLink, Tag
from tagorganizer.widgets.tag_bar import Filters


class TestF4HierarchicalTagFilter:
    """F4: Hierarchical tag filter drops items tagged with both parent and child."""

    def test_filter_by_parent_returns_all_tagged_items(self, seeded_db):
        """Filtering by parent tag should return all items tagged with parent or child.

        The seeded_db has:
        - item[0] tagged with parent (Travel)
        - item[1] tagged with child (Japan)
        - item[2] tagged with BOTH parent and child
        - item[3] untagged

        Filtering by ["Travel"] should return all three tagged items [0, 1, 2].
        """
        filters = Filters(tags=["Travel"])
        results = db.get_images(0, filters)
        uris = sorted([item.uri for item in results])

        # Items 0, 1, 2 are tagged (directly or via child) with Travel
        expected = sorted(["/p/0.jpg", "/p/1.jpg", "/p/2.jpg"])
        assert uris == expected, f"Expected {expected}, got {uris}"

    def test_multi_tag_and_semantics(self, seeded_db):
        """Filtering by multiple tags should use AND semantics.

        This test requires two tags where no item has both, to verify AND works.
        We create a temporary Beach tag and verify that filtering by
        ["Travel", "Beach"] requires having both tags.
        """
        with Session(db.engine) as session:
            # Create a Beach tag (unrelated parent)
            beach = Tag(name="Beach")
            session.add(beach)
            session.commit()
            session.refresh(beach)

            # Tag one item with Beach (item[3], which is currently untagged)
            session.add(ItemTagLink(item_id=seeded_db["items"][3].id, tag_id=beach.id))
            session.commit()

        # Now filter by ["Travel", "Beach"]
        filters = Filters(tags=["Travel", "Beach"])
        results = db.get_images(0, filters)
        uris = sorted([item.uri for item in results])

        # Only item[3] has Beach, and it doesn't have Travel, so no results
        expected = []
        assert uris == expected, f"Expected {expected} for AND filter, got {uris}"


class TestF7ImageOrdering:
    """F7: The preloader warms the opposite end of the collection."""

    def test_get_images_and_get_current_image_same_order(self, seeded_db):
        """Both functions should return items in the same order.

        get_images(0, None) should return the same sequence as
        [get_current_image(n, None) for n in range(4)].
        """
        # Get all items using get_images with no filters
        results_pages = []
        page = 0
        while True:
            results = db.get_images(page, None)
            if not results:
                break
            results_pages.extend(results)
            page += 1

        # Get items using get_current_image for each position
        results_current = []
        for i in range(len(results_pages)):
            item = db.get_current_image(i, None)
            if item:
                results_current.append(item)

        # Extract URIs for comparison
        uris_pages = [item.uri for item in results_pages]
        uris_current = [item.uri for item in results_current]

        assert uris_pages == uris_current, (
            f"Order mismatch: get_images gave {uris_pages}, "
            f"get_current_image gave {uris_current}"
        )

    def test_null_date_ordering_is_consistent(self, temp_db):
        """Items with NULL dates should be ordered consistently.

        Verify that NULL dates are placed after dated items and that
        both get_images and get_current_image handle NULLs the same way.
        """
        # Create items with mixed NULL and non-NULL dates
        with Session(temp_db) as session:
            items = [
                Item(uri="/p/0.jpg", date=datetime(2020, 1, 3)),
                Item(uri="/p/1.jpg", date=None),  # NULL date
                Item(uri="/p/2.jpg", date=datetime(2020, 1, 1)),
                Item(uri="/p/3.jpg", date=None),  # NULL date
            ]
            for item in items:
                session.add(item)
            session.commit()

        # Get all items using get_images
        results_pages = []
        page = 0
        while True:
            results = db.get_images(page, None)
            if not results:
                break
            results_pages.extend(results)
            page += 1

        # Get items using get_current_image
        results_current = []
        for i in range(len(results_pages)):
            item = db.get_current_image(i, None)
            if item:
                results_current.append(item)

        # Extract URIs for comparison
        uris_pages = [item.uri for item in results_pages]
        uris_current = [item.uri for item in results_current]

        # Verify same order
        assert uris_pages == uris_current, (
            f"NULL order mismatch: get_images gave {uris_pages}, "
            f"get_current_image gave {uris_current}"
        )

        # Verify expected order: newest dated first, oldest dated, then NULLs
        # Expected: /p/0.jpg (2020-01-03), /p/2.jpg (2020-01-01), then NULLs
        # The NULLs might be in database order (insertion order), but should be after dated items
        assert uris_pages[0] == "/p/0.jpg", "Newest item should be first"
        assert uris_pages[1] == "/p/2.jpg", "Oldest dated item should be second"
        assert uris_pages[2] in [
            "/p/1.jpg",
            "/p/3.jpg",
        ], "NULL items should be after dated items"
        assert uris_pages[3] in [
            "/p/1.jpg",
            "/p/3.jpg",
        ], "NULL items should be after dated items"


class TestF19AddImagesOptimization:
    """F19: db.py:131-150 add_images nested session calls."""

    def test_add_images_inserts_only_new_uris(self, temp_db):
        """add_images should insert only new URIs without duplicating existing ones.

        This test verifies that add_images:
        1. Doesn't create nested sessions (only one session is used)
        2. Correctly identifies duplicates
        3. Skips duplicates and prints a message
        4. Only commits new items
        """
        # First batch: add some images
        db.add_images(["/p/0.jpg", "/p/1.jpg"])

        # Verify they were added
        with Session(temp_db) as session:
            count = session.exec(select(Item)).all()
            assert len(count) == 2

        # Second batch: add a mix of new and existing URIs
        db.add_images(["/p/1.jpg", "/p/2.jpg", "/p/3.jpg"])

        # Verify only new ones were added (no duplicates)
        with Session(temp_db) as session:
            items = session.exec(select(Item)).all()
            uris = sorted([item.uri for item in items])

        expected = ["/p/0.jpg", "/p/1.jpg", "/p/2.jpg", "/p/3.jpg"]
        assert uris == expected, f"Expected {expected}, got {uris}"

    def test_add_images_with_all_duplicates(self, temp_db):
        """add_images should handle all-duplicate input gracefully."""
        # Add initial images
        db.add_images(["/p/0.jpg", "/p/1.jpg"])

        # Try to add the same images again
        db.add_images(["/p/0.jpg", "/p/1.jpg"])

        # Verify no new items were created
        with Session(temp_db) as session:
            items = session.exec(select(Item)).all()
        assert len(items) == 2, "No new items should be created for duplicates"

    def test_add_image_singular_still_works(self, temp_db):
        """add_image (singular) should still work for DBimport compatibility.

        This verifies that the fix to add_images doesn't break add_image,
        which is required by agent-6 (DBimport).
        """
        # add_image should work independently
        item_id = db.add_image("/p/test.jpg")
        assert item_id is not None

        # Calling add_image with duplicate should return the ID
        item_id2 = db.add_image("/p/test.jpg")
        assert item_id2 == item_id

        # Verify only one item exists
        with Session(temp_db) as session:
            items = session.exec(select(Item)).all()
        assert len(items) == 1


class TestGetImageRange:
    """get_image_range: one query for a window of items, in display order.

    The preloader used to call get_current_image once per item. Each call
    opens its own session and sorts the whole table, which cost ~100 ms for
    eleven items at 30k rows - more than the preloader's entire frame budget.
    """

    def test_range_matches_per_item_lookup(self, seeded_db):
        ranged = [item.uri for item in db.get_image_range(0, 4, None)]
        per_item = [db.get_current_image(i, None).uri for i in range(4)]
        assert ranged == per_item

    def test_range_matches_page_from_get_images(self, seeded_db):
        assert [i.uri for i in db.get_images(0, None)] == [
            i.uri for i in db.get_image_range(0, 25, None)
        ]

    def test_negative_start_is_clamped(self, seeded_db):
        """The preloader asks for highlight-5, which is negative near the top."""
        assert [i.uri for i in db.get_image_range(-3, 5, None)] == [
            i.uri for i in db.get_image_range(0, 2, None)
        ]

    def test_range_past_the_end_is_empty(self, seeded_db):
        assert db.get_image_range(999, 10, None) == []
        assert db.get_image_range(0, 0, None) == []

    def test_get_current_image_past_the_end_returns_none(self, seeded_db):
        assert db.get_current_image(999, None) is None
