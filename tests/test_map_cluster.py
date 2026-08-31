"""Tests for map clustering and geometry.

All Qt-free and database-free: clustering is the piece that lets the map work at
any library size, so it is worth testing directly rather than through the widget.
"""

from typing import ClassVar

import pytest

from tagorganizer.map_cluster import (
    cell_size_for_zoom,
    cluster_points,
    point_in_polygon,
)


class TestCellSizeForZoom:
    def test_halves_with_each_zoom_level(self):
        """Leaflet doubles the world's pixel width per zoom level."""
        assert cell_size_for_zoom(5) == pytest.approx(cell_size_for_zoom(4) / 2)

    def test_zoom_zero_spans_a_large_fraction_of_the_world(self):
        assert cell_size_for_zoom(0) == pytest.approx(360 * 60 / 256)

    def test_larger_target_gives_larger_cells(self):
        assert cell_size_for_zoom(5, target_px=120) > cell_size_for_zoom(
            5, target_px=60
        )


class TestClusterPoints:
    def test_nearby_points_share_a_cluster(self):
        points = [(1, 10.00, 20.00), (2, 10.001, 20.001)]
        clusters = cluster_points(points, cell_size=1.0)
        assert len(clusters) == 1
        assert sorted(clusters[0].ids) == [1, 2]

    def test_distant_points_are_separate(self):
        points = [(1, 10.0, 20.0), (2, 50.0, 80.0)]
        assert len(cluster_points(points, cell_size=1.0)) == 2

    def test_centroid_is_the_mean_of_members(self):
        points = [(1, 10.0, 20.0), (2, 12.0, 24.0)]
        cluster = cluster_points(points, cell_size=100.0)[0]
        assert cluster.lat == pytest.approx(11.0)
        assert cluster.lon == pytest.approx(22.0)

    def test_bounds_exclude_points_outside_the_viewport(self):
        """Restricting to the viewport is what keeps the emitted count bounded."""
        points = [(1, 10.0, 20.0), (2, 80.0, 20.0)]
        clusters = cluster_points(points, cell_size=1.0, bounds=(0.0, 0.0, 20.0, 40.0))
        assert [c.ids for c in clusters] == [[1]]

    def test_empty_input_gives_no_clusters(self):
        assert cluster_points([], cell_size=1.0) == []

    def test_order_is_stable(self):
        """The index of a cluster is sent to JS and looked up again on hover."""
        points = [(i, float(i), float(i)) for i in range(20)]
        assert [c.ids for c in cluster_points(points, 1.0)] == [
            c.ids for c in cluster_points(points, 1.0)
        ]


class TestPointInPolygon:
    SQUARE: ClassVar = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)]

    def test_inside(self):
        assert point_in_polygon(5.0, 5.0, self.SQUARE) is True

    def test_outside(self):
        assert point_in_polygon(15.0, 5.0, self.SQUARE) is False

    def test_concave_polygon_excludes_the_notch(self):
        """A lasso that selected its bounding box would not be a lasso."""
        # A "C" shape: the notch on the right is outside the polygon but well
        # inside its bounding box.
        c_shape = [
            (0.0, 0.0),
            (0.0, 10.0),
            (10.0, 10.0),
            (10.0, 8.0),
            (2.0, 8.0),
            (2.0, 2.0),
            (10.0, 2.0),
            (10.0, 0.0),
        ]
        assert point_in_polygon(5.0, 5.0, c_shape) is False  # in the notch
        assert point_in_polygon(1.0, 5.0, c_shape) is True  # in the spine

    def test_degenerate_polygon_is_never_inside(self):
        assert point_in_polygon(1.0, 1.0, [(0.0, 0.0), (1.0, 1.0)]) is False
