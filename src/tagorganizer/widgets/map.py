import io
import folium
from folium.plugins import FastMarkerCluster
from qtpy.QtWebEngineWidgets import QWebEngineView
from qtpy.QtWidgets import QWidget, QVBoxLayout, QPushButton


DEFAULT_LOCATION = [37.7749, -122.4194]
DEFAULT_ZOOM = 2
FITTED_ZOOM = 4


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

    def render_map(self):
        location, zoom = map_center_and_zoom(self.coords)
        # Location and zoom go to the constructor: folium copies the zoom into
        # the map's options when it is built, so assigning zoom_start afterwards
        # does nothing at all.
        self.map = folium.Map(location=location, zoom_start=zoom)
        if self.coords:
            FastMarkerCluster(self.coords).add_to(self.map)
        self.load_map()
        self._dirty = False

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
        """
        if ok:
            self.invalidate_size()

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
        self.setHtml(html_content)


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
