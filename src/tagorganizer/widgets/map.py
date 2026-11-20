import io
import json
import logging
import folium
from folium.plugins import Draw
from qtpy.QtWebEngineWidgets import QWebEngineView
from qtpy.QtWebChannel import QWebChannel
from qtpy.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout
from qtpy.QtCore import QObject, QTimer, QFile, Slot
from qtpy.QtGui import QPixmap, QCursor
from tagorganizer.map_cluster import (
    FITTED_ZOOM,
    ClusterState,
    ids_in_viewport,
    point_in_polygon,
    shift_longitude_into,
    unwrap_longitudes,
)
from tagorganizer.widgets.map_overlay import MosaicOverlay, compose_mosaic

logger = logging.getLogger(__name__)


DEFAULT_LOCATION = [37.7749, -122.4194]
DEFAULT_ZOOM = 2


class MapBridge(QObject):
    """The page's handle on Python.

    Registered on a QWebChannel under a name the injected script knows. Slots
    must be declared with @Slot or they are not visible to JavaScript.
    """

    def __init__(self, map_view):
        super().__init__()
        self.map_view = map_view

    @Slot(int, int)
    def hover(self, cluster_index, generation):
        """Show the mosaic overlay for a hovered cluster.

        The generation names the marker set the hover came from; see
        MapView.update_clusters for why it has to travel with the index.
        """
        self.map_view._on_hover(cluster_index, generation)

    @Slot()
    def hover_end(self):
        """Hide the mosaic overlay."""
        self.map_view._on_hover_end()

    @Slot(int, float, float, float, float)
    def viewport_changed(self, zoom, min_lat, min_lon, max_lat, max_lon):
        """Handle map viewport changes: debounce and re-cluster."""
        self.map_view._on_viewport_changed(zoom, min_lat, min_lon, max_lat, max_lon)

    @Slot(float, float)
    def map_double_clicked(self, latitude, longitude):
        """A double-click on the map, which places photos when armed."""
        self.map_view._on_double_click(latitude, longitude)

    @Slot(str)
    def shape_drawn(self, geojson):
        """Handle shape selection: add photos in the drawn shape to the selection.

        Parses the GeoJSON geometry from the Draw plugin. For rectangles, filters
        the cached locations by bounding box. For polygons, filters by bounding
        box first and then applies point_in_polygon to exclude concave notches.
        """
        try:
            geometry = json.loads(geojson)
        except (json.JSONDecodeError, ValueError):
            self.map_view.main.messages.add(
                "[ERROR] Could not parse drawn shape geometry"
            )
            return

        # Extract the coordinates from the geometry
        if "coordinates" not in geometry:
            self.map_view.main.messages.add("[ERROR] Drawn shape has no coordinates")
            return

        coords = geometry["coordinates"]

        # A rectangle in Leaflet Draw comes as a closed polygon with 5 points
        # (4 corners + closing point). A lasso is an open polygon.
        # Both are sent as type: "Polygon" with coordinates in [lon, lat] format.

        if not coords or len(coords) == 0:
            return

        # coords is nested: coords[0] is the outer ring for a Polygon
        ring = coords[0] if coords else []
        if not ring:
            return

        # A shape drawn across the antimeridian arrives with longitudes past
        # 180, so the ring is made continuous before it is tested. Each photo is
        # then matched against the copy of the world the shape lies on.
        ring_lons = unwrap_longitudes([c[0] for c in ring])
        lats = [c[1] for c in ring]
        min_lon, max_lon = min(ring_lons), max(ring_lons)
        min_lat, max_lat = min(lats), max(lats)
        polygon_ring = [(lat, lon) for lon, lat in zip(ring_lons, lats, strict=True)]

        # Bounding box first, then point_in_polygon on the survivors to exclude
        # concave notches. Both go through the same wrapped longitude.
        selected_ids = []
        for id_, lat, lon in self.map_view._locations:
            if not min_lat <= lat <= max_lat:
                continue
            shifted = shift_longitude_into(lon, min_lon, max_lon)
            if shifted is None:
                continue
            if point_in_polygon(lat, shifted, polygon_ring):
                selected_ids.append(id_)

        if not selected_ids:
            self.map_view.main.messages.add("No photos in the selected area")
            return

        # Add to the selection
        self.map_view.main.selection.add_many(selected_ids)
        self.map_view.main.update_items()
        self.map_view.main.update_numbers(selected=len(self.map_view.main.selection))
        self.map_view.main.messages.add(f"Selected {len(selected_ids)} photos")

    @Slot()
    def channel_ready(self):
        """Called when the QWebChannel handshake completes on the page.

        The JavaScript side signals this after registering the bridge object,
        so we can start sending updates.
        """
        self.map_view._on_channel_ready()


def map_center_and_zoom(coords):
    """Where to centre the map, and how far in to zoom, for these points.

    With nothing to show we stay on the default world view, which is also what
    the user should see before any photo has a location.
    """
    if len(coords) == 0:
        return list(DEFAULT_LOCATION), DEFAULT_ZOOM
    latitudes = [c[0] for c in coords]
    longitudes = [c[1] for c in coords]
    return [
        sum(latitudes) / len(latitudes),
        sum(longitudes) / len(longitudes),
    ], FITTED_ZOOM


def parse_map_name(html: str) -> str:
    """Recover the Leaflet map's JavaScript variable name from folium's output.

    Everything we ask the page to do afterwards - reading the bounds, telling it
    to re-measure - has to name that variable.
    """
    for line in html.split("\n"):
        if "L.map" in line:
            parts = line.strip().split()
            if len(parts) > 1:
                return parts[1]
    return ""


class MapView(QWebEngineView):
    def __init__(self, main):
        super().__init__()
        self.main = main

        self.map = None
        self.map_name = ""
        self.coords = []
        # Nothing is rendered until the tab is actually shown. Leaflet measures
        # its container once, when the document loads, so building the map while
        # the tab is hidden leaves it with a 0x0 viewport that never asks for
        # any tiles - a permanently blank map.
        self._dirty = True

        # For map interaction: locations and the viewport they are clustered in
        # (ClusterState), the clusters the page is showing, and the overlay.
        self._state = ClusterState()
        self._clusters = []
        # Bumped whenever the page's markers are replaced. See update_clusters.
        self._cluster_generation = 0
        self._overlay = MosaicOverlay(self)
        # Set by arm_location: called with (latitude, longitude) by the next
        # double-click, instead of the map zooming.
        self._on_place = None

        # QWebChannel for communication with the page
        self._channel = QWebChannel()
        self._bridge = MapBridge(self)
        self._channel.registerObject("bridge", self._bridge)
        self.page().setWebChannel(self._channel)
        self._channel_ready = False
        self._pending_update = False

        # Debounce timer for viewport changes to avoid re-clustering too often
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(200)
        self._debounce_timer.timeout.connect(self._on_debounce_timeout)

        # Watchdog timer for QWebChannel handshake. If the handshake does not
        # complete within 5 seconds of the document loading, log an error so the
        # failure is visible to the user.
        self._channel_watchdog = QTimer()
        self._channel_watchdog.setSingleShot(True)
        self._channel_watchdog.setInterval(5000)
        self._channel_watchdog.timeout.connect(self._on_channel_watchdog_timeout)

        self.loadFinished.connect(self._on_load_finished)

    @property
    def _locations(self):
        """(id, lat, lon) for every photo with a location."""
        return self._state.locations

    def set_locations(self, rows):
        """Accept (id, lat, lon) tuples and trigger re-render if needed.

        Stores locations for clustering and selection, and derives centering
        coordinates from the location data. The clustering state forgets the
        previous viewport: the map is about to be rebuilt around the new set.
        """
        self._state.set_locations(rows)
        # Extract (lat, lon) pairs for centering the map
        self.coords = [(lat, lon) for _, lat, lon in self._locations]
        self._dirty = True
        if self.isVisible():
            self.render_map()

    def render_map(self):
        location, zoom = map_center_and_zoom(self.coords)
        # Location and zoom go to the constructor: folium copies the zoom into
        # the map's options when it is built, so assigning zoom_start afterwards
        # does nothing at all.
        self.map = folium.Map(location=location, zoom_start=zoom)

        # Add the Draw control for rectangle and polygon selection. Only enable
        # rectangle and polygon modes; disable polyline, circle, marker, and
        # circlemarker.
        draw_options = {
            "rectangle": True,
            "polygon": True,
            "polyline": False,
            "circle": False,
            "marker": False,
            "circlemarker": False,
        }
        Draw(export=False, position="topleft", draw_options=draw_options).add_to(
            self.map
        )

        self.load_map()
        self._dirty = False
        self._channel_ready = False

        # Cluster and push markers once the document is loaded
        if self._locations:
            self.update_clusters()

    def on_shown(self):
        """Called when the map becomes visible.

        A first show renders; a later one only has to tell Leaflet to re-measure,
        because the container it sized itself against may have changed while the
        tab was hidden.
        """
        if self._dirty:
            self.render_map()
        else:
            self.invalidate_size()

    def invalidate_size(self):
        if self.map_name:
            # Showing the tab while a re-rendered page is still loading names a
            # map variable the new document has not defined yet. Unguarded,
            # that logs "ReferenceError: map_... is not defined" on every such
            # show; the load-finished handler re-measures once it exists.
            name = self.map_name
            self.page().runJavaScript(f"window.{name} && {name}.invalidateSize()")

    def _on_load_finished(self, ok):
        """Re-measure once the document is actually live.

        setHtml loads asynchronously, so any invalidate_size() issued between
        load_map() and this signal names a Leaflet variable that does not exist
        yet and does nothing. This is the one call guaranteed to land after the
        map object exists.

        Start the channel handshake watchdog: if the handshake does not complete
        within 5 seconds, it is undiagnosable unless we log it explicitly.
        """
        if ok:
            self.invalidate_size()
            # A page built after arm_location ran - showing the tab often
            # rebuilds it - starts with zoom on again.
            if self._on_place is not None:
                self._set_double_click_zoom(False)
            # Start the watchdog timer to detect hangs in QWebChannel handshake
            self._channel_watchdog.start()

    def _on_channel_ready(self):
        """Called when the QWebChannel handshake completes on the page.

        The JavaScript side signals this after the bridge object is published,
        so we can now send updates to the page.
        """
        # Stop the watchdog timer; the handshake has completed successfully
        self._channel_watchdog.stop()
        self._channel_ready = True
        # Flush any updates that were queued while waiting for handshake
        if self._pending_update:
            self._pending_update = False
            self.update_clusters()

    def _on_channel_watchdog_timeout(self):
        """Called if the QWebChannel handshake does not complete within 5 seconds.

        This diagnostic makes a silent failure visible so the issue can be debugged.
        """
        if not self._channel_ready:
            logger.error(
                "QWebChannel handshake did not complete within 5 seconds; "
                "map interaction (clustering, selection, hover) is unavailable"
            )
            self.main.messages.add(
                "[ERROR] Map interaction unavailable: QWebChannel handshake timeout"
            )

    def update_clusters(self):
        """Cluster the current locations and push markers to the map.

        Only pushes if the channel is ready. Otherwise marks as pending so
        the update is sent once the handshake completes. With no locations the
        empty list is pushed like any other, so the page's markers are cleared.
        """
        if not self._channel_ready:
            self._pending_update = True
            return

        # Leaflet does not fire mouseout for a marker removed from under the
        # cursor, so a mosaic left up here would never be hidden. Take it down
        # with the markers it belongs to.
        self._overlay.hide_mosaic()

        self._clusters = self._state.cluster()
        # A hover from the page names a cluster by index, and the page's markers
        # may have been replaced since it was sent. The generation travels with
        # each marker so a stale hover is recognised and dropped.
        self._cluster_generation += 1

        # Convert clusters to JSON: only send lat, lon, and index
        clusters_json = json.dumps(
            [{"lat": c.lat, "lon": c.lon} for c in self._clusters]
        )

        # Push to the page using runJavaScript. Pass JSON directly, not as a
        # quoted string, so the page receives the parsed array.
        self.page().runJavaScript(
            f"updateClusters({clusters_json}, {self._cluster_generation})"
        )

    def _on_viewport_changed(self, zoom, min_lat, min_lon, max_lat, max_lon):
        """Handle viewport changes from the map.

        Debounce to avoid re-clustering too frequently during drag/zoom operations.
        """
        self._state.set_viewport(zoom, min_lat, min_lon, max_lat, max_lon)

        # Restart the debounce timer
        self._debounce_timer.stop()
        self._debounce_timer.start()

    def _on_debounce_timeout(self):
        """Called after the debounce timer expires."""
        self.update_clusters()

    def _on_hover(self, cluster_index, generation):
        """Show the mosaic overlay for a hovered cluster."""
        # The hover came from markers that have since been replaced, so its
        # index names a cluster in a list the page no longer shows.
        if generation != self._cluster_generation:
            return
        if cluster_index < 0 or cluster_index >= len(self._clusters):
            return

        cluster = self._clusters[cluster_index]
        # Take the first 9 photo IDs from this cluster
        photo_ids = cluster.ids[:9]

        if not photo_ids:
            return

        # Load thumbnails from the cache and compose the mosaic
        self._show_mosaic_for_photos(photo_ids, cluster_index)

    def _show_mosaic_for_photos(self, photo_ids, cluster_index):
        """Compose and show the mosaic overlay for the given photo IDs.

        Loads thumbnails from the cache using the existing Item infrastructure,
        composes them into a grid, and shows the overlay at the cursor position.
        """
        if not photo_ids:
            self._overlay.hide_mosaic()
            return

        try:
            from tagorganizer import db
            from tagorganizer.widgets.helper import load_pixmap

            # Fetch the Item objects for these IDs
            items = db.get_items_by_ids(photo_ids)
            if not items:
                self._overlay.hide_mosaic()
                return

            # Load thumbnails (150px is the standard size for the overlay)
            THUMBNAIL_SIZE = 150
            images = []
            for item in items:
                pixmap = load_pixmap(item, THUMBNAIL_SIZE, self.main.config.photos)
                if pixmap:
                    images.append(pixmap.toImage())

            if not images:
                self._overlay.hide_mosaic()
                return

            # Compose the mosaic
            mosaic = compose_mosaic(images, cell=THUMBNAIL_SIZE)
            if mosaic.isNull():
                self._overlay.hide_mosaic()
                return

            # Get the current cursor position and show the overlay
            mosaic_pixmap = QPixmap.fromImage(mosaic)
            self._overlay.show_for(mosaic_pixmap, QCursor.pos())

        except Exception:
            # Silently fail: a stale cluster index or database access issue
            # should not crash the map
            import logging

            logging.getLogger(__name__).exception(
                "Failed to show mosaic for cluster %s", cluster_index
            )

    def arm_location(self, on_place) -> None:
        """Let the next double-click choose a location, instead of zooming."""
        self._on_place = on_place
        self._set_double_click_zoom(False)

    def disarm_location(self) -> None:
        """Forget a pending arm_location; double-clicks zoom again."""
        if self._on_place is not None:
            self._on_place = None
            self._set_double_click_zoom(True)

    def _on_double_click(self, latitude, longitude):
        on_place, self._on_place = self._on_place, None
        if on_place is None:
            return
        self._set_double_click_zoom(True)
        on_place(latitude, longitude)

    def _set_double_click_zoom(self, enabled: bool) -> None:
        if self.map_name:
            action = "enable" if enabled else "disable"
            self.page().runJavaScript(
                f"window.{self.map_name} && {self.map_name}.doubleClickZoom.{action}()"
            )

    def _on_hover_end(self):
        """Hide the mosaic overlay."""
        self._overlay.hide_mosaic()

    def showEvent(self, event):
        super().showEvent(event)
        self.on_shown()

    def hideEvent(self, event):
        # Switching tabs does not deliver a mouseout, so a mosaic shown over
        # this map would otherwise stay on screen over the other tabs.
        self._overlay.hide_mosaic()
        # Leaving the map gives up on placing photos; a double-click made much
        # later, only to zoom, must not place photos chosen back then.
        self.disarm_location()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.invalidate_size()

    def get_bounds(self):
        if self.map_name:
            self.page().runJavaScript(
                f"{self.map_name}.getBounds()", self.bounds_callback
            )

    def bounds_callback(self, bounds):
        # A failed bounds query (when map_name is empty or folium format changes)
        # must not take down the tag bar. Silently ignore.
        if not bounds:
            return

        NE = bounds["_northEast"]
        SW = bounds["_southWest"]

        self.main.tag_bar.selected_area.set_values(
            min_longitude=SW["lng"],
            max_longitude=NE["lng"],
            min_latitude=SW["lat"],
            max_latitude=NE["lat"],
        )
        self.main.tag_bar.add_area_tag()

    def select_visible(self):
        """Select all photos currently visible in the viewport.

        Queries the map's current bounds and adds all locations within those
        bounds to the selection (without creating an area filter).
        """
        if self.map_name:
            self.page().runJavaScript(
                f"{self.map_name}.getBounds()", self._select_visible_callback
            )

    def _select_visible_callback(self, bounds):
        """Add all visible photos to the selection.

        Filters the cached locations by the current viewport bounds and adds
        them to the selection.
        """
        if not bounds:
            self.main.messages.add("[ERROR] Could not query map bounds")
            return

        NE = bounds["_northEast"]
        SW = bounds["_southWest"]

        min_lat = SW["lat"]
        max_lat = NE["lat"]
        min_lon = SW["lng"]
        max_lon = NE["lng"]

        visible_ids = ids_in_viewport(
            self._locations, (min_lat, min_lon, max_lat, max_lon)
        )

        if not visible_ids:
            self.main.messages.add("No photos visible in the current viewport")
            return

        # Add to the selection
        self.main.selection.add_many(visible_ids)
        self.main.update_items()
        self.main.update_numbers(selected=len(self.main.selection))
        self.main.messages.add(f"Selected {len(visible_ids)} photos")

    def load_map(self):
        data = io.BytesIO()
        self.map.save(data, close_file=False)
        html_content = data.getvalue().decode()
        self.map_name = parse_map_name(html_content)

        # Inject qwebchannel.js and the map interaction script
        qwebchannel_js = self._load_qwebchannel()
        injection = self._make_injection_script(qwebchannel_js)

        # Inject the script at </html>, not </body>. folium emits the map
        # creation (var map_xxx = L.map(...)) and the Draw control in a
        # trailing <script> block that comes AFTER </body>. Injecting at
        # </body> would run our script before the Leaflet map variable exists,
        # causing a ReferenceError that aborts before the QWebChannel handshake
        # and leaves the map with no markers and interaction disabled. Injecting
        # at </html> ensures our script runs after folium's map creation script.
        if "</html>" in html_content:
            html_content = html_content.replace(
                "</html>", f"<script>{injection}</script>\n</html>", 1
            )
        else:
            # Fallback if the document has no </html> tag: append to the end.
            # This silently producing an injection-free document would be a
            # failure mode as silent as the </body> bug.
            html_content = html_content + f"<script>{injection}</script>"

        self.setHtml(html_content)

    def _load_qwebchannel(self) -> str:
        """Load the qwebchannel.js library from Qt resources.

        The resource is verified readable and 16004 bytes. We inline it to avoid
        depending on qrc: loading from a page with no base URL.
        """
        qf = QFile(":/qtwebchannel/qwebchannel.js")
        if not qf.open(QFile.ReadOnly):
            # Log the failure and notify the user. The page will still render
            # the basemap, but map interaction will be unavailable.
            logger.error(
                "Cannot load qwebchannel.js resource: map clustering, hover "
                "previews, and viewport-based re-clustering will be unavailable"
            )
            self.main.messages.add(
                "[ERROR] Map interaction unavailable: qwebchannel.js could not be loaded"
            )
            return ""
        content = qf.readAll().data().decode()
        qf.close()
        return content

    def _make_injection_script(self, qwebchannel_js: str) -> str:
        """Build the JavaScript injection for map interaction.

        Inlines qwebchannel.js, sets up the layer group and update function,
        wires viewport change handlers, and handles drawn shape events.
        """
        # Map name is extracted from the folium HTML, e.g., "map_abc123"
        map_var = self.map_name

        return f"""
{qwebchannel_js}

var clustersLayer = L.layerGroup();
clustersLayer.addTo({map_var});

function updateClusters(clusters, generation) {{
    clustersLayer.clearLayers();
    clusters.forEach(function(cluster, index) {{
        var marker = L.marker([cluster.lat, cluster.lon]);
        marker.on('mouseover', function() {{
            bridge.hover(index, generation);
        }});
        marker.on('mouseout', function() {{
            bridge.hover_end();
        }});
        clustersLayer.addLayer(marker);
    }});
}}

// Set up the QWebChannel handshake
new QWebChannel(qt.webChannelTransport, function(channel) {{
    window.bridge = channel.objects.bridge;
    // Signal Python that the channel is ready for updates
    window.bridge.channel_ready();
}});

// Wire viewport changes
{map_var}.on('moveend', function() {{
    if (!window.bridge) return;
    var bounds = {map_var}.getBounds();
    var zoom = {map_var}.getZoom();
    window.bridge.viewport_changed(zoom, bounds.getSouth(), bounds.getWest(), bounds.getNorth(), bounds.getEast());
}});

{map_var}.on('zoomend', function() {{
    if (!window.bridge) return;
    var bounds = {map_var}.getBounds();
    var zoom = {map_var}.getZoom();
    window.bridge.viewport_changed(zoom, bounds.getSouth(), bounds.getWest(), bounds.getNorth(), bounds.getEast());
}});

// Report double-clicks; Python uses one when asked to place photos.
{map_var}.on('dblclick', function(e) {{
    if (!window.bridge) return;
    window.bridge.map_double_clicked(e.latlng.lat, e.latlng.lng);
}});

// Handle drawn shapes from the Leaflet Draw plugin
{map_var}.on('draw:created', function(e) {{
    if (!window.bridge) return;
    var layer = e.layer;
    var geometry = layer.toGeoJSON().geometry;
    // Send the geometry as a JSON string to Python
    window.bridge.shape_drawn(JSON.stringify(geometry));
}});
"""


class MapWidget(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main

        layout = QVBoxLayout()

        # Create the map view
        self.view = MapView(main)

        # Create buttons for area filter and visible selection
        buttons_layout = QHBoxLayout()
        self.select_area_button = QPushButton("Select area")
        self.select_area_button.clicked.connect(self.select_area)
        self.select_visible_button = QPushButton("Select visible")
        self.select_visible_button.clicked.connect(self.select_visible)

        buttons_layout.addWidget(self.select_area_button)
        buttons_layout.addWidget(self.select_visible_button)

        # Add the map and buttons to the layout
        layout.addWidget(self.view)
        layout.addLayout(buttons_layout)

        # Set the layout for the QWidget
        self.setLayout(layout)

    def set_locations(self, rows):
        self.view.set_locations(rows)

    def on_shown(self):
        """Tell the view it is visible, so it can render or re-measure."""
        self.view.on_shown()

    def select_area(self):
        self.view.get_bounds()

    def select_visible(self):
        self.view.select_visible()
