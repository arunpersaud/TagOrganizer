"""The fixture builder is load-bearing, so it is tested too.

Every video test below rests on these bytes being a real MP4. A broken builder
would make those tests agree with each other and with nothing else.
"""

from datetime import datetime

from synthetic_media import write_mp4


def boxes(data):
    """Top-level box kinds, for asserting on structure."""
    found, offset = [], 0
    while offset + 8 <= len(data):
        size = int.from_bytes(data[offset : offset + 4], "big")
        found.append(data[offset + 4 : offset + 8])
        if size < 8:
            break
        offset += size
    return found


class TestWriteMp4:
    def test_it_writes_a_recognisable_mp4(self, tmp_path):
        path = write_mp4(tmp_path / "a.mp4", datetime(2021, 3, 7, 14, 25, 30))
        assert boxes(path.read_bytes())[:2] == [b"ftyp", b"moov"]

    def test_hachoir_can_parse_what_we_write(self, tmp_path):
        """If hachoir cannot read our fixture, the fixture is wrong."""
        import hachoir.core.config as cfg

        cfg.quiet = True
        from hachoir.metadata import extractMetadata
        from hachoir.parser import createParser

        path = write_mp4(tmp_path / "a.mp4", datetime(2021, 3, 7, 14, 25, 30))
        metadata = extractMetadata(createParser(str(path)))
        assert metadata.get("creation_date") == datetime(2021, 3, 7, 14, 25, 30)

    def test_gps_is_embedded_when_asked_for(self, tmp_path):
        path = write_mp4(tmp_path / "a.mp4", None, gps=(40.7128, -74.0060))
        assert b"\xa9xyz" in path.read_bytes()

    def test_no_gps_box_when_not_asked_for(self, tmp_path):
        path = write_mp4(tmp_path / "a.mp4", datetime(2021, 3, 7))
        assert b"\xa9xyz" not in path.read_bytes()

    def test_a_file_with_neither_is_still_valid(self, tmp_path):
        path = write_mp4(tmp_path / "a.mp4")
        assert boxes(path.read_bytes())[:2] == [b"ftyp", b"moov"]

    def test_the_returned_path_is_the_file(self, tmp_path):
        path = write_mp4(tmp_path / "a.mp4", datetime(2021, 3, 7))
        assert path.is_file() and path.name == "a.mp4"

    def test_box_sizes_cover_the_whole_file(self, tmp_path):
        """A wrong length field would make the walk in metadata.py misbehave."""
        data = write_mp4(
            tmp_path / "a.mp4", datetime(2021, 3, 7), gps=(1.0, 2.0)
        ).read_bytes()
        total = 0
        while total + 8 <= len(data):
            total += int.from_bytes(data[total : total + 4], "big")
        assert total == len(data)
