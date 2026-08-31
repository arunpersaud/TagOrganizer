import io
import json
import folium
from qtpy.QtWebEngineWidgets import QWebEngineView
from qtpy.QtWebChannel import QWebChannel
from qtpy.QtWidgets import QWidget, QVBoxLayout, QPushButton
from qtpy.QtCore import QObject, QTimer, QFile, Slot
from qtpy.QtGui import QPixmap, QCursor
from tagorganizer.map_cluster import cell_size_for_zoom, cluster_points
from tagorganizer.widgets.map_overlay import MosaicOverlay, compose_mosaic


DEFAULT_LOCATION = [37.7749, -122.4194]
DEFAULT_ZOOM = 2
FITTED_ZOOM = 4


class MapBridge(QObject):
    """The page's handle on Python.

    Registered on a QWebChannel under a name the injected script knows. Slots
    must be declared with @Slot or they are not visible to JavaScript.
    """

    def __init__(self, map_view):
        super().__init__()
        self.map_view = map_view

    @Slot(int)
    def hover(self, cluster_index):
        """Show the mosaic overlay for a hovered cluster."""
        self.map_view._on_hover(cluster_index)

    @Slot()
    def hover_end(self):
        """Hide the mosaic overlay."""
        self.map_view._on_hover_end()

    @Slot(int, float, float, float, float)
    def viewport_changed(self, zoom, min_lat, min_lon, max_lat, max_lon):
        """Handle map viewport changes: debounce and re-cluster."""
        self.map_view._on_viewport_changed(zoom, min_lat, min_lon, max_lat, max_lon)

    @Slot(str)
    def shape_drawn(self, geojson):
        """Handle lasso selection (future task)."""
        pass


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

        # For map interaction: locations, clusters, and overlay
        self._locations = []
        self._clusters = []
        self._overlay = MosaicOverlay(self)

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
        self._viewport_zoom = 0
        self._viewport_bounds = None

        self.loadFinished.connect(self._on_load_finished)

    def set_location(self, longitude, latitude, zoom):
        if self.map is None:
            return
        self.map.location = [latitude, longitude]
        self.load_map()

    def set_markers(self, coords):
        """Remember the points to plot, and redraw if we are on screen."""
        self.coords = list(coords)
        self._dirty = True
        if self.isVisible():
            self.render_map()

    def set_locations(self, rows):
        """Accept (id, lat, lon) tuples and trigger re-render if needed.

        This replaces the coordinate-based rendering and prepares for clustering.
        """
        self._locations = list(rows)
        self._dirty = True
        if self.isVisible():
            self.render_map()

    def render_map(self):
        location, zoom = map_center_and_zoom(self.coords)
        # Location and zoom go to the constructor: folium copies the zoom into
        # the map's options when it is built, so assigning zoom_start afterwards
        # does nothing at all.
        self.map = folium.Map(location=location, zoom_start=zoom)
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
            self.page().runJavaScript(f"{self.map_name}.invalidateSize()")

    def _on_load_finished(self, ok):
        """Re-measure once the document is actually live.

        setHtml loads asynchronously, so any invalidate_size() issued between
        load_map() and this signal names a Leaflet variable that does not exist
        yet and is silently dropped. This is the one call guaranteed to land
        after the map object exists.

        Also check if the channel is ready and push any pending updates.
        """
        if ok:
            self.invalidate_size()
            # Check if the channel handshake completed
            self.page().runJavaScript(
                "window.bridgeReady || false",
                lambda result: self._on_channel_ready_check(result),
            )

    def _on_channel_ready_check(self, ready):
        """Called when we check if the channel is ready.

        If ready and we have pending updates, push them now.
        """
        if ready:
            self._channel_ready = True
            if self._pending_update and self._locations:
                self._pending_update = False
                self.update_clusters()

    def update_clusters(self):
        """Cluster the current locations and push markers to the map.

        Only pushes if the channel is ready. Otherwise marks as pending so
        the update is sent once the handshake completes.
        """
        if not self._channel_ready:
            self._pending_update = True
            return

        if not self._locations:
            # No locations, clear the clusters
            self.page().runJavaScript("updateClusters('[]')")
            return

        # Calculate cell size based on current zoom (default to FITTED_ZOOM)
        zoom = self._viewport_zoom if self._viewport_zoom > 0 else FITTED_ZOOM
        cell_size = cell_size_for_zoom(zoom)
        bounds = self._viewport_bounds

        # Cluster the locations
        self._clusters = cluster_points(self._locations, cell_size, bounds)

        # Convert clusters to JSON: only send lat, lon, and index
        clusters_json = json.dumps(
            [{"lat": c.lat, "lon": c.lon} for c in self._clusters]
        )

        # Push to the page using runJavaScript
        self.page().runJavaScript(f"updateClusters('{clusters_json}')")

    def _on_viewport_changed(self, zoom, min_lat, min_lon, max_lat, max_lon):
        """Handle viewport changes from the map.

        Debounce to avoid re-clustering too frequently during drag/zoom operations.
        """
        self._viewport_zoom = zoom
        self._viewport_bounds = (min_lat, min_lon, max_lat, max_lon)

        # Restart the debounce timer
        self._debounce_timer.stop()
        self._debounce_timer.start()

    def _on_debounce_timeout(self):
        """Called after the debounce timer expires."""
        self.update_clusters()

    def _on_hover(self, cluster_index):
        """Show the mosaic overlay for a hovered cluster."""
        # Guard against stale index (clusters may have changed since hover started)
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

    def _on_hover_end(self):
        """Hide the mosaic overlay."""
        self._overlay.hide_mosaic()

    def showEvent(self, event):
        super().showEvent(event)
        self.on_shown()

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

    def load_map(self):
        data = io.BytesIO()
        self.map.save(data, close_file=False)
        html_content = data.getvalue().decode()
        self.map_name = parse_map_name(html_content)

        # Inject qwebchannel.js and the map interaction script
        qwebchannel_js = self._load_qwebchannel()
        injection = self._make_injection_script(qwebchannel_js)

        # Insert the injection before </body>
        html_content = html_content.replace(
            "</body>", f"<script>{injection}</script>\n</body>", 1
        )

        self.setHtml(html_content)

    def _load_qwebchannel(self) -> str:
        """Load the qwebchannel.js library from Qt resources.

        The resource is verified readable and 16004 bytes. We inline it to avoid
        depending on qrc: loading from a page with no base URL.
        """
        qf = QFile(":/qtwebchannel/qwebchannel.js")
        if not qf.open(QFile.ReadOnly):
            # Fallback: return empty string so the page still works
            # (but without the channel handshake)
            return ""
        content = qf.readAll().data().decode()
        qf.close()
        return content

    def _make_injection_script(self, qwebchannel_js: str) -> str:
        """Build the JavaScript injection for map interaction.

        Inlines qwebchannel.js, sets up the layer group and update function,
        and wires viewport change handlers.
        """
        # Map name is extracted from the folium HTML, e.g., "map_abc123"
        map_var = self.map_name

        return f"""
{qwebchannel_js}

var clustersLayer = L.layerGroup();
clustersLayer.addTo({map_var});

function updateClusters(json) {{
    clustersLayer.clearLayers();
    var clusters = JSON.parse(json);
    clusters.forEach(function(cluster, index) {{
        var marker = L.marker([cluster.lat, cluster.lon]);
        marker.on('mouseover', function() {{
            bridge.hover(index);
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
    // Signal that the channel is ready for updates
    window.bridgeReady = true;
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
"""


class MapWidget(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main

        layout = QVBoxLayout()

        # Create two QLabel widgets
        self.view = MapView(main)
        self.button = QPushButton("Select area")
        self.button.clicked.connect(self.select_area)

        # Add the QLabel widgets to the layout
        layout.addWidget(self.view)
        layout.addWidget(self.button)

        # Set the layout for the QWidget
        self.setLayout(layout)

    def set_markers(self, coords):
        self.view.set_markers(coords)

    def on_shown(self):
        """Tell the view it is visible, so it can render or re-measure."""
        self.view.on_shown()

    def select_area(self):
        self.view.get_bounds()
