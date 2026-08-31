"""Tests for the map view's pure helpers.

The rendering itself needs QtWebEngine and a real window, so only the decisions
are tested here: where to centre, how far to zoom, and how the Leaflet variable
name is recovered from a rendered document.
"""

import ast
import inspect
import textwrap
from tagorganizer.widgets.map import (
    map_center_and_zoom,
    parse_map_name,
    MapBridge,
    MapView,
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
    def test_declares_hover_slot(self):
        """MapBridge must declare a hover(int) slot."""
        source = inspect.getsource(MapBridge)
        tree = ast.parse(source)
        hover_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "hover":
                # Check for @Slot decorator
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        if (
                            isinstance(decorator.func, ast.Name)
                            and decorator.func.id == "Slot"
                        ):
                            hover_found = True
                            break
        assert hover_found, "MapBridge.hover must be decorated with @Slot"

    def test_declares_hover_end_slot(self):
        """MapBridge must declare a hover_end() slot."""
        source = inspect.getsource(MapBridge)
        tree = ast.parse(source)
        hover_end_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "hover_end":
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        if (
                            isinstance(decorator.func, ast.Name)
                            and decorator.func.id == "Slot"
                        ):
                            hover_end_found = True
                            break
        assert hover_end_found, "MapBridge.hover_end must be decorated with @Slot"

    def test_declares_viewport_changed_slot(self):
        """MapBridge must declare a viewport_changed(int, float, float, float, float) slot."""
        source = inspect.getsource(MapBridge)
        tree = ast.parse(source)
        viewport_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "viewport_changed":
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        if (
                            isinstance(decorator.func, ast.Name)
                            and decorator.func.id == "Slot"
                        ):
                            viewport_found = True
                            break
        assert viewport_found, "MapBridge.viewport_changed must be decorated with @Slot"

    def test_declares_shape_drawn_slot(self):
        """MapBridge must declare a shape_drawn(str) slot."""
        source = inspect.getsource(MapBridge)
        tree = ast.parse(source)
        shape_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "shape_drawn":
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        if (
                            isinstance(decorator.func, ast.Name)
                            and decorator.func.id == "Slot"
                        ):
                            shape_found = True
                            break
        assert shape_found, "MapBridge.shape_drawn must be decorated with @Slot"

    def test_declares_channel_ready_slot(self):
        """MapBridge must declare a channel_ready() slot.

        This slot is called by JavaScript when the QWebChannel handshake
        completes, signaling that Python can now send updates to the page.
        """
        source = inspect.getsource(MapBridge)
        tree = ast.parse(source)
        channel_ready_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "channel_ready":
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        if (
                            isinstance(decorator.func, ast.Name)
                            and decorator.func.id == "Slot"
                        ):
                            channel_ready_found = True
                            break
        assert (
            channel_ready_found
        ), "MapBridge.channel_ready must be decorated with @Slot"


class TestChannelReadinessFlushing:
    def test_on_channel_ready_assigns_channel_ready_flag(self):
        """MapView._on_channel_ready must set _channel_ready = True.

        This is called when the JavaScript side signals the handshake is
        complete, so we know it is safe to send updates to the page.
        """
        source = inspect.getsource(MapView._on_channel_ready)
        source = textwrap.dedent(source)
        tree = ast.parse(source)

        # Look for self._channel_ready = True
        assignment_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        if (
                            isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                            and target.attr == "_channel_ready"
                        ):
                            if (
                                isinstance(node.value, ast.Constant)
                                and node.value.value is True
                            ):
                                assignment_found = True
                                break
        assert (
            assignment_found
        ), "_on_channel_ready must assign True to self._channel_ready"


class TestMapViewWebChannelIntegration:
    def test_render_map_inlines_qwebchannel(self):
        """The render_map path must inline qwebchannel.js into the HTML.

        Inlining avoids depending on qrc: loading from a setHtml page with no
        base URL, which may not resolve.
        """
        source = inspect.getsource(MapView.render_map)
        source = textwrap.dedent(source)
        tree = ast.parse(source)

        # Check that load_map is called (which does the injection)
        load_map_called = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "load_map"
                ):
                    load_map_called = True
                    break

        assert load_map_called, "render_map must call load_map()"

    def test_no_setHtml_in_viewport_change_path(self):
        """No setHtml should be called on viewport changes.

        setHtml reloads the document, resetting the user's viewport and
        retriggering the Leaflet initialization that must be fixed. Viewport
        changes should only update markers in place.
        """
        # Check methods that handle viewport changes
        viewport_change_methods = [
            "_on_viewport_changed",
            "_on_debounce_timeout",
            "update_clusters",
        ]

        source = inspect.getsource(MapView)
        source = textwrap.dedent(source)
        tree = ast.parse(source)

        # Find all setHtml calls
        sethtml_locations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr == "setHtml":
                    # Get the line number
                    sethtml_locations.append(node.lineno)

        # Check that setHtml is only called in load_map or render_map, not in
        # viewport change handling
        source_lines = inspect.getsource(MapView).split("\n")

        # Find the line ranges of viewport change methods
        for method_name in viewport_change_methods:
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == method_name:
                    method_start = node.lineno
                    method_end = node.end_lineno or len(source_lines)

                    # Check if any setHtml calls fall within this method
                    for sethtml_line in sethtml_locations:
                        if method_start <= sethtml_line <= method_end:
                            raise AssertionError(
                                f"setHtml should not be called in {method_name} "
                                f"(line {sethtml_line}). Viewport changes must update "
                                "markers in place, not reload the document."
                            )
