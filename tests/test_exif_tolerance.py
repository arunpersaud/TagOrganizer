"""One malformed file must not end a metadata run.

The location and timestamp plugins work through a batch of files, and an
exception from any one of them used to abort the run. The batch in hand was
lost, and the same file failed again on every rerun.
"""

from datetime import datetime

from exifread.classes import Ratio
from sqlmodel import Session

from synthetic_media import write_mp4
from tagorganizer import db
from tagorganizer.models import Item
from tagorganizer.plugins.builtin import update_locations, update_timestamps
from tagorganizer.plugins.builtin.update_locations import UpdateLocations
from tagorganizer.plugins.builtin.update_timestamps import UpdateTimestamps
from tagorganizer.plugins.context import TaskContext
from tagorganizer.scope import Scope


class _Tag:
    def __init__(self, *values):
        self.values = list(values)


def _ctx(tmp_path, messages):
    return TaskContext(Scope.LIBRARY, tmp_path, tmp_path, messages.append)


def _add(temp_db, *paths):
    with Session(temp_db) as session:
        for path in paths:
            session.add(Item(uri=str(path)))
        session.commit()


def _by_name(name):
    return next(item for item in db.get_all_items() if item.uri.endswith(name))


class TestMalformedLocations:
    def test_a_zero_denominator_does_not_stop_the_run(
        self, temp_db, tmp_path, monkeypatch
    ):
        """0/0 rationals raise ZeroDivisionError in to_degrees. The second file
        must still be located, which proves the run went on."""
        bad = tmp_path / "bad.jpg"
        good = tmp_path / "good.mp4"
        bad.write_bytes(b"x")
        good_path = write_mp4(good, None, gps=(40.7128, -74.0060))
        _add(temp_db, bad, good_path)

        def exif(path):
            if path == bad:
                zero = Ratio(0, 0)
                return {
                    "GPS GPSLatitude": _Tag(zero, zero, zero),
                    "GPS GPSLongitude": _Tag(zero, zero, zero),
                }
            return {}

        monkeypatch.setattr(update_locations, "load_exif", exif)
        messages = []
        list(UpdateLocations().run(_ctx(tmp_path, messages)))

        assert _by_name("good.mp4").latitude is not None
        assert _by_name("bad.jpg").latitude is None
        assert any("bad.jpg" in m and "Skip" in m for m in messages), messages

    def test_too_few_coordinate_parts_does_not_stop_the_run(
        self, temp_db, tmp_path, monkeypatch
    ):
        bad = tmp_path / "bad.jpg"
        good = write_mp4(tmp_path / "good.mp4", None, gps=(51.5, -0.12))
        bad.write_bytes(b"x")
        _add(temp_db, bad, good)

        def exif(path):
            if path == bad:
                return {
                    "GPS GPSLatitude": _Tag(1),
                    "GPS GPSLongitude": _Tag(1),
                }
            return {}

        monkeypatch.setattr(update_locations, "load_exif", exif)
        list(UpdateLocations().run(_ctx(tmp_path, [])))
        assert _by_name("good.mp4").latitude is not None

    def test_the_batch_in_hand_is_saved_before_a_bad_file(
        self, temp_db, tmp_path, monkeypatch
    ):
        """Good items before a bad one must not be lost with the run."""
        good = [
            write_mp4(tmp_path / f"g{i}.mp4", None, gps=(10.0 + i, 20.0))
            for i in range(3)
        ]
        bad = tmp_path / "bad.jpg"
        bad.write_bytes(b"x")
        _add(temp_db, *good, bad)

        def exif(path):
            if path == bad:
                raise ValueError("corrupt EXIF")
            return {}

        monkeypatch.setattr(update_locations, "load_exif", exif)
        list(UpdateLocations().run(_ctx(tmp_path, [])))
        located = [item for item in db.get_all_items() if item.latitude is not None]
        assert len(located) == 3


class TestMalformedTimestamps:
    def test_an_unreadable_exif_block_does_not_stop_the_run(
        self, temp_db, tmp_path, monkeypatch
    ):
        bad = tmp_path / "bad.jpg"
        bad.write_bytes(b"x")
        good = write_mp4(tmp_path / "good.mp4", datetime(2021, 3, 7, 12, 0, 0))
        _add(temp_db, bad, good)

        def exif(path):
            if path == bad:
                raise IndexError("truncated IFD")
            return {}

        monkeypatch.setattr(update_timestamps, "load_exif", exif)
        messages = []
        list(UpdateTimestamps().run(_ctx(tmp_path, messages)))

        assert _by_name("good.mp4").date is not None
        assert any("bad.jpg" in m and "Skip" in m for m in messages), messages
