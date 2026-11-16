"""What the map relies on in folium's own output.

widgets/map.py reads the Leaflet variable name out of the HTML folium writes,
then injects JavaScript at </html> that names that variable and listens for
Leaflet Draw's 'draw:created' event. Nothing here runs that JavaScript. These
tests pin the parts of folium's document the Python side depends on, so a
folium upgrade that moves them fails in the suite rather than in the map.
"""

import io

import folium
from folium.plugins import Draw

from tagorganizer.widgets.map import parse_map_name


def _folium_document():
    m = folium.Map(location=[40.7, -74.0], zoom_start=9)
    Draw(
        export=False,
        position="topleft",
        draw_options={
            "rectangle": True,
            "polygon": True,
            "polyline": False,
            "circle": False,
            "marker": False,
            "circlemarker": False,
        },
    ).add_to(m)
    data = io.BytesIO()
    m.save(data, close_file=False)
    return data.getvalue().decode()


def test_the_document_names_its_leaflet_map():
    html = _folium_document()
    name = parse_map_name(html)
    assert name.startswith("map_")
    assert f"var {name} = L.map(" in html


def test_the_map_is_created_before_the_closing_html_tag():
    """The injected script goes in at </html>, so it runs after this creation."""
    html = _folium_document()
    name = parse_map_name(html)
    assert html.index(f"var {name} = L.map(") < html.rindex("</html>")


def test_the_draw_plugin_fires_the_event_the_script_listens_for():
    html = _folium_document()
    name = parse_map_name(html)
    assert f"{name}.on('draw:created'" in html
