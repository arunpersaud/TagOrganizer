import io
import folium
from folium.plugins import FastMarkerCluster
from qtpy.QtWebEngineWidgets import QWebEngineView
from qtpy.QtWidgets import QWidget, QVBoxLayout, QPushButton

import numpy as np


class MapView(QWebEngineView):
    def __init__(self, main):
        super().__init__()
        self.main = main

        self.map = folium.Map(location=[37.7749, -122.4194], zoom_start=2)
        self.map_name = ""
        self.load_map()

    def set_location(self, longitude, latitude, zoom):
        self.map.location = [latitude, longitude]
        self.map.zoom_start = zoom
        self.load_map()

    def get_bounds(self):
        self.page().runJavaScript(f"{self.map_name}.getBounds()", self.bounds_callback)

    def bounds_callback(self, bounds):
        NE = bounds["_northEast"]
        SW = bounds["_southWest"]

        self.main.tag_bar.selected_area.set_values(
            min_longitude=SW["lng"],
            max_longitude=NE["lng"],
            min_latitude=SW["lat"],
            max_latitude=NE["lat"],
        )
        self.main.tag_bar.add_area_tag()

    def set_markers(self, coords: list[float, float]):
        # recreate map, to get rid of old markers
        self.map = folium.Map(location=[37.7749, -122.4194], zoom_start=2)

        FastMarkerCluster(coords).add_to(self.map)

        coords = np.array(coords)
        if len(coords):
            self.map.location = [coords[:, 0].mean(), coords[:, 1].mean()]
            self.map.zoom_start = 4

        self.load_map()

    def load_map(self):
        data = io.BytesIO()
        self.map.save(data, close_file=False)
        html_content = data.getvalue().decode()
        for line in html_content.split("\n"):
            if "L.map" in line:
                tmp = line.strip()
                tmp = tmp.split()
                self.map_name = tmp[1]
                print(self.map_name)
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

    def select_area(self):
        self.view.get_bounds()
