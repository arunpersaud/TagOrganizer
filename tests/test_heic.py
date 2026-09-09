"""HEIC photos, whose brand exifread does not always recognise.

exifread 3.0.0 dispatches on the exact bytes b'ftypheic' and returns nothing
for every other HEIF brand, though its HEIC reader handles them all. An iPhone
photo written as 'mif1' would otherwise import with no date and no location
while looking perfectly fine.
"""

import os
import struct
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


from tagorganizer import config
from tagorganizer.metadata import heif_brand


def write_heif(path, brand=b"mif1"):
    """A file carrying a HEIF ftyp box.

    Not a decodable image: only the brand matters for the detection under test.
    """
    payload = brand + struct.pack(">I", 0) + b"mif1heic"
    path.write_bytes(struct.pack(">I", len(payload) + 8) + b"ftyp" + payload)
    return path


class TestBrandDetection:
    @pytest.mark.parametrize(
        "brand", [b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"heim", b"heis"]
    )
    def test_every_heif_brand_is_recognised(self, tmp_path, brand):
        assert heif_brand(write_heif(tmp_path / "a.heic", brand)) == brand

    def test_a_jpeg_is_not_a_heif(self, tmp_path):
        path = tmp_path / "a.jpg"
        path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
        assert heif_brand(path) is None

    def test_an_mp4_is_not_a_heif(self, tmp_path):
        """Both are ISO-BMFF with an ftyp box; only the brand separates them."""
        from synthetic_media import write_mp4

        assert heif_brand(write_mp4(tmp_path / "a.mp4", datetime(2021, 3, 7))) is None

    def test_a_heif_brand_without_an_ftyp_box_is_not_a_heif(self, tmp_path):
        """The brand only means something inside an ftyp box.

        Without checking the box kind, any file whose ninth to twelfth bytes
        happened to spell a brand would be treated as a photo.
        """
        path = tmp_path / "coincidence.bin"
        path.write_bytes(b"\x00\x00\x00\x14junkheic" + b"\x00" * 8)
        assert heif_brand(path) is None

    def test_a_short_file_is_not_a_heif(self, tmp_path):
        path = tmp_path / "tiny"
        path.write_bytes(b"ab")
        assert heif_brand(path) is None

    def test_a_missing_file_is_not_a_heif(self, tmp_path):
        assert heif_brand(tmp_path / "gone.heic") is None


class TestExifIsAttemptedForEveryBrand:
    def test_a_mif1_file_reaches_exifreads_heic_reader(self, tmp_path, monkeypatch):
        """The brand is rewritten so exifread will look at all.

        Asserted on exifread being handed a HEIC-branded stream, because these
        stub files carry no real EXIF to read back.
        """
        from tagorganizer.widgets import helper

        seen = {}

        def fake_process_file(handle, *args, **kwargs):
            seen["header"] = handle.read(12)
            return {}

        monkeypatch.setattr(helper.exif, "process_file", fake_process_file)
        helper.load_exif(write_heif(tmp_path / "a.heic", b"mif1"))

        assert seen["header"][4:12] == b"ftypheic"

    def test_a_jpeg_is_passed_through_untouched(self, tmp_path, monkeypatch):
        from tagorganizer.widgets import helper

        path = tmp_path / "a.jpg"
        path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

        seen = {}

        def fake_process_file(handle, *args, **kwargs):
            seen["bytes"] = handle.read()
            return {}

        monkeypatch.setattr(helper.exif, "process_file", fake_process_file)
        helper.load_exif(path)

        # The whole file, not just its first bytes: a brand rewrite applied
        # indiscriminately would corrupt bytes 8 to 12 of a JPEG and leave the
        # magic number looking fine.
        assert seen["bytes"] == path.read_bytes()


class TestSuffixes:
    @pytest.mark.parametrize("ext", [".heic", ".heif"])
    def test_heic_counts_as_a_photo(self, ext):
        assert ext in config.PHOTO_SUFFIX

    @pytest.mark.parametrize("ext", [".3gp", ".m4v"])
    def test_the_new_video_formats_are_recognised(self, ext):
        assert ext in config.VIDEO_SUFFIX

    def test_photos_and_videos_do_not_overlap(self):
        """A suffix in both lists would make routing depend on list order."""
        assert not set(config.PHOTO_SUFFIX) & set(config.VIDEO_SUFFIX)

    def test_every_suffix_is_lowercase_with_a_dot(self):
        """Callers compare against suffix.lower(), so an entry that is not
        lowercase could never match."""
        for ext in config.ALL_SUFFIX:
            assert ext == ext.lower() and ext.startswith(".")


class TestUndecodableImages:
    """A format Qt cannot read must degrade, not raise.

    Qt reads HEIC here, but that depends on qtimageformats and is not
    guaranteed on Linux or Windows. On a machine without it, every HEIC tile
    takes this path.
    """

    def test_a_photo_qt_cannot_read_does_not_raise_when_emitted(self, qapp):
        from tagorganizer.widgets.helper import ThumbnailResultEmitter

        emitter = ThumbnailResultEmitter()
        received = []
        emitter.thumbnail_ready.connect(lambda key, image: received.append(image))

        # This is what the decode path returns for a file Qt cannot read.
        emitter.handle_result(("id", 150), None)

        assert received == [] or received[0].isNull()
