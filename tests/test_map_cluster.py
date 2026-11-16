"""Tests for map clustering and geometry.

All Qt-free and database-free: clustering is the piece that lets the map work at
any library size, so it is worth testing directly rather than through the widget.
"""

from typing import ClassVar

import pytest

from tagorganizer.map_cluster import (
    FITTED_ZOOM,
    ClusterState,
    cell_size_for_zoom,
    cluster_points,
    ids_in_viewport,
    point_in_polygon,
    shift_longitude_into,
    unwrap_longitudes,
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

    def test_zero_cell_size_raises_error(self):
        """Guard against ZeroDivisionError when cell_size comes from untrusted zoom."""
        with pytest.raises(ValueError, match="cell_size must be positive"):
            cluster_points([(1, 10.0, 20.0)], cell_size=0.0)

    def test_negative_cell_size_raises_error(self):
        """Guard against ZeroDivisionError when cell_size comes from untrusted zoom."""
        with pytest.raises(ValueError, match="cell_size must be positive"):
            cluster_points([(1, 10.0, 20.0)], cell_size=-1.0)

    def test_southern_hemisphere_coordinates_cluster(self):
        """Floor division handles negative coordinates correctly."""
        # Sydney at -33.87, 151.21 and -33.86, 151.22 should cluster together
        points = [(1, -33.87, 151.21), (2, -33.86, 151.22)]
        clusters = cluster_points(points, cell_size=1.0)
        assert len(clusters) == 1
        assert sorted(clusters[0].ids) == [1, 2]

    def test_western_hemisphere_stays_separate(self):
        """Points in western hemisphere at different locations stay separate."""
        # Rio at -22.91, -43.17 and Cape Town at -33.92, 18.42 should be separate
        points = [(1, -22.91, -43.17), (2, -33.92, 18.42)]
        clusters = cluster_points(points, cell_size=1.0)
        assert len(clusters) == 2

    def test_equator_crossing_does_not_merge(self):
        """Points either side of the equator do not merge."""
        points = [(1, -0.1, 0.0), (2, 0.1, 0.0)]
        clusters = cluster_points(points, cell_size=1.0)
        assert len(clusters) == 2

    def test_inverted_bounds_select_nothing(self):
        """Inverted bounds (min > max) should select nothing."""
        points = [(1, 10.0, 20.0), (2, 15.0, 25.0)]
        clusters = cluster_points(points, cell_size=1.0, bounds=(20.0, 40.0, 0.0, 0.0))
        assert clusters == []


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


class TestAntimeridian:
    """Leaflet reports longitudes past +/-180 once the view has crossed the seam.

    A photo at -175 is on screen at 185 in such a view, so a test on the raw
    longitude alone hides every photo on the far side of the date line.
    """

    def test_a_point_on_the_far_side_of_the_seam_is_shifted_into_view(self):
        assert shift_longitude_into(-175.0, 170.0, 190.0) == pytest.approx(185.0)

    def test_a_point_outside_the_span_stays_outside(self):
        assert shift_longitude_into(10.0, 170.0, 190.0) is None

    def test_a_point_already_inside_is_returned_unchanged(self):
        assert shift_longitude_into(175.0, 170.0, 190.0) == pytest.approx(175.0)

    def test_a_span_of_a_full_world_always_finds_a_representative(self):
        for lon in (-179.0, 0.0, 179.0):
            shifted = shift_longitude_into(lon, -200.0, 170.0)
            assert shifted is not None
            assert -200.0 <= shifted <= 170.0
            assert (shifted - lon) % 360 == pytest.approx(0.0)

    def test_inverted_span_contains_nothing(self):
        assert shift_longitude_into(0.0, 10.0, -10.0) is None

    def test_unwrapping_keeps_a_ring_continuous_across_the_seam(self):
        assert unwrap_longitudes([170.0, -175.0, -170.0]) == pytest.approx(
            [170.0, 185.0, 190.0]
        )

    def test_clusters_on_the_far_side_are_kept_in_a_wrapped_view(self):
        """A cluster centroid is placed where the viewport shows it."""
        points = [(1, 0.0, -175.0), (2, 0.0, -174.0)]
        clusters = cluster_points(points, cell_size=100.0, bounds=(-60, 170, 60, 190))
        assert len(clusters) == 1
        assert clusters[0].lon == pytest.approx(185.5)

    def test_viewport_selection_includes_the_wrapped_side(self):
        locations = [(1, 0.0, -175.0), (2, 0.0, 10.0), (3, 80.0, -175.0)]
        assert ids_in_viewport(locations, (-10, 170, 10, 190)) == [1]


class TestClusterState:
    """The map's clustering inputs, with the viewport they are seen through."""

    def test_no_locations_gives_no_clusters(self):
        """The empty case used to send the string '[]' to the page."""
        assert ClusterState().cluster() == []

    def test_before_the_page_reports_a_viewport_everything_is_clustered(self):
        state = ClusterState()
        state.set_locations([(1, 48.85, 2.35), (2, 40.71, -74.0)])
        assert sorted(i for c in state.cluster() for i in c.ids) == [1, 2]

    def test_a_new_location_set_is_not_clipped_by_the_old_viewport(self):
        """Filtering re-renders the map, so the old viewport no longer applies.

        Paris was on screen when the filter changed. The new set is New York,
        which lies outside that viewport: it must still be clustered.
        """
        state = ClusterState()
        state.set_locations([(1, 48.85, 2.35)])
        state.set_viewport(6, 48.0, 1.0, 49.5, 3.5)

        state.set_locations([(2, 40.71, -74.0)])

        assert [i for c in state.cluster() for i in c.ids] == [2]

    def test_a_reported_viewport_restricts_clustering(self):
        state = ClusterState()
        state.set_locations([(1, 48.85, 2.35), (2, 40.71, -74.0)])
        state.set_viewport(6, 48.0, 1.0, 49.5, 3.5)
        assert [i for c in state.cluster() for i in c.ids] == [1]

    def test_an_unreported_zoom_falls_back_to_the_fitted_zoom(self):
        state = ClusterState()
        state.set_locations([(1, 0.0, 0.0)])
        assert state.zoom == 0
        assert state.cluster()[0].ids == [1]
        assert FITTED_ZOOM == 4
