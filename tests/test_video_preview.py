"""Sprite sheets for animated video previews.

The geometry helpers are pure arithmetic and need neither Qt nor a video. The
extraction test generates its own clip with ffmpeg and skips when ffmpeg is
absent, so no binary fixture is committed.
"""

import os
import shutil
import subprocess

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tagorganizer.widgets.helper import (
    SPRITE_COLUMNS,
    SPRITE_FRAMES,
    forget_thumbnail,
    frame_positions,
    preview_file,
    sprite_frame_rect,
    thumbnail_file,
)


class TestFramePositions:
    def test_long_video_samples_forty_frames(self):
        assert len(frame_positions(1800)) == SPRITE_FRAMES

    def test_positions_are_in_range_and_increasing(self):
        positions = frame_positions(1800)
        assert positions == sorted(set(positions))
        assert all(0 <= p < 1800 for p in positions)

    def test_short_video_yields_fewer_frames_rather_than_duplicates(self):
        """A 7-frame clip gets 7 distinct frames, not 40 repeats.

        Padding the sheet by repeating frames would read as a stuttering,
        broken preview.
        """
        positions = frame_positions(7)
        assert len(positions) == 7
        assert positions == sorted(set(positions))

    def test_single_frame_video(self):
        assert frame_positions(1) == [0]

    def test_empty_or_unreadable_video(self):
        assert frame_positions(0) == []
        assert frame_positions(-1) == []


class TestSpriteGeometry:
    def test_first_frame_is_top_left(self):
        assert sprite_frame_rect(0, 150, 84) == (0, 0, 150, 84)

    def test_row_wraps_after_eight_columns(self):
        assert sprite_frame_rect(7, 150, 84) == (1050, 0, 150, 84)
        assert sprite_frame_rect(8, 150, 84) == (0, 84, 150, 84)

    def test_last_frame_is_bottom_right(self):
        assert sprite_frame_rect(39, 150, 84) == (1050, 336, 150, 84)


class TestPreviewFile:
    def test_lives_in_its_own_subtree(self, tmp_path):
        """A sprite sheet must never be mistaken for a still thumbnail."""
        still = thumbnail_file("abcdef0123456789", 150, tmp_path)
        preview = preview_file("abcdef0123456789", 150, tmp_path)
        assert preview != still
        assert "preview" in preview.parts

    def test_size_is_part_of_the_path(self, tmp_path):
        assert preview_file("abcdef0123456789", 150, tmp_path) != preview_file(
            "abcdef0123456789", 300, tmp_path
        )


class TestForgetThumbnailClearsPreviews:
    def test_preview_is_removed_too(self, tmp_path):
        """A moved video changes its uri hash, so a left-behind sheet is dead.

        The still cache had exactly this orphaning problem; the preview cache
        must not repeat it.
        """
        md5 = "abcdef0123456789"
        still = thumbnail_file(md5, 150, tmp_path)
        preview = preview_file(md5, 150, tmp_path)
        for path in (still, preview):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not really a png")

        forget_thumbnail(md5, tmp_path)

        assert not still.exists()
        assert not preview.exists()


@pytest.fixture
def tiny_video(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg not available to generate a fixture")
    out = tmp_path / "clip.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=320x240:rate=15",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out


class TestBuildVideoPreview:
    def test_writes_a_sheet_of_the_expected_shape(self, tiny_video, tmp_path):
        from qtpy.QtGui import QImage

        from tagorganizer.models import Item
        from tagorganizer.widgets.helper import build_video_preview

        item = Item(id=1, uri=str(tiny_video), uri_md5="a" * 32)
        assert build_video_preview(item, 150, tmp_path) is True

        sheet = QImage(str(preview_file("a" * 32, 150, tmp_path)))
        assert not sheet.isNull()
        assert sheet.width() == SPRITE_COLUMNS * 150

    def test_returns_false_for_a_missing_file(self, tmp_path):
        from tagorganizer.models import Item
        from tagorganizer.widgets.helper import build_video_preview

        item = Item(id=1, uri=str(tmp_path / "nope.mp4"), uri_md5="b" * 32)
        assert build_video_preview(item, 150, tmp_path) is False

    def test_does_not_rebuild_an_existing_sheet(self, tiny_video, tmp_path):
        """The task re-runs often; rebuilding every sheet would be wasted work."""
        from tagorganizer.models import Item
        from tagorganizer.widgets.helper import build_video_preview

        item = Item(id=1, uri=str(tiny_video), uri_md5="c" * 32)
        assert build_video_preview(item, 150, tmp_path) is True
        stamp = preview_file("c" * 32, 150, tmp_path).stat().st_mtime_ns

        assert build_video_preview(item, 150, tmp_path) is False
        assert preview_file("c" * 32, 150, tmp_path).stat().st_mtime_ns == stamp
