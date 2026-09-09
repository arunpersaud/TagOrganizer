"""Clearing out cached thumbnails nothing points at any more.

forget_thumbnail handles a file that moves, but a photo deleted outside the
application, or removed from the library, leaves its cache entries behind
forever. On a large library that is real disk.
"""

import pytest
from sqlmodel import Session

from tagorganizer.models import Item
from tagorganizer.plugins.builtin.prune_cache import PruneThumbnailCache
from tagorganizer.plugins.context import TaskContext
from tagorganizer.scope import Scope
from tagorganizer.widgets.helper import cached_hashes, preview_file, thumbnail_file


@pytest.fixture
def cache(temp_db, tmp_path):
    """One item in the library, with cache entries for it and for two ghosts."""
    kept = "a" * 32
    ghost = "b" * 32
    ghost_preview = "c" * 32

    with Session(temp_db) as session:
        session.add(Item(uri=str(tmp_path / "kept.jpg"), uri_md5=kept))
        session.commit()

    for path in (
        thumbnail_file(kept, 150, tmp_path),
        thumbnail_file(ghost, 150, tmp_path),
        thumbnail_file(ghost, 300, tmp_path),
        preview_file(ghost_preview, 150, tmp_path),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 100)

    return {"kept": kept, "ghost": ghost, "ghost_preview": ghost_preview}


def run(plugin, tmp_path):
    messages = []
    ctx = TaskContext(Scope.LIBRARY, tmp_path, tmp_path, messages.append)
    list(plugin.run(ctx))
    return messages


class TestCachedHashes:
    def test_it_finds_every_cached_hash(self, cache, tmp_path):
        found = {md5 for md5, _ in cached_hashes(tmp_path)}
        assert found == {cache["kept"], cache["ghost"], cache["ghost_preview"]}

    def test_it_reports_each_file_separately(self, cache, tmp_path):
        """The same hash is cached once per size."""
        sizes = [path for md5, path in cached_hashes(tmp_path) if md5 == cache["ghost"]]
        assert len(sizes) == 2

    def test_an_empty_cache_yields_nothing(self, temp_db, tmp_path):
        assert list(cached_hashes(tmp_path)) == []

    def test_a_missing_cache_directory_is_not_an_error(self, temp_db, tmp_path):
        assert list(cached_hashes(tmp_path / "nowhere")) == []


class TestPruning:
    def test_an_orphaned_thumbnail_is_deleted(self, cache, tmp_path):
        run(PruneThumbnailCache(), tmp_path)
        assert not thumbnail_file(cache["ghost"], 150, tmp_path).exists()

    def test_every_size_of_an_orphan_goes(self, cache, tmp_path):
        run(PruneThumbnailCache(), tmp_path)
        assert not thumbnail_file(cache["ghost"], 300, tmp_path).exists()

    def test_an_orphaned_video_preview_is_deleted(self, cache, tmp_path):
        run(PruneThumbnailCache(), tmp_path)
        assert not preview_file(cache["ghost_preview"], 150, tmp_path).exists()

    def test_a_thumbnail_still_in_the_library_is_kept(self, cache, tmp_path):
        """Deleting these would make the grid re-decode the whole library."""
        run(PruneThumbnailCache(), tmp_path)
        assert thumbnail_file(cache["kept"], 150, tmp_path).exists()

    def test_it_reports_what_it_freed(self, cache, tmp_path):
        messages = run(PruneThumbnailCache(), tmp_path)
        assert any("3" in m for m in messages), messages

    def test_running_twice_is_harmless(self, cache, tmp_path):
        run(PruneThumbnailCache(), tmp_path)
        run(PruneThumbnailCache(), tmp_path)
        assert thumbnail_file(cache["kept"], 150, tmp_path).exists()

    def test_an_empty_library_does_not_delete_a_cache_it_cannot_explain(
        self, temp_db, tmp_path
    ):
        """A library with no items has no hashes, so everything looks orphaned
        - which is right, but only because the scope really is everything."""
        path = thumbnail_file("d" * 32, 150, tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

        run(PruneThumbnailCache(), tmp_path)
        assert not path.exists()


class TestScope:
    def test_it_is_library_only(self):
        """Pruning against a selection would treat every unselected photo's
        cache as an orphan and delete the lot."""
        assert PruneThumbnailCache().accepts_selection is False

    def test_it_does_not_run_automatically(self):
        assert PruneThumbnailCache().auto is False
