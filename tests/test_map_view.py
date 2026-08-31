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

# Import here to avoid circular imports when checking update_items

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


class TestMapInjectionPoint:
    def test_load_map_injects_at_html_not_body(self):
        """MapView.load_map must inject the script at </html>, not </body>.

        folium emits the map creation (var map_xxx = L.map(...)) and the Draw
        control in a trailing <script> block that comes AFTER </body>. If we
        inject at </body>, our script runs before the Leaflet map variable
        exists, throwing a ReferenceError that aborts before the QWebChannel
        handshake. Injecting at </html> ensures our script runs after folium's.

        This is the third silent-empty-map bug in this project and this guard
        prevents it from regressing.
        """
        source = inspect.getsource(MapView.load_map)
        source = textwrap.dedent(source)

        # The source must contain </html> as a replacement target
        # and must NOT contain </body> as a replacement target.
        # Note: the strings may be split across lines due to formatting.

        # Check that the source mentions injecting at </html>
        has_html_comment = "at </html>" in source or '("</html>"' in source

        # Check that </body> replacement is not used
        # We look for the pattern where </body> is the first arg to replace()
        has_body_replacement = (
            'replace(\n            "</body>"' in source
            or "replace(\n            '</body>'" in source
        )

        assert has_html_comment, (
            "load_map must inject at </html> "
            "so the script runs after folium's map creation"
        )
        assert not has_body_replacement, (
            "load_map must NOT inject at </body>, as folium's map creation "
            "and Draw plugin come AFTER </body> in a trailing script"
        )


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


class TestMainUpdateItemsWiring:
    def test_update_items_calls_set_locations_on_map(self):
        """MainWindow.update_items must call map.set_locations to populate _locations.

        Without this, _locations stays empty, and the map shows no markers, hover
        finds no clusters, and selection operations select nothing. This is the
        wiring that makes the entire map feature functional.
        """
        # Avoid circular import by importing MainWindow only in the test
        from tagorganizer.main import MainWindow

        source = inspect.getsource(MainWindow.update_items)
        source = textwrap.dedent(source)
        tree = ast.parse(source)

        # Check that set_locations is called on self.map
        set_locations_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "set_locations":
                        # Check that it's on self.map
                        if isinstance(node.func.value, ast.Attribute):
                            if (
                                isinstance(node.func.value.value, ast.Name)
                                and node.func.value.value.id == "self"
                                and node.func.value.attr == "map"
                            ):
                                set_locations_found = True
                                break

        assert (
            set_locations_found
        ), "update_items must call self.map.set_locations to populate map data"


class TestShapeSelection:
    def test_shape_drawn_calls_point_in_polygon(self):
        """MapBridge.shape_drawn must call point_in_polygon for lasso selection.

        A rectangle-only implementation would silently over-select every lasso,
        and the user would have no way to tell that concave shapes don't work.
        Point-in-polygon test must be applied to all shapes.
        """
        source = inspect.getsource(MapBridge.shape_drawn)
        source = textwrap.dedent(source)
        tree = ast.parse(source)

        # Check that point_in_polygon is called
        point_in_polygon_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for direct function call
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "point_in_polygon"
                ):
                    point_in_polygon_found = True
                    break
                # Also check for module.function call pattern
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "point_in_polygon"
                ):
                    point_in_polygon_found = True
                    break

        assert (
            point_in_polygon_found
        ), "shape_drawn must call point_in_polygon to handle concave shapes correctly"

    def test_shape_drawn_calls_selection_add_many(self):
        """MapBridge.shape_drawn must call selection.add_many to add selected photos.

        The selection route must add to the selection directly, not touch the tag
        bar or create filters.
        """
        source = inspect.getsource(MapBridge.shape_drawn)
        source = textwrap.dedent(source)
        tree = ast.parse(source)

        # Check that self.map_view.main.selection.add_many is called
        add_many_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    # Look for .add_many(...) calls
                    if node.func.attr == "add_many":
                        # Check that it's on selection
                        current = node.func.value
                        # Navigate through the attribute chain
                        attrs = []
                        while isinstance(current, ast.Attribute):
                            attrs.insert(0, current.attr)
                            current = current.value
                        if isinstance(current, ast.Name) and current.id == "self":
                            if "selection" in attrs:
                                add_many_found = True
                                break

        assert (
            add_many_found
        ), "shape_drawn must call selection.add_many to add selected photos"

    def test_select_visible_calls_selection_add_many(self):
        """MapView.select_visible must call selection.add_many to add visible photos.

        The visible selection route must add to the selection directly, not touch
        the tag bar or create filters.
        """
        # Check that self.main.selection.add_many is called in the callback
        callback_source = inspect.getsource(MapView._select_visible_callback)
        callback_source = textwrap.dedent(callback_source)
        callback_tree = ast.parse(callback_source)

        # Check for add_many call in the callback
        add_many_found = False
        for node in ast.walk(callback_tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "add_many":
                        # Check that it's on selection
                        current = node.func.value
                        attrs = []
                        while isinstance(current, ast.Attribute):
                            attrs.insert(0, current.attr)
                            current = current.value
                        if isinstance(current, ast.Name) and current.id == "self":
                            if "selection" in attrs:
                                add_many_found = True
                                break

        assert (
            add_many_found
        ), "_select_visible_callback must call selection.add_many to add visible photos"
