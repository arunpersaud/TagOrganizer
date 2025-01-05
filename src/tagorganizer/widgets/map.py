import io
import folium
from folium.plugins import FastMarkerCluster
from qtpy.QtWebEngineWidgets import QWebEngineView
from qtpy.QtWebChannel import QWebChannel
from qtpy.QtCore import QObject, Slot, Signal

import numpy as np

from ..models import Item


class MapBackend(QObject):
    boundsChanged = Signal(list)
    markerClicked = Signal(str)

    def __init__(self):
        super().__init__()

    @Slot(list)
    def on_bounds_received(self, bounds):
        print(f"North-East: {bounds[0]}, {bounds[1]}")
        print(f"South-West: {bounds[2]}, {bounds[3]}")
        self.boundsChanged.emit(bounds)

    @Slot(str)
    def on_marker_clicked(self, marker_id):
        print(f"Marker clicked: {marker_id}")
        self.markerClicked.emit(marker_id)


class MapWidget(QWebEngineView):
    def __init__(self):
        super().__init__()

        self.map = folium.Map(location=[37.7749, -122.4194], zoom_start=2)
        self.backend = MapBackend()
        self.channel = QWebChannel()
        self.channel.registerObject("backend", self.backend)
        self.page().setWebChannel(self.channel)
        self.load_map()

        # Connect signals to slots
        self.backend.boundsChanged.connect(self.handle_bounds_changed)
        self.backend.markerClicked.connect(self.handle_marker_clicked)

    def set_location(self, longitude, latitude, zoom):
        self.map.location = [latitude, longitude]
        self.map.zoom_start = zoom
        self.load_map()

    def get_bounds(self):
        self.page().runJavaScript(
            """
            var bounds = map.getBounds();
            var ne = bounds.getNorthEast();
            var sw = bounds.getSouthWest();
            [ne.lat, ne.lng, sw.lat, sw.lng];
        """,
            self.backend.on_bounds_received,
        )

    def set_markers(self, items: list[Item]):
        markers = []
        lat = []
        lon = []
        for item in items:
            if (item.longitude is not None) and (item.latitude is not None):
                lat.append(item.latitude)
                lon.append(item.longitude)
                markers.append([item.latitude, item.longitude])

        FastMarkerCluster(markers).add_to(self.map)

        if len(lat):
            lat = np.array(lat)
            lon = np.array(lon)
            self.map.location = [lat.mean(), lon.mean()]
            self.map.zoom_start = 4

        self.load_map()

    def load_map(self):
        data = io.BytesIO()
        self.map.save(data, close_file=False)
        html_content = data.getvalue().decode()
        html_content = self.add_web_channel(html_content)
        self.setHtml(html_content)

    def add_web_channel(self, html_content):
        return html_content.replace(
            "</head>",
            """
            <script type="text/javascript" src="qrc:///qtwebchannel/qwebchannel.js"></script>
            <script type="text/javascript">
                document.addEventListener("DOMContentLoaded", function() {
                    new QWebChannel(qt.webChannelTransport, function(channel) {
                        window.backend = channel.objects.backend;
                    });
                    map.on('moveend', function() {
                        var bounds = map.getBounds();
                        var ne = bounds.getNorthEast();
                        var sw = bounds.getSouthWest();
                        backend.on_bounds_received([ne.lat, ne.lng, sw.lat, sw.lng]);
                    });
                });
            </script>
            </head>
            """,
        )

    def handle_bounds_changed(self, bounds):
        print(f"Bounds changed: {bounds}")

    def handle_marker_clicked(self, marker_id):
        print(f"Marker clicked: {marker_id}")
