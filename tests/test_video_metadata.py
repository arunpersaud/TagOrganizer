"""Dates and places out of video containers.

hachoir reads the date across mp4, mov, avi, mkv and wmv. It surfaces no GPS
at all, so the ©xyz box is read directly - and only the ISO-BMFF family
records GPS in the first place.
"""

from datetime import datetime

from synthetic_media import write_mp4

from tagorganizer.metadata import video_date, video_gps


class TestVideoDate:
    def test_reads_the_container_creation_time(self, tmp_path):
        path = write_mp4(tmp_path / "a.mp4", datetime(2021, 3, 7, 14, 25, 30))
        assert video_date(path) == datetime(2021, 3, 7, 14, 25, 30)

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
