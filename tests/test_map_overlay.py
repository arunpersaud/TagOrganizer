"""Mosaic composition for the map's hover preview.

Needs a QApplication because QImage/QPainter do; guarded the same way as
tests/test_single_view_layout.py.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    widgets = pytest.importorskip("qtpy.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


def _solid(qapp, size, colour):
    from qtpy.QtGui import QImage

    image = QImage(size, size, QImage.Format_RGB32)
    image.fill(colour)
    return image


class TestComposeMosaic:
    def test_nine_images_make_a_three_by_three(self, qapp):
        from tagorganizer.widgets.map_overlay import compose_mosaic

        mosaic = compose_mosaic([_solid(qapp, 150, 0x336699)] * 9, cell=150)
        assert (mosaic.width(), mosaic.height()) == (450, 450)

    def test_a_single_image_is_one_cell(self, qapp):
        from tagorganizer.widgets.map_overlay import compose_mosaic

        mosaic = compose_mosaic([_solid(qapp, 150, 0x336699)], cell=150)
        assert (mosaic.width(), mosaic.height()) == (150, 150)

    def test_four_images_make_a_two_by_two(self, qapp):
        """The grid is only as large as it needs to be."""
        from tagorganizer.widgets.map_overlay import compose_mosaic

        mosaic = compose_mosaic([_solid(qapp, 150, 0x336699)] * 4, cell=150)
        assert (mosaic.width(), mosaic.height()) == (300, 300)

    def test_more_than_nine_are_truncated(self, qapp):
        """The preview shows the first nine; it is a glance, not a gallery."""
        from tagorganizer.widgets.map_overlay import compose_mosaic

        mosaic = compose_mosaic([_solid(qapp, 150, 0x336699)] * 25, cell=150)
        assert (mosaic.width(), mosaic.height()) == (450, 450)

    def test_no_images_gives_a_null_image(self, qapp):
        from tagorganizer.widgets.map_overlay import compose_mosaic

        assert compose_mosaic([], cell=150).isNull()
