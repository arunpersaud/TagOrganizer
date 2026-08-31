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
