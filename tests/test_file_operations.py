"""The window's file operations and the grid's position rules, called directly.

Delete, copy and clamp used to be inline in MainWindow, where a failing unlink
aborted the whole loop. They are plain functions now, so these tests call the
real code. Failures are injected by replacing Path.unlink and shutil.copy from
outside, not by reimplementing either.
"""

import shutil
from pathlib import Path

import pytest

from tagorganizer import db
from tagorganizer.main import clamp_grid_position, copy_photos, delete_photos


def _photo(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_bytes(b"not really a jpeg, but a file all the same")
    return path


@pytest.fixture
def photos(temp_db, tmp_path):
    """Three real files, each registered as an item."""
    media = tmp_path / "media"
    media.mkdir()
    paths = [_photo(media, f"{name}.jpg") for name in ("a", "b", "c")]
    db.add_images(paths)
    return _items_for(paths)


def _items_for(paths):
    """The Item rows for these files, found by their uri."""
    from sqlmodel import Session, select

    from tagorganizer.models import Item

    with Session(db.engine) as session:
        return list(
            session.exec(
                select(Item).where(Item.uri.in_([str(p) for p in paths]))
            ).all()
        )


class TestDeletePhotos:
    def test_without_the_files_only_the_rows_go(self, photos):
        removed, failures = delete_photos(photos[:2], delete_files=False)

        assert failures == []
        assert sorted(removed) == sorted(i.id for i in photos[:2])
        assert len(db.get_items_by_ids([i.id for i in photos])) == 1

    def test_with_the_files_both_go(self, photos):
        _, failures = delete_photos(photos[:2], delete_files=True)

        assert failures == []
        assert not Path(photos[0].uri).exists()
        assert not Path(photos[1].uri).exists()

    def test_a_file_that_cannot_be_removed_keeps_its_row(self, photos, monkeypatch):
        """Dropping the row while the file is still there would let the next
        import add the photo back as new."""
        stuck = Path(photos[1].uri)
        real_unlink = Path.unlink

        def unlink(self, *args, **kwargs):
            if self == stuck:
                raise PermissionError(13, "Operation not permitted")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)

        removed, failures = delete_photos(photos, delete_files=True)

        assert photos[1].id not in removed
        assert len(failures) == 1 and "Operation not permitted" in failures[0]
        assert db.get_items_by_ids([photos[1].id])  # row still there
        assert not Path(photos[0].uri).exists()  # the others still went
        assert not Path(photos[2].uri).exists()

    def test_a_file_already_gone_is_not_a_failure(self, photos):
        Path(photos[0].uri).unlink()

        removed, failures = delete_photos(photos[:1], delete_files=True)

        assert failures == []
        assert removed == [photos[0].id]


class TestCopyPhotos:
    def test_every_photo_is_copied(self, photos, tmp_path):
        target = tmp_path / "out"
        target.mkdir()

        copied, problems = copy_photos(photos, target)

        assert copied == 3
        assert problems == []
        assert (target / "a.jpg").is_file()

    def test_a_failed_copy_is_reported_and_the_rest_still_go(
        self, photos, tmp_path, monkeypatch
    ):
        target = tmp_path / "out"
        target.mkdir()
        real_copy = shutil.copy

        def copy(source, destination, *args, **kwargs):
            if Path(source).name == "b.jpg":
                raise OSError(28, "No space left on device")
            return real_copy(source, destination, *args, **kwargs)

        monkeypatch.setattr(shutil, "copy", copy)

        copied, problems = copy_photos(photos, target)

        assert copied == 2
        assert any("No space left" in p for p in problems)
        assert (target / "c.jpg").is_file()

    def test_an_existing_name_is_skipped_not_overwritten(self, photos, tmp_path):
        target = tmp_path / "out"
        target.mkdir()
        (target / "a.jpg").write_bytes(b"keep me")

        copied, problems = copy_photos(photos[:1], target)

        assert copied == 0
        assert (target / "a.jpg").read_bytes() == b"keep me"
        assert problems


class TestClampGridPosition:
    def test_a_frame_past_a_shrunken_result_moves_to_its_last_item(self):
        # Page 10 of 12 per page, with the frame on its first tile, then a
        # filter leaves 5 photos.
        assert clamp_grid_position(120, 5, 12) == (4, 0)

    def test_a_frame_that_still_fits_is_untouched(self):
        assert clamp_grid_position(14, 40, 12) == (14, 1)

    def test_an_empty_result_puts_everything_at_zero(self):
        assert clamp_grid_position(7, 0, 12) == (0, 0)

    def test_a_negative_frame_is_brought_back_on_screen(self):
        assert clamp_grid_position(-1, 10, 12) == (0, 0)
