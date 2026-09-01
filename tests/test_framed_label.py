"""Rendering tests for the grid tile.

These need a real widget: the bug they guard is that a QLabel silently clips a
pixmap larger than itself, which no structural assertion can see. Guarded the
same way as tests/test_single_view_layout.py and tests/test_map_overlay.py.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    widgets = pytest.importorskip("qtpy.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_tall_thumbnail_is_scaled_to_fit_the_tile(qapp, tmp_path):
    """A portrait photo must show whole, not cropped to its middle band.

    load_qimage scales to a target *width*, so a portrait photo comes back
    taller than the square tile that displays it. Setting that pixmap directly
    makes QLabel clip it, and the user sees a slice of the photo rather than the
    photo. The displayed pixmap must therefore fit inside the tile.
    """
    from qtpy.QtGui import QImage
    from qtpy.QtWidgets import QLabel

    from tagorganizer.models import Item
    from tagorganizer.widgets.framed_label import FramedLabel
    from tagorganizer.widgets.helper import get_thumbnail_loader

    item = Item(id=1, uri=str(tmp_path / "portrait.jpg"), uri_md5="a" * 32)
    label = FramedLabel(item, tmp_path)
    label.resize(150, 150)

    # What load_qimage produces for a portrait photo at a 150 px target width.
    tall = QImage(150, 400, QImage.Format_RGB32)
    tall.fill(0x3060A0)

    key = get_thumbnail_loader().key_for(item, label.pixmap_width)
    label._on_thumbnail_ready(key, tall)

    # FramedLabel shadows QLabel.pixmap with an attribute, so reach the
    # displayed pixmap through the class.
    shown = QLabel.pixmap(label)
    assert shown is not None and not shown.isNull()
    assert shown.width() <= label.width()
    assert shown.height() <= label.height(), (
        f"tile is {label.width()}x{label.height()} but the displayed pixmap is "
        f"{shown.width()}x{shown.height()}; QLabel will clip it and the user "
        f"sees only part of the photo"
    )


def test_scaling_preserves_aspect_ratio(qapp, tmp_path):
    """Fitting the tile must not squash the photo."""
    from qtpy.QtGui import QImage
    from qtpy.QtWidgets import QLabel

    from tagorganizer.models import Item
    from tagorganizer.widgets.framed_label import FramedLabel
    from tagorganizer.widgets.helper import get_thumbnail_loader

    item = Item(id=2, uri=str(tmp_path / "portrait.jpg"), uri_md5="b" * 32)
    label = FramedLabel(item, tmp_path)
    label.resize(150, 150)

    tall = QImage(100, 400, QImage.Format_RGB32)  # 1:4
    tall.fill(0x3060A0)

    key = get_thumbnail_loader().key_for(item, label.pixmap_width)
    label._on_thumbnail_ready(key, tall)

    shown = QLabel.pixmap(label)
    assert shown.width() / shown.height() == pytest.approx(100 / 400, rel=0.05)


def _video_item(tmp_path, md5="e" * 32):
    from tagorganizer.models import Item

    return Item(id=99, uri=str(tmp_path / "clip.mp4"), uri_md5=md5)


def _write_sheet(tmp_path, md5, frame_w=150, frame_h=84):
    """A sprite sheet shaped like a real one, without needing a video."""
    from qtpy.QtGui import QImage

    from tagorganizer.widgets.helper import (
        SPRITE_COLUMNS,
        SPRITE_ROWS,
        preview_file,
    )

    sheet = QImage(SPRITE_COLUMNS * frame_w, SPRITE_ROWS * frame_h, QImage.Format_RGB32)
    sheet.fill(0x226644)
    path = preview_file(md5, 150, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(path), "PNG")
    return path


class TestPlaceholders:
    def test_a_tile_awaiting_its_thumbnail_says_so(self, qapp, tmp_path):
        """Pending and failed must not look identical.

        Today both render as the bare file name, so a tile whose photo is fine
        and a tile whose photo has vanished are indistinguishable.
        """
        from tagorganizer.models import Item
        from tagorganizer.widgets.framed_label import FramedLabel

        item = Item(id=1, uri=str(tmp_path / "waiting.jpg"), uri_md5="f" * 32)
        label = FramedLabel(item, tmp_path)

        assert "generating" in label.text().lower()

    def test_a_failed_decode_shows_the_file_name(self, qapp, tmp_path):
        """A missing file is an error the user needs to see."""
        from tagorganizer.models import Item
        from tagorganizer.widgets.framed_label import FramedLabel
        from tagorganizer.widgets.helper import get_thumbnail_loader

        item = Item(id=2, uri=str(tmp_path / "gone.jpg"), uri_md5="0" * 32)
        label = FramedLabel(item, tmp_path)
        label._on_thumbnail_ready(get_thumbnail_loader().key_for(item, 150), None)

        assert "gone.jpg" in label.text()
        assert "generating" not in label.text().lower()


class TestHoverPreview:
    def test_hovering_a_video_with_a_sheet_animates(self, qapp, tmp_path):
        from tagorganizer.widgets.framed_label import FramedLabel

        md5 = "e" * 32
        _write_sheet(tmp_path, md5)
        label = FramedLabel(_video_item(tmp_path, md5), tmp_path)
        label.resize(150, 150)

        label.enterEvent(None)
        assert label.is_animating() is True

        label.leaveEvent(None)
        assert label.is_animating() is False

    def test_hovering_a_photo_does_nothing(self, qapp, tmp_path):
        from tagorganizer.models import Item
        from tagorganizer.widgets.framed_label import FramedLabel

        item = Item(id=3, uri=str(tmp_path / "photo.jpg"), uri_md5="1" * 32)
        label = FramedLabel(item, tmp_path)
        label.enterEvent(None)

        assert label.is_animating() is False

    def test_a_video_without_a_sheet_does_not_animate_or_raise(self, qapp, tmp_path):
        """Previews are built by a background task; until it runs there is none."""
        from tagorganizer.widgets.framed_label import FramedLabel

        label = FramedLabel(_video_item(tmp_path, "2" * 32), tmp_path)
        label.enterEvent(None)

        assert label.is_animating() is False

    def test_frames_wrap_round_rather_than_running_off_the_sheet(self, qapp, tmp_path):
        from tagorganizer.widgets.framed_label import FramedLabel
        from tagorganizer.widgets.helper import SPRITE_FRAMES

        md5 = "e" * 32
        _write_sheet(tmp_path, md5)
        label = FramedLabel(_video_item(tmp_path, md5), tmp_path)
        label.resize(150, 150)
        label.enterEvent(None)

        for _ in range(SPRITE_FRAMES + 3):
            label._advance_frame()

        assert 0 <= label._frame < SPRITE_FRAMES
