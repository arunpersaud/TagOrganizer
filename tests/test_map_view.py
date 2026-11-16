"""Tests for the map view.

The map's pure helpers are tested directly: where to centre, how far to zoom,
how the Leaflet variable name is recovered from a rendered document, and how a
lasso is turned into a selection.

The rest runs against a real MapView inside a real window, with the page
replaced by a recorder. Nothing here shows the map: showing it offscreen
crashes inside QtWebEngine, so only what the Python side hands the page is
checked.
"""

from types import SimpleNamespace

import pytest

from tagorganizer.map_cluster import ClusterState
from tagorganizer.widgets.map import (
    MapBridge,
    MapView,
    map_center_and_zoom,
    parse_map_name,
)

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


class TestMapBridge:
    """The page calls Python through QWebChannel, which offers only the slots the
    Qt meta-object declares. A method without @Slot is silently uncallable from
    the page, so these ask the meta-object directly.
    """

    @pytest.mark.parametrize(
        "signature",
        [
            "hover(int,int)",
            "hover_end()",
            "viewport_changed(int,double,double,double,double)",
            "shape_drawn(QString)",
            "channel_ready()",
        ],
    )
    def test_the_page_can_call_the_slot(self, signature):
        assert MapBridge.staticMetaObject.indexOfSlot(signature) >= 0, signature

    def test_the_handshake_call_reaches_the_view(self, window_for):
        """Invoke channel_ready by name, as the page's handshake does."""
        from qtpy.QtCore import Qt
        from qtpy.QtCore import QMetaObject

        view = window_for().map.view
        view._channel_ready = False

        QMetaObject.invokeMethod(
            view._bridge, "channel_ready", Qt.ConnectionType.DirectConnection
        )

        assert view._channel_ready is True


def _captured_html(window_for, monkeypatch):
    """Render the real map; return the view and the document handed to setHtml."""
    window = window_for()
    view = window.map.view
    documents = []
    monkeypatch.setattr(view, "setHtml", lambda html, *args: documents.append(html))
    view.render_map()
    return view, documents[-1]


class TestChannelReadinessFlushing:
    def test_nothing_is_sent_before_the_handshake_and_the_queue_flushes_after(
        self, window_for, monkeypatch
    ):
        view = window_for().map.view
        page = _FakePage()
        monkeypatch.setattr(view, "page", lambda: page)
        view._channel_ready = False

        view.update_clusters()
        assert page.scripts == [], "an update reached the page before the handshake"

        view._on_channel_ready()

        assert view._channel_ready is True
        assert len(page.scripts) == 1
        assert page.scripts[0].startswith("updateClusters(")


class TestMapInjectionPoint:
    def test_the_interaction_script_runs_after_folium_creates_the_map(
        self, window_for, monkeypatch
    ):
        """folium writes the map creation, and the Draw control, in a trailing
        script after </body>. The interaction script refers to that map variable,
        so injecting at </body> would run it first and throw a ReferenceError,
        leaving the map blank. Injection belongs at </html>.
        """
        view, html = _captured_html(window_for, monkeypatch)

        creation = html.index(f"var {view.map_name} = L.map(")
        injected = html.index("clustersLayer")

        assert injected > creation, "the script ran before the map existed"
        assert html.rstrip().endswith("</html>")


class TestMapViewWebChannelIntegration:
    def test_the_rendered_document_carries_the_channel_library(
        self, window_for, monkeypatch
    ):
        """qwebchannel.js is inlined, because a setHtml page has no base URL to
        load it from."""
        view, html = _captured_html(window_for, monkeypatch)

        library = view._load_qwebchannel()

        assert library, "qwebchannel.js did not load from the Qt resources"
        assert library in html

    def test_viewport_changes_update_the_markers_without_reloading(
        self, window_for, monkeypatch
    ):
        """setHtml reloads the document and resets the user's viewport, so a
        pan or zoom must only re-cluster and push markers in place.
        """
        view = window_for().map.view
        loads = []
        monkeypatch.setattr(view, "setHtml", lambda html, *args: loads.append(html))
        page = _FakePage()
        monkeypatch.setattr(view, "page", lambda: page)
        view._channel_ready = True

        view._on_viewport_changed(6, 48.0, 1.0, 49.5, 3.5)
        view._on_debounce_timeout()

        assert loads == [], "a viewport change reloaded the document"
        assert page.scripts, "the markers were not updated in place"


class TestMainUpdateItemsWiring:
    def test_the_library_locations_reach_the_map_on_update(self, window_for):
        """Without this the map has no markers, no hover and nothing to select."""
        from sqlmodel import select

        from tagorganizer import db
        from tagorganizer.models import Item

        window = window_for()
        path = str(window.config.photos / "geo.jpg")
        db.add_images([path])
        with db.new_session() as session:
            item = session.exec(select(Item).where(Item.uri == path)).one()
            item.latitude, item.longitude = 48.85, 2.35
            session.add(item)
            session.commit()
            item_id = item.id

        # A plain update keeps the filters it drew last time, and the map is
        # only given the locations when they change. A data change always does.
        window.refresh_after_data_change()

        assert (item_id, 48.85, 2.35) in window.map.view._locations


# A U-shaped lasso, as (longitude, latitude). Its notch is lon 4 to 6 above
# lat 4: inside the bounding box, outside the shape.
U_SHAPE = [[0, 0], [10, 0], [10, 10], [6, 10], [6, 4], [4, 4], [4, 10], [0, 10], [0, 0]]


class TestShapeSelection:
    def test_a_lasso_leaves_out_the_notch_of_a_concave_shape(self, window_for):
        """A bounding-box test would select the photo in the notch as well."""
        window = window_for()
        # (id, lat, lon): id 1 is in the notch, id 2 in the left arm.
        window.map.set_locations([(1, 8.0, 5.0), (2, 8.0, 2.0)])

        window.map.view._bridge.shape_drawn(_geojson_polygon(U_SHAPE))

        assert set(window.selection.ids()) == {2}

    def test_select_visible_adds_the_viewport_and_creates_no_filter(self, window_for):
        window = window_for()
        window.map.set_locations([(1, 48.0, 2.0), (2, 10.0, 10.0)])
        bounds = {
            "_southWest": {"lat": 45.0, "lng": 0.0},
            "_northEast": {"lat": 50.0, "lng": 5.0},
        }

        window.map.view._select_visible_callback(bounds)

        assert set(window.selection.ids()) == {1}
        assert window.tag_bar.get_all_names() == []
        assert window.tag_bar.get_filters().min_latitude is None


class _FakeSelection:
    def __init__(self):
        self.ids = set()

    def add_many(self, ids):
        self.ids.update(ids)

    def __len__(self):
        return len(self.ids)


class _FakeMessages:
    def __init__(self):
        self.lines = []

    def add(self, text):
        self.lines.append(text)


class _FakeMain:
    """The parts of MainWindow the map touches, recording what it was told."""

    def __init__(self):
        self.selection = _FakeSelection()
        self.messages = _FakeMessages()
        self.item_updates = 0
        self.numbers = []

    def update_items(self):
        self.item_updates += 1

    def update_numbers(self, view=None, selected=None, total=None):
        self.numbers.append(selected)


class _FakePage:
    def __init__(self):
        self.scripts = []

    def runJavaScript(self, script, *callback):
        self.scripts.append(script)


class _FakeOverlay:
    def __init__(self):
        self.hidden = 0

    def hide_mosaic(self):
        self.hidden += 1


def _geojson_polygon(ring):
    import json

    return json.dumps({"type": "Polygon", "coordinates": [ring]})


class TestClusterUpdates:
    """update_clusters and the hover path, driven through the real methods."""

    def _view(self, locations, channel_ready=True):
        view = SimpleNamespace(
            _state=ClusterState(),
            _clusters=[],
            _cluster_generation=0,
            _channel_ready=channel_ready,
            _pending_update=False,
            _overlay=_FakeOverlay(),
            _show_calls=[],
            _debounce_timer=SimpleNamespace(stop=lambda: None, start=lambda: None),
        )
        view._state.set_locations(locations)
        view.page = lambda: view._page
        view._page = _FakePage()
        view._show_mosaic_for_photos = lambda ids, index: view._show_calls.append(
            (ids, index)
        )
        return view

    def test_an_empty_location_set_pushes_an_empty_array_not_a_string(self):
        """updateClusters('[]') handed the page a string, so forEach threw."""
        view = self._view([])
        MapView.update_clusters(view)
        assert view._page.scripts == ["updateClusters([], 1)"]

    def test_each_push_carries_a_new_generation(self):
        view = self._view([(1, 48.85, 2.35)])
        MapView.update_clusters(view)
        MapView.update_clusters(view)
        assert view._page.scripts[0].endswith(", 1)")
        assert view._page.scripts[1].endswith(", 2)")

    def test_replacing_the_markers_hides_a_mosaic_left_over_from_them(self):
        view = self._view([(1, 48.85, 2.35)])
        MapView.update_clusters(view)
        assert view._overlay.hidden == 1

    def test_a_hover_from_replaced_markers_is_ignored(self):
        """The index named a cluster in the previous list, not the current one."""
        from tagorganizer.map_cluster import Cluster

        view = self._view([(1, 48.85, 2.35)])
        view._clusters = [Cluster(0.0, 0.0, [1])]
        view._cluster_generation = 5

        MapView._on_hover(view, 0, 4)

        assert view._show_calls == []

    def test_a_hover_from_the_current_markers_is_shown(self):
        from tagorganizer.map_cluster import Cluster

        view = self._view([(1, 48.85, 2.35)])
        view._clusters = [Cluster(0.0, 0.0, [1])]
        view._cluster_generation = 5

        MapView._on_hover(view, 0, 5)

        assert view._show_calls == [([1], 0)]

    def test_a_viewport_report_is_used_when_clustering(self):
        view = self._view([(1, 48.85, 2.35), (2, 40.71, -74.0)])
        MapView._on_viewport_changed(view, 6, 48.0, 1.0, 49.5, 3.5)
        assert view._state.zoom == 6
        assert view._state.bounds == (48.0, 1.0, 49.5, 3.5)


class TestSelectionCounts:
    """Selecting by map must refresh the count, and the real callbacks must run."""

    def test_select_visible_reports_the_new_selection_size(self):
        main = _FakeMain()
        view = SimpleNamespace(
            main=main,
            _locations=[(1, 48.85, 2.35), (2, 40.71, -74.0)],
        )

        MapView._select_visible_callback(
            view,
            {
                "_southWest": {"lat": 45.0, "lng": 0.0},
                "_northEast": {"lat": 50.0, "lng": 5.0},
            },
        )

        assert main.selection.ids == {1}
        assert main.numbers == [1]

    def test_select_visible_finds_photos_across_the_antimeridian(self):
        main = _FakeMain()
        view = SimpleNamespace(main=main, _locations=[(1, 0.0, -175.0), (2, 0.0, 10.0)])

        MapView._select_visible_callback(
            view,
            {
                "_southWest": {"lat": -10.0, "lng": 170.0},
                "_northEast": {"lat": 10.0, "lng": 190.0},
            },
        )

        assert main.selection.ids == {1}

    def test_a_lasso_across_the_antimeridian_selects_the_far_side(self):
        """A lasso whose ring crosses the seam: 170 to -170 in raw longitudes.

        Read as written, the ring is a sliver spanning the whole planet. Unwrapped
        it is a twenty-degree shape from 170 to 190, and the far-side photo at
        -175 (185 on that shape) is inside while the one at 10 is not.
        """
        main = _FakeMain()
        bridge = SimpleNamespace(
            map_view=SimpleNamespace(
                main=main, _locations=[(1, 0.0, -175.0), (2, 0.0, 10.0)]
            )
        )
        ring = [
            [170.0, -10.0],
            [-170.0, -10.0],
            [-170.0, 10.0],
            [170.0, 10.0],
            [170.0, -10.0],
        ]

        MapBridge.shape_drawn(bridge, _geojson_polygon(ring))

        assert main.selection.ids == {1}
        assert main.numbers == [1]

    def test_a_lasso_that_selects_nothing_leaves_the_count_alone(self):
        main = _FakeMain()
        bridge = SimpleNamespace(
            map_view=SimpleNamespace(main=main, _locations=[(1, 0.0, 10.0)])
        )
        ring = [[-5.0, -5.0], [5.0, -5.0], [5.0, 5.0], [-5.0, 5.0], [-5.0, -5.0]]

        MapBridge.shape_drawn(bridge, _geojson_polygon(ring))

        assert main.numbers == []
        assert main.messages.lines == ["No photos in the selected area"]


class TestMapViewWiring:
    def test_the_unused_set_location_is_gone(self):
        assert not hasattr(MapView, "set_location")

    def test_hiding_the_map_hides_the_mosaic(self, window_for, monkeypatch):
        """A mosaic over another tab would never receive its mouseout."""
        from qtpy.QtGui import QHideEvent

        view = window_for().map.view
        hidden = []
        monkeypatch.setattr(view._overlay, "hide_mosaic", lambda: hidden.append(True))

        view.hideEvent(QHideEvent())

        assert hidden == [True]


class TestInvalidateSize:
    """Only the generated script can be checked here; whether the guard keeps
    the page quiet was confirmed against a live QWebEngineView, not in the suite.
    """

    def test_the_resize_call_is_skipped_while_the_map_is_not_defined(self):
        view = SimpleNamespace(map_name="map_abc", _page=_FakePage())
        view.page = lambda: view._page

        MapView.invalidate_size(view)

        assert view._page.scripts == ["window.map_abc && map_abc.invalidateSize()"]
