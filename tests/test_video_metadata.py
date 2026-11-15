"""Dates and places out of video containers.

hachoir reads the date across mp4, mov, avi, mkv and wmv. It surfaces no GPS
at all, so the ©xyz box is read directly - and only the ISO-BMFF family
records GPS in the first place.
"""

import time
from datetime import datetime, timezone

import pytest
from synthetic_media import write_mp4

from tagorganizer.metadata import video_date, video_gps


class TestVideoDate:
    def test_reads_the_container_creation_time(self, tmp_path):
        """The container holds UTC; the result is the same instant as local
        time, which is what the EXIF dates beside it are stored as."""
        when = datetime(2021, 3, 7, 14, 25, 30)
        path = write_mp4(tmp_path / "a.mp4", when)
        expected = when.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        assert video_date(path) == expected

    @pytest.mark.skipif(not hasattr(time, "tzset"), reason="needs POSIX TZ")
    def test_the_result_is_local_time_not_utc(self, tmp_path, monkeypatch):
        """Pinned to a zone with a fixed offset, so the expectation is exact:
        14:25 UTC is 23:25 in Tokyo, and 14:25 would mean the conversion was
        skipped."""
        monkeypatch.setenv("TZ", "Asia/Tokyo")
        time.tzset()
        try:
            path = write_mp4(tmp_path / "a.mp4", datetime(2021, 3, 7, 14, 25, 30))
            assert video_date(path) == datetime(2021, 3, 7, 23, 25, 30)
        finally:
            monkeypatch.undo()
            time.tzset()

    def test_the_unset_mp4_time_is_not_a_date(self, tmp_path):
        """A zero creation time decodes to 1904-01-01, which an earlier version
        accepted as a capture date."""
        path = write_mp4(tmp_path / "a.mp4", datetime(1904, 1, 1))
        assert video_date(path) is None

    def test_a_date_in_the_future_is_not_a_date(self, tmp_path):
        # 2035 rather than something far off: a 32-bit MP4 time cannot hold
        # dates past 2040, and the synthetic writer is limited by that.
        path = write_mp4(tmp_path / "a.mp4", datetime(2035, 1, 1))
        assert video_date(path) is None

    def test_a_video_without_a_date_gives_none(self, tmp_path):
        assert video_date(write_mp4(tmp_path / "a.mp4")) is None

    def test_an_unparseable_file_gives_none_rather_than_raising(self, tmp_path):
        broken = tmp_path / "broken.mp4"
        broken.write_bytes(b"not a video at all")
        assert video_date(broken) is None

    def test_a_missing_file_gives_none(self, tmp_path):
        assert video_date(tmp_path / "gone.mp4") is None

    def test_an_empty_file_gives_none(self, tmp_path):
        empty = tmp_path / "empty.mp4"
        empty.write_bytes(b"")
        assert video_date(empty) is None

    def test_it_does_not_print_to_stderr(self, tmp_path, capfd):
        """hachoir warns loudly about every parser it tries and rejects.

        This project moved off printing to the logging module deliberately; a
        task running over a whole library would otherwise bury the console.
        """
        broken = tmp_path / "broken.mp4"
        broken.write_bytes(b"not a video at all")
        video_date(broken)
        captured = capfd.readouterr()
        assert captured.err == "" and captured.out == ""


class TestVideoGps:
    def test_reads_the_xyz_box(self, tmp_path):
        path = write_mp4(tmp_path / "a.mp4", None, gps=(40.7128, -74.0060))
        latitude, longitude = video_gps(path)
        assert round(latitude, 4) == 40.7128
        assert round(longitude, 4) == -74.0060

    def test_southern_and_eastern_coordinates(self, tmp_path):
        """Sydney: negative latitude, positive longitude.

        Catches a swapped pair, which a symmetric example would not.
        """
        path = write_mp4(tmp_path / "a.mp4", None, gps=(-33.8688, 151.2093))
        latitude, longitude = video_gps(path)
        assert round(latitude, 4) == -33.8688
        assert round(longitude, 4) == 151.2093

    def test_a_video_without_gps_gives_none(self, tmp_path):
        assert video_gps(write_mp4(tmp_path / "a.mp4", datetime(2021, 3, 7))) is None

    def test_a_non_video_gives_none(self, tmp_path):
        broken = tmp_path / "broken.mp4"
        broken.write_bytes(b"not a video at all")
        assert video_gps(broken) is None

    def test_a_missing_file_gives_none(self, tmp_path):
        assert video_gps(tmp_path / "gone.mp4") is None

    def test_a_truncated_box_does_not_hang_or_raise(self, tmp_path):
        """A zero length field would leave the walk looping on one box."""
        path = tmp_path / "truncated.mp4"
        path.write_bytes(b"\x00\x00\x00\x00moov" + b"\x00" * 8)
        assert video_gps(path) is None

    def test_a_box_claiming_more_than_the_file_holds_is_refused(self, tmp_path):
        path = tmp_path / "overlong.mp4"
        path.write_bytes(b"\xff\xff\xff\xffmoov" + b"\x00" * 8)
        assert video_gps(path) is None


def _moov_with_gps(latitude, longitude):
    """A moov box holding the ©xyz location, built without its own header."""
    from synthetic_media import _box, _xyz

    return _box(b"udta", _xyz(latitude, longitude))


class TestContainerLayouts:
    """Layouts a phone or a large camera file can produce."""

    def test_a_64_bit_box_before_moov_is_stepped_over(self, tmp_path):
        """mdat written with a largesize header, ahead of moov. Refusing size 1
        meant such a file lost its location entirely."""
        from synthetic_media import _box

        mdat_body = b"\x00" * 64
        mdat = b"\x00\x00\x00\x01mdat" + (16 + len(mdat_body)).to_bytes(8, "big")
        mdat += mdat_body
        moov = _box(b"moov", _moov_with_gps(40.7128, -74.0060))
        path = tmp_path / "large.mp4"
        path.write_bytes(_box(b"ftyp", b"isom" + b"\x00" * 8) + mdat + moov)
        latitude, longitude = video_gps(path)
        assert round(latitude, 4) == 40.7128
        assert round(longitude, 4) == -74.0060

    def test_a_box_that_runs_to_the_end_of_the_file(self, tmp_path):
        """Size 0 means 'to the end'; a moov written that way is the last box."""
        from synthetic_media import _box

        moov = _box(b"moov", _moov_with_gps(-33.8688, 151.2093))
        open_ended = b"\x00\x00\x00\x00" + moov[4:]
        path = tmp_path / "open.mp4"
        path.write_bytes(_box(b"ftyp", b"isom" + b"\x00" * 8) + open_ended)
        latitude, longitude = video_gps(path)
        assert round(latitude, 4) == -33.8688
        assert round(longitude, 4) == 151.2093

    def test_the_file_is_not_read_whole(self, tmp_path, monkeypatch):
        """A multi-gigabyte video must not be pulled into memory to find a
        box near its end. read_bytes is replaced so any whole-file read fails
        the test rather than the machine."""
        from pathlib import Path as _Path

        from synthetic_media import _box

        big = _box(b"mdat", b"\x00" * (1024 * 1024))
        path = tmp_path / "big.mp4"
        path.write_bytes(
            _box(b"ftyp", b"isom" + b"\x00" * 8)
            + big
            + _box(b"moov", _moov_with_gps(40.7128, -74.0060))
        )

        def refuse(self, *args, **kwargs):
            raise AssertionError("video_gps read the whole file")

        monkeypatch.setattr(_Path, "read_bytes", refuse)
        assert video_gps(path) is not None
