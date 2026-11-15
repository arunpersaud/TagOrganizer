"""Matching items to directories by path prefix.

"Outside the photos directory" is a prefix test on stored uris. A bare LIKE
gets three things wrong: a sibling sharing the name as a prefix (/photos-old
is not inside /photos), "_" and "%" in a directory name acting as wildcards,
and ASCII case folding on filesystems that keep case.
"""

from pathlib import Path

import pytest
from sqlmodel import Session

from tagorganizer import db
from tagorganizer.models import Item


@pytest.fixture
def library(temp_db):
    uris = [
        "/photos/a.jpg",
        "/photos-old/b.jpg",
        "/my_pics/c.jpg",
        "/myXpics/d.jpg",
        "/Photos/e.jpg",
    ]
    with Session(temp_db) as session:
        session.add_all(Item(uri=uri) for uri in uris)
        session.commit()
    return uris


def outside(directory, suffix=".jpg"):
    found = db.get_all_items_not_in_dir([Path(directory)], [suffix])
    return sorted(item.uri for item in found)


class TestPrefixBoundary:
    def test_a_sibling_sharing_the_name_is_outside(self, library):
        assert "/photos-old/b.jpg" in outside("/photos")

    def test_the_directory_itself_is_inside(self, library):
        assert "/photos/a.jpg" not in outside("/photos")


class TestWildcardCharacters:
    def test_an_underscore_in_the_directory_is_literal(self, library):
        """LIKE would read "_" as any character, so /myXpics counted as inside."""
        assert "/myXpics/d.jpg" in outside("/my_pics")

    def test_the_directory_with_the_underscore_is_still_inside(self, library):
        assert "/my_pics/c.jpg" not in outside("/my_pics")


class TestCaseFollowsTheFilesystem:
    def test_case_is_kept_where_the_filesystem_keeps_it(self, library, monkeypatch):
        monkeypatch.setattr("tagorganizer.paths.is_case_insensitive", lambda p: False)
        assert "/Photos/e.jpg" in outside("/photos")

    def test_case_is_folded_where_the_filesystem_ignores_it(self, library, monkeypatch):
        monkeypatch.setattr("tagorganizer.paths.is_case_insensitive", lambda p: True)
        assert "/Photos/e.jpg" not in outside("/photos")
