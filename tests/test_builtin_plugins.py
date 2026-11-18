"""The shipped enrichment plugins, exercised against a real database.

These are the eight tasks the app already had, rewritten against the public
plugin API. If the API could not express them it would not be ready for
anyone else's plugin, so these tests are as much about the API as the tasks.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlmodel import Session

from tagorganizer import db
from tagorganizer.models import Item
from tagorganizer.plugins.builtin.update_hashes import UpdateHashes
from tagorganizer.plugins.builtin.update_locations import UpdateLocations
from tagorganizer.plugins.builtin.update_timestamps import UpdateTimestamps
from tagorganizer.plugins.builtin.video_previews import VideoPreviews
from tagorganizer.plugins.context import TaskContext
from tagorganizer.scope import Scope, resolve_scope


@pytest.fixture
def photos(temp_db, tmp_path):
    """Three real files on disk, so hashing has something to hash."""
    ids = []
    with Session(temp_db) as session:
        for i in range(3):
            path = tmp_path / f"{i}.jpg"
            path.write_bytes(b"image-" + str(i).encode())
            item = Item(uri=str(path))
            session.add(item)
            session.commit()
            session.refresh(item)
            ids.append(item.id)
    return ids


def run(plugin, scope, tmp_path, messages=None):
    ctx = TaskContext(
        scope,
        Path(tmp_path),
        Path(tmp_path),
        messages.append if messages is not None else (lambda text: None),
    )
    steps = list(plugin.run(ctx))
    return steps


class TestUpdateHashes:
    def test_hashes_every_item_in_the_library(self, photos, tmp_path):
        run(UpdateHashes(), Scope.LIBRARY, tmp_path)
        assert all(i.data_xxhash for i in db.get_items_by_ids(photos))

    def test_a_selection_leaves_the_others_alone(self, photos, tmp_path):
        run(UpdateHashes(), resolve_scope(photos[:1]), tmp_path)
        rows = {i.id: i for i in db.get_items_by_ids(photos)}
        assert rows[photos[0]].data_xxhash
        assert not rows[photos[2]].data_xxhash

    def test_a_missing_file_is_skipped_not_fatal(self, photos, tmp_path):
        Path(db.get_items_by_ids([photos[0]])[0].uri).unlink()
        run(UpdateHashes(), Scope.LIBRARY, tmp_path)
        assert db.get_items_by_ids([photos[2]])[0].data_xxhash

    def test_it_yields_progress(self, photos, tmp_path):
        steps = run(UpdateHashes(), Scope.LIBRARY, tmp_path)
        assert steps
        assert all(len(step) == 2 for step in steps)

    def test_it_reports_what_it_did(self, photos, tmp_path):
        messages = []
        run(UpdateHashes(), Scope.LIBRARY, tmp_path, messages)
        assert messages

    def test_it_runs_automatically_after_an_import(self):
        assert UpdateHashes().auto is True

    def test_it_accepts_a_selection(self):
        assert UpdateHashes().accepts_selection is True

    def test_it_stops_when_cancelled(self, photos, tmp_path):
        """A cancelled task must not keep working through the library."""
        ctx = TaskContext(Scope.LIBRARY, tmp_path, tmp_path, lambda text: None)
        ctx.cancel()
        list(UpdateHashes().run(ctx))
        assert not any(i.data_xxhash for i in db.get_items_by_ids(photos))


class TestUpdateTimestamps:
    def test_a_file_without_exif_is_left_alone(self, photos, tmp_path):
        run(UpdateTimestamps(), Scope.LIBRARY, tmp_path)
        assert all(i.date is None for i in db.get_items_by_ids(photos))

    def test_it_yields_progress(self, photos, tmp_path):
        assert run(UpdateTimestamps(), Scope.LIBRARY, tmp_path)

    def test_it_accepts_a_selection(self):
        assert UpdateTimestamps().accepts_selection is True

    def test_it_runs_automatically_after_an_import(self):
        """A new photo should land on the timeline without a trip to the menu."""
        assert UpdateTimestamps().auto is True


class TestUpdateLocations:
    def test_a_file_without_gps_is_left_alone(self, photos, tmp_path):
        run(UpdateLocations(), Scope.LIBRARY, tmp_path)
        assert all(i.latitude is None for i in db.get_items_by_ids(photos))

    def test_it_yields_progress(self, photos, tmp_path):
        assert run(UpdateLocations(), Scope.LIBRARY, tmp_path)

    def test_it_accepts_a_selection(self):
        assert UpdateLocations().accepts_selection is True

    def test_it_runs_automatically_after_an_import(self):
        """A new photo should land on the map without a trip to the menu."""
        assert UpdateLocations().auto is True


class TestVideoPreviews:
    def test_photos_are_ignored(self, photos, tmp_path):
        """Stills already have thumbnails; only videos get a sprite sheet."""
        steps = run(VideoPreviews(), Scope.LIBRARY, tmp_path)
        assert steps[0][0] == 0

    def test_a_library_with_no_videos_still_completes(self, photos, tmp_path):
        """Otherwise the progress bar appears to hang at zero."""
        assert run(VideoPreviews(), Scope.LIBRARY, tmp_path)

    def test_videos_are_counted(self, temp_db, tmp_path):
        with Session(temp_db) as session:
            session.add(Item(uri=str(tmp_path / "a.mp4"), uri_md5="a" * 32))
            session.commit()
        steps = run(VideoPreviews(), Scope.LIBRARY, tmp_path)
        assert steps[0][0] == 1

    def test_an_existing_sheet_is_not_rebuilt(self, temp_db, tmp_path, monkeypatch):
        """Re-running must be cheap, so interrupting it loses nothing.

        Asserted on the extraction actually being skipped, not on the file
        being unchanged: extraction of a non-existent video changes nothing
        either way, so the file alone proves nothing.
        """
        from tagorganizer.plugins.builtin import video_previews
        from tagorganizer.widgets.helper import preview_file

        md5 = "c" * 32
        with Session(temp_db) as session:
            session.add(Item(uri=str(tmp_path / "done.mp4"), uri_md5=md5))
            session.commit()

        existing = preview_file(md5, 150, tmp_path)
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_bytes(b"already here")

        built = []
        monkeypatch.setattr(
            video_previews,
            "build_video_preview",
            lambda item, width, path: built.append(item.uri) or True,
        )

        run(VideoPreviews(), Scope.LIBRARY, tmp_path)
        assert built == [], "an existing sheet was extracted again"

    def test_a_video_without_a_sheet_is_built(self, temp_db, tmp_path, monkeypatch):
        """The counterpart: skipping must not skip everything."""
        from tagorganizer.plugins.builtin import video_previews

        with Session(temp_db) as session:
            session.add(Item(uri=str(tmp_path / "new.mp4"), uri_md5="d" * 32))
            session.commit()

        built = []
        monkeypatch.setattr(
            video_previews,
            "build_video_preview",
            lambda item, width, path: built.append(item.uri) or True,
        )

        run(VideoPreviews(), Scope.LIBRARY, tmp_path)
        assert len(built) == 1

    def test_it_runs_automatically_after_an_import(self):
        assert VideoPreviews().auto is True


class TestRegisteredCategories:
    def test_the_enrichment_plugins_share_a_category(self):
        categories = {
            UpdateHashes().category,
            UpdateTimestamps().category,
            UpdateLocations().category,
            VideoPreviews().category,
        }
        assert len(categories) == 1


class TestTimestampsFromVideosAndNames:
    """EXIF, then the container, then the filename."""

    def _item(self, temp_db, path):
        with Session(temp_db) as session:
            session.add(Item(uri=str(path)))
            session.commit()

    def test_a_video_gets_its_container_date(self, temp_db, tmp_path):
        from synthetic_media import write_mp4

        self._item(
            temp_db, write_mp4(tmp_path / "a.mp4", datetime(2021, 3, 7, 14, 25, 30))
        )
        run(UpdateTimestamps(), Scope.LIBRARY, tmp_path)
        # The container holds UTC; the item stores the same instant as local.
        expected = datetime(2021, 3, 7, 14, 25, 30, tzinfo=timezone.utc)
        assert db.get_all_items()[0].date == expected.astimezone().replace(tzinfo=None)

    def test_a_dated_filename_is_used_when_the_file_has_no_date(
        self, temp_db, tmp_path
    ):
        path = tmp_path / "IMG_20210307_142530.jpg"
        path.write_bytes(b"not really a jpeg")
        self._item(temp_db, path)

        run(UpdateTimestamps(), Scope.LIBRARY, tmp_path)
        assert db.get_all_items()[0].date == datetime(2021, 3, 7, 14, 25, 30)

    def test_the_container_date_beats_the_filename(self, temp_db, tmp_path):
        """The file's own record outranks a guess made from its name."""
        from synthetic_media import write_mp4

        self._item(
            temp_db,
            write_mp4(
                tmp_path / "VID_20200101_000000.mp4", datetime(2021, 3, 7, 14, 25, 30)
            ),
        )
        run(UpdateTimestamps(), Scope.LIBRARY, tmp_path)
        expected = datetime(2021, 3, 7, 14, 25, 30, tzinfo=timezone.utc)
        assert db.get_all_items()[0].date == expected.astimezone().replace(tzinfo=None)

    def test_an_undated_unnamed_file_stays_undated(self, temp_db, tmp_path):
        """Better no date than a wrong one."""
        path = tmp_path / "holiday.mp4"
        path.write_bytes(b"junk")
        self._item(temp_db, path)

        run(UpdateTimestamps(), Scope.LIBRARY, tmp_path)
        assert db.get_all_items()[0].date is None

    def test_a_video_without_a_container_date_falls_back_to_its_name(
        self, temp_db, tmp_path
    ):
        from synthetic_media import write_mp4

        self._item(temp_db, write_mp4(tmp_path / "VID_20210307_142530.mp4"))
        run(UpdateTimestamps(), Scope.LIBRARY, tmp_path)
        assert db.get_all_items()[0].date == datetime(2021, 3, 7, 14, 25, 30)


class TestLocationsFromVideos:
    def test_a_video_gets_its_container_gps(self, temp_db, tmp_path):
        from synthetic_media import write_mp4

        path = write_mp4(tmp_path / "a.mp4", None, gps=(40.7128, -74.0060))
        with Session(temp_db) as session:
            session.add(Item(uri=str(path)))
            session.commit()

        run(UpdateLocations(), Scope.LIBRARY, tmp_path)
        item = db.get_all_items()[0]
        assert round(item.latitude, 4) == 40.7128
        assert round(item.longitude, 4) == -74.0060

    def test_a_video_without_gps_is_left_alone(self, temp_db, tmp_path):
        from synthetic_media import write_mp4

        path = write_mp4(tmp_path / "a.mp4", datetime(2021, 3, 7))
        with Session(temp_db) as session:
            session.add(Item(uri=str(path)))
            session.commit()

        run(UpdateLocations(), Scope.LIBRARY, tmp_path)
        assert db.get_all_items()[0].latitude is None
