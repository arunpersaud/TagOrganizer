"""Renaming, merging and removing tags.

Merge is destructive and has no undo, so these assert on the resulting rows
rather than on return values alone.
"""

import pytest
from sqlmodel import Session, select

from tagorganizer import db
from tagorganizer.models import Item, ItemTagLink, Tag


@pytest.fixture
def vocabulary(temp_db):
    """Three photos and a small hierarchy.

    Beach > Sand, Surf
    Coast

    photo0: Beach
    photo1: Beach and Coast   <- the duplicate-link case
    photo2: Coast
    """
    with Session(temp_db) as session:
        items = [Item(uri=f"/p/{i}.jpg") for i in range(3)]
        for item in items:
            session.add(item)

        tags = {name: Tag(name=name) for name in ("Beach", "Coast", "Sand", "Surf")}
        for tag in tags.values():
            session.add(tag)
        session.commit()
        for obj in (*items, *tags.values()):
            session.refresh(obj)

        for child in ("Sand", "Surf"):
            tags[child].parent_id = tags["Beach"].id
            session.add(tags[child])

        session.add(ItemTagLink(item_id=items[0].id, tag_id=tags["Beach"].id))
        session.add(ItemTagLink(item_id=items[1].id, tag_id=tags["Beach"].id))
        session.add(ItemTagLink(item_id=items[1].id, tag_id=tags["Coast"].id))
        session.add(ItemTagLink(item_id=items[2].id, tag_id=tags["Coast"].id))
        session.commit()

        return {
            "items": [item.id for item in items],
            "tags": {name: tag.id for name, tag in tags.items()},
        }


def items_on(tag_id):
    with db.new_session() as session:
        return sorted(
            session.exec(
                select(ItemTagLink.item_id).where(ItemTagLink.tag_id == tag_id)
            ).all()
        )


class TestRenameTag:
    def test_renames(self, vocabulary):
        db.rename_tag(vocabulary["tags"]["Beach"], "Seaside")
        assert db.get_tag("Seaside") is not None
        assert db.get_tag("Beach") is None

    def test_keeps_the_links(self, vocabulary):
        before = items_on(vocabulary["tags"]["Beach"])
        db.rename_tag(vocabulary["tags"]["Beach"], "Seaside")
        assert items_on(vocabulary["tags"]["Beach"]) == before

    def test_refuses_a_case_insensitive_collision(self, vocabulary):
        """Tag lookup folds case, so 'coast' and 'Coast' would be one tag.

        Allowing the rename would leave two rows get_tag cannot tell apart.
        """
        with pytest.raises(ValueError, match="already"):
            db.rename_tag(vocabulary["tags"]["Beach"], "coast")

    def test_renaming_to_its_own_name_in_a_different_case_is_allowed(self, vocabulary):
        db.rename_tag(vocabulary["tags"]["Beach"], "BEACH")
        assert db.get_tag_by_id(vocabulary["tags"]["Beach"]).name == "BEACH"


class TestMergeTags:
    def test_moves_links_to_the_survivor(self, vocabulary):
        tags = vocabulary["tags"]
        db.merge_tags(tags["Beach"], tags["Coast"])
        assert items_on(tags["Coast"]) == sorted(vocabulary["items"])

    def test_a_photo_carrying_both_tags_ends_with_one_link(self, vocabulary):
        """ItemTagLink has a composite primary key.

        Repointing every link would violate it for a photo that already carries
        the target tag, so the redundant link must be dropped instead.
        """
        tags = vocabulary["tags"]
        db.merge_tags(tags["Beach"], tags["Coast"])
        links = items_on(tags["Coast"])
        assert len(links) == len(set(links))

    def test_reports_what_it_moved_and_dropped(self, vocabulary):
        tags = vocabulary["tags"]
        moved, dropped = db.merge_tags(tags["Beach"], tags["Coast"])
        assert (moved, dropped) == (1, 1)

    def test_children_move_to_the_survivor(self, vocabulary):
        tags = vocabulary["tags"]
        db.merge_tags(tags["Beach"], tags["Coast"])
        with db.new_session() as session:
            children = sorted(
                tag.name
                for tag in session.exec(
                    select(Tag).where(Tag.parent_id == tags["Coast"])
                ).all()
            )
        assert children == ["Sand", "Surf"]

    def test_the_source_tag_is_gone(self, vocabulary):
        tags = vocabulary["tags"]
        db.merge_tags(tags["Beach"], tags["Coast"])
        assert db.get_tag_by_id(tags["Beach"]) is None

    def test_refuses_merging_a_tag_into_itself(self, vocabulary):
        tags = vocabulary["tags"]
        with pytest.raises(ValueError, match="itself"):
            db.merge_tags(tags["Beach"], tags["Beach"])

    def test_refuses_merging_into_a_descendant(self, vocabulary):
        """Reparenting the children afterwards would make a tag its own ancestor."""
        tags = vocabulary["tags"]
        with pytest.raises(ValueError, match="descendant"):
            db.merge_tags(tags["Beach"], tags["Sand"])

    def test_a_refused_merge_changes_nothing(self, vocabulary):
        tags = vocabulary["tags"]
        before = items_on(tags["Beach"])
        with pytest.raises(ValueError):
            db.merge_tags(tags["Beach"], tags["Sand"])
        assert items_on(tags["Beach"]) == before
        assert db.get_tag_by_id(tags["Beach"]) is not None


class TestRemoveTags:
    def test_removes_the_link(self, vocabulary):
        tags, items = vocabulary["tags"], vocabulary["items"]
        removed = db.remove_tags(
            [Item(id=items[0])], [Tag(id=tags["Beach"], name="Beach")]
        )
        assert removed == 1
        assert items[0] not in items_on(tags["Beach"])

    def test_leaves_the_same_tag_on_other_photos(self, vocabulary):
        tags, items = vocabulary["tags"], vocabulary["items"]
        db.remove_tags([Item(id=items[0])], [Tag(id=tags["Beach"], name="Beach")])
        assert items[1] in items_on(tags["Beach"])

    def test_leaves_other_tags_on_the_same_photo(self, vocabulary):
        tags, items = vocabulary["tags"], vocabulary["items"]
        db.remove_tags([Item(id=items[1])], [Tag(id=tags["Beach"], name="Beach")])
        assert items[1] in items_on(tags["Coast"])

    def test_the_tag_itself_survives(self, vocabulary):
        """Untagging one photo must not delete the tag from the library."""
        tags, items = vocabulary["tags"], vocabulary["items"]
        db.remove_tags([Item(id=items[0])], [Tag(id=tags["Beach"], name="Beach")])
        assert db.get_tag_by_id(tags["Beach"]) is not None

    def test_removing_a_tag_a_photo_never_had_is_quiet(self, vocabulary):
        tags, items = vocabulary["tags"], vocabulary["items"]
        assert (
            db.remove_tags([Item(id=items[2])], [Tag(id=tags["Beach"], name="Beach")])
            == 0
        )


class TestAddTagRace:
    """add_tag looks the name up, then inserts.

    Harmless when everything ran on the GUI thread; a real interleaving now
    that plugins run on a worker while the user types in the tag bar. The
    unique constraint turns the lost race into an IntegrityError, which
    add_tag has to absorb rather than propagate.
    """

    @pytest.fixture
    def lost_race(self, temp_db, monkeypatch):
        """The tag exists, but add_tag's lookup misses it.

        Exactly what a competing insert committed between the lookup and our
        own insert looks like from here - and deterministic, which two real
        threads would not be.
        """
        from sqlmodel import Session

        from tagorganizer.models import Tag

        with Session(db.engine) as session:
            session.add(Tag(name="Beach"))
            session.commit()

        missed = []
        real_exec = Session.exec

        class _Empty:
            def first(self):
                return None

        def exec_(self, statement, *args, **kwargs):
            if not missed:
                missed.append(True)
                return _Empty()
            return real_exec(self, statement, *args, **kwargs)

        monkeypatch.setattr(Session, "exec", exec_)

    def test_the_loser_of_the_race_still_gets_a_usable_id(self, lost_race):
        tag_id = db.add_tag("Beach")
        assert tag_id is not None
        assert db.get_tag_by_id(tag_id).name == "Beach"

    def test_only_one_tag_exists_afterwards(self, lost_race):
        from sqlmodel import select

        from tagorganizer.models import Tag

        db.add_tag("Beach")
        with db.new_session() as session:
            assert len(session.exec(select(Tag)).all()) == 1
