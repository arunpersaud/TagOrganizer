"""Tests for the map view's pure helpers.

The rendering itself needs QtWebEngine and a real window, so only the decisions
are tested here: where to centre, how far to zoom, and how the Leaflet variable
name is recovered from a rendered document.
"""

from tagorganizer.widgets.map import map_center_and_zoom, parse_map_name

DEFAULT_LOCATION = [37.7749, -122.4194]


class TestMapCenterAndZoom:
    def test_no_coordinates_uses_the_default_world_view(self):
        location, zoom = map_center_and_zoom([])
        assert location == DEFAULT_LOCATION
        assert zoom == 2

    def test_single_coordinate_centres_on_it(self):
        location, zoom = map_center_and_zoom([(48.85, 2.35)])
        assert location == [48.85, 2.35]
        assert zoom == 4

    def test_several_coordinates_centre_on_the_mean(self):
        location, zoom = map_center_and_zoom([(0.0, 0.0), (10.0, 20.0)])
        assert location == [5.0, 10.0]
        assert zoom == 4


class TestParseMapName:
    def test_finds_the_leaflet_variable(self):
        html = "\n".join(
            [
                "<html><body>",
                "    var map_abc123 = L.map(",
                '        "map_abc123",',
                "    );",
                "</body></html>",
            ]
        )
        assert parse_map_name(html) == "map_abc123"

    def test_returns_empty_string_when_absent(self):
        assert parse_map_name("<html><body>no map here</body></html>") == ""
