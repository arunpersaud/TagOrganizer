"""The Unnamed faces filter: photos with a face that nobody has named yet.

A photo is on the list when the face task found at least one face in it and
it carries no tag from the People tree. Naming anyone, or tagging it plain
"People" for strangers, takes it off. Assertions are on the items a real
database returns, like the other filter tests.
"""

import pytest
from sqlmodel import Session, select

from tagorganizer import db
from tagorganizer.models import Item, ItemTagLink, Tag
from tagorganizer.widgets.tag_bar import Filters


@pytest.fixture
def library(temp_db):
    """People > Alice, and an unrelated Beach.

    named:     2 faces, Alice
    plain:     1 face,  People itself
    unnamed:   2 faces, Beach
    noface:    checked, no faces
    unchecked: never checked
    video:     a video, never checked
    """
    with Session(temp_db) as session:
        people = Tag(name="People")
        beach = Tag(name="Beach")
        session.add_all([people, beach])
        session.commit()
        alice = Tag(name="Alice", parent_id=people.id)
        session.add(alice)
        session.commit()

        items = {}
        for name, faces, suffix in (
            ("named", 2, "jpg"),
            ("plain", 1, "jpg"),
            ("unnamed", 2, "jpg"),
            ("noface", 0, "jpg"),
            ("unchecked", None, "jpg"),
            ("video", None, "mp4"),
        ):
            item = Item(uri=f"/p/{name}.{suffix}", face_count=faces)
            session.add(item)
            items[name] = item
        session.commit()
        for item in items.values():
            session.refresh(item)

        for item_name, tag in (("named", alice), ("plain", people), ("unnamed", beach)):
            session.add(ItemTagLink(item_id=items[item_name].id, tag_id=tag.id))
        session.commit()
        return {name: item.id for name, item in items.items()}


def names(filters):
    return sorted(
        item.uri.split("/")[-1].split(".")[0] for item in db.get_images(0, filters)
    )


def test_only_photos_with_unnamed_faces_are_shown(library):
    assert names(Filters(unnamed_faces=True)) == ["unnamed"]


def test_without_a_people_tag_every_photo_with_faces_is_shown(library):
    assert names(Filters(unnamed_faces=True, people_tag="Nobody")) == [
        "named",
        "plain",
        "unnamed",
    ]


def test_the_people_tag_matches_case_insensitively(library):
    assert names(Filters(unnamed_faces=True, people_tag="people")) == ["unnamed"]


def test_a_tag_two_levels_down_still_counts_as_named(library, temp_db):
    with Session(temp_db) as session:
        people = session.exec(select(Tag).where(Tag.name == "People")).one()
        family = Tag(name="Family", parent_id=people.id)
        session.add(family)
        session.commit()
        bob = Tag(name="Bob", parent_id=family.id)
        session.add(bob)
        session.commit()
        session.add(ItemTagLink(item_id=library["unnamed"], tag_id=bob.id))
        session.commit()

    assert names(Filters(unnamed_faces=True)) == []


def test_it_combines_with_other_filters(library):
    assert names(Filters(unnamed_faces=True, tags=["Beach"])) == ["unnamed"]
    assert names(Filters(unnamed_faces=True, tags=["Alice"])) == []
