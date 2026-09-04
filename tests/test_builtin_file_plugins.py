"""The file-moving and reporting plugins.

These move real files, so the destination logic is a pure function tested on
its own, and the plugins are exercised against a real temporary tree.
"""

from datetime import datetime
from pathlib import Path

from sqlmodel import Session

from tagorganizer import db
from tagorganizer.models import Item
from tagorganizer.plugins.builtin._move import destination_for
from tagorganizer.plugins.builtin.fix_no_date_files import FixNoDateFiles
from tagorganizer.plugins.builtin.list_files_not_in_db import ListFilesNotInDb
from tagorganizer.plugins.builtin.list_files_outside_dirs import ListFilesOutsideDirs
from tagorganizer.plugins.builtin.move_files import MoveFiles
from tagorganizer.plugins.context import TaskContext
from tagorganizer.scope import Scope


def run(plugin, tmp_path, photos=None, videos=None):
    messages = []
    ctx = TaskContext(
        Scope.LIBRARY,
        Path(photos or tmp_path),
        Path(videos or tmp_path),
        messages.append,
    )
    list(plugin.run(ctx))
    return messages


class TestScopeRefusal:
    """Moving an arbitrary subset of a library is a footgun, and the reports
    are whole-library questions by nature."""

    def test_moving_files_is_library_only(self):
        assert MoveFiles().accepts_selection is False

    def test_fixing_no_date_files_is_library_only(self):
        assert FixNoDateFiles().accepts_selection is False

    def test_reports_are_library_only(self):
        assert ListFilesNotInDb().accepts_selection is False
        assert ListFilesOutsideDirs().accepts_selection is False

    def test_none_of_them_run_automatically(self):
        """Nothing that moves files may start on its own."""
        assert not any(
            p.auto
            for p in (
                MoveFiles(),
                FixNoDateFiles(),
                ListFilesNotInDb(),
                ListFilesOutsideDirs(),
            )
        )


class TestDestinationFor:
    def test_a_dated_photo_goes_in_a_year_month_day_tree(self, tmp_path):
        item = Item(uri="/x/a.JPG", date=datetime(2021, 3, 7))
        target = destination_for(item, tmp_path / "p", tmp_path / "v")
        assert target == tmp_path / "p" / "2021" / "03" / "07" / "a.jpg"

    def test_the_extension_case_is_normalised(self, tmp_path):
        item = Item(uri="/x/a.JPG", date=datetime(2021, 3, 7))
        assert destination_for(item, tmp_path / "p", tmp_path / "v").suffix == ".jpg"

    def test_a_video_goes_under_the_video_directory(self, tmp_path):
        item = Item(uri="/x/a.mp4", date=datetime(2021, 3, 7))
        target = destination_for(item, tmp_path / "p", tmp_path / "v")
        assert str(target).startswith(str(tmp_path / "v"))

    def test_an_undated_item_goes_to_no_date(self, tmp_path):
        item = Item(uri="/x/a.jpg", date=None)
        target = destination_for(item, tmp_path / "p", tmp_path / "v")
        assert target == tmp_path / "p" / "no-date" / "a.jpg"

    def test_an_unknown_extension_has_no_destination(self, tmp_path):
        item = Item(uri="/x/notes.txt", date=datetime(2021, 3, 7))
        assert destination_for(item, tmp_path / "p", tmp_path / "v") is None


class TestMoveFiles:
    def test_a_file_is_moved_and_the_item_follows_it(self, temp_db, tmp_path):
        source = tmp_path / "loose" / "a.jpg"
        source.parent.mkdir()
        source.write_bytes(b"photo")
        target_root = tmp_path / "library"

        with Session(temp_db) as session:
            session.add(Item(uri=str(source), date=datetime(2021, 3, 7)))
            session.commit()

        run(MoveFiles(), tmp_path, photos=target_root, videos=target_root)

        moved = target_root / "2021" / "03" / "07" / "a.jpg"
        assert moved.is_file(), "the file was not moved"
        assert not source.exists()
        assert db.get_all_items()[0].uri == str(moved)

    def test_the_hashes_are_recomputed_for_the_new_path(self, temp_db, tmp_path):
        """uri_md5 keys the thumbnail cache, so a stale one orphans the cache."""
        source = tmp_path / "loose" / "a.jpg"
        source.parent.mkdir()
        source.write_bytes(b"photo")
        target_root = tmp_path / "library"

        with Session(temp_db) as session:
            session.add(
                Item(uri=str(source), date=datetime(2021, 3, 7), uri_md5="stale")
            )
            session.commit()

        run(MoveFiles(), tmp_path, photos=target_root, videos=target_root)
        assert db.get_all_items()[0].uri_md5 != "stale"

    def test_a_missing_file_is_reported_not_fatal(self, temp_db, tmp_path):
        with Session(temp_db) as session:
            session.add(Item(uri=str(tmp_path / "gone.jpg"), date=datetime(2021, 3, 7)))
            session.commit()

        messages = run(
            MoveFiles(), tmp_path, photos=tmp_path / "lib", videos=tmp_path / "lib"
        )
        assert any("does not exist" in m for m in messages)

    def test_an_existing_destination_is_not_overwritten(self, temp_db, tmp_path):
        """Two photos with the same name on the same day must not clobber."""
        source = tmp_path / "loose" / "a.jpg"
        source.parent.mkdir()
        source.write_bytes(b"new")
        target_root = tmp_path / "library"
        existing = target_root / "2021" / "03" / "07" / "a.jpg"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"original")

        with Session(temp_db) as session:
            session.add(Item(uri=str(source), date=datetime(2021, 3, 7)))
            session.commit()

        run(MoveFiles(), tmp_path, photos=target_root, videos=target_root)
        assert existing.read_bytes() == b"original"
        assert source.exists(), "the source was removed despite the collision"


class TestFixNoDateFiles:
    def test_an_item_that_now_has_a_date_is_moved_out(self, temp_db, tmp_path):
        target_root = tmp_path / "library"
        source = target_root / "no-date" / "a.jpg"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"photo")

        with Session(temp_db) as session:
            session.add(Item(uri=str(source), date=datetime(2021, 3, 7)))
            session.commit()

        run(FixNoDateFiles(), tmp_path, photos=target_root, videos=target_root)

        assert (target_root / "2021" / "03" / "07" / "a.jpg").is_file()

    def test_an_item_still_without_a_date_is_left_alone(self, temp_db, tmp_path):
        target_root = tmp_path / "library"
        source = target_root / "no-date" / "a.jpg"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"photo")

        with Session(temp_db) as session:
            session.add(Item(uri=str(source), date=None))
            session.commit()

        run(FixNoDateFiles(), tmp_path, photos=target_root, videos=target_root)
        assert source.is_file()


class TestListFilesNotInDb:
    def test_reports_a_file_on_disk_that_is_not_in_the_database(
        self, temp_db, tmp_path
    ):
        (tmp_path / "orphan.jpg").write_bytes(b"x")
        messages = run(ListFilesNotInDb(), tmp_path)
        assert any("orphan.jpg" in m for m in messages)

    def test_a_file_already_in_the_database_is_not_reported(self, temp_db, tmp_path):
        known = tmp_path / "known.jpg"
        known.write_bytes(b"x")
        with Session(temp_db) as session:
            session.add(Item(uri=str(known)))
            session.commit()

        messages = run(ListFilesNotInDb(), tmp_path)
        assert not any("known.jpg" in m for m in messages)

    def test_thumbnail_caches_are_not_reported(self, temp_db, tmp_path):
        """The cache lives beside the photos; it is not a missing import."""
        cache = tmp_path / "thumbnails"
        cache.mkdir()
        (cache / "abc.jpg").write_bytes(b"x")

        messages = run(ListFilesNotInDb(), tmp_path)
        assert not any("abc.jpg" in m for m in messages)


class TestListFilesOutsideDirs:
    def test_reports_an_item_stored_outside_the_configured_tree(
        self, temp_db, tmp_path
    ):
        outside = tmp_path / "elsewhere" / "stray.jpg"
        outside.parent.mkdir()
        outside.write_bytes(b"x")

        with Session(temp_db) as session:
            session.add(Item(uri=str(outside)))
            session.commit()

        messages = run(
            ListFilesOutsideDirs(),
            tmp_path,
            photos=tmp_path / "library",
            videos=tmp_path / "library",
        )
        assert any("stray.jpg" in m for m in messages)
