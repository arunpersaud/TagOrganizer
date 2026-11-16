"""Clustering photo locations for the map, and the geometry a lasso needs.

Clustering happens here rather than in Leaflet because Leaflet's MarkerCluster
builds a JavaScript object per photo - measured at ~208 bytes each, which hits
QtWebEngine's ~2 MB setHtml ceiling at roughly 10 000 photos and then silently
blanks the map. Bucketing here means the page carries a few hundred centroids
whatever the library size.

Deliberately free of Qt and of the database, so it can be tested directly.
"""

import math
from dataclasses import dataclass, field
from itertools import pairwise

# Leaflet's world is 256 pixels wide at zoom 0 and doubles each level.
TILE_SIZE_PX = 256
WORLD_DEGREES = 360.0

# The zoom the map fits its photos at, and the zoom clustering assumes before
# the page has reported one. Lives here so the clustering state can use it.
FITTED_ZOOM = 4


@dataclass
class Cluster:
    lat: float
    lon: float
    ids: list[int] = field(default_factory=list)


def cell_size_for_zoom(zoom: int, target_px: int = 60) -> float:
    """Grid cell size in degrees that stays a constant size on screen.

    At a given zoom the world spans TILE_SIZE_PX * 2**zoom pixels across
    WORLD_DEGREES, so a cell of target_px pixels covers this many degrees. Using
    a screen-relative size is what keeps the number of visible clusters roughly
    constant instead of growing as the user zooms out over a large library.
    """
    return WORLD_DEGREES * target_px / (TILE_SIZE_PX * (2**zoom))


def shift_longitude_into(lon: float, min_lon: float, max_lon: float):
    """The representative of `lon` inside [min_lon, max_lon], or None.

    Leaflet's getBounds() reports longitudes past +/-180 once the view has been
    panned across the antimeridian, and a photo at -175 is on screen at 185 in
    such a view. Only whole turns of the world are added or taken away, so the
    answer is the same point, drawn on the copy of the world that is visible.
    """
    if max_lon < min_lon:
        return None
    # The smallest whole-turn shift that lifts lon to at least min_lon. If that
    # still overshoots max_lon, no shift lands inside the span; a span of a full
    # world or more always does.
    turns = math.ceil((min_lon - lon) / WORLD_DEGREES)
    candidate = lon + turns * WORLD_DEGREES
    return candidate if candidate <= max_lon else None


def unwrap_longitudes(lons) -> list[float]:
    """Make a ring of longitudes continuous, so it can be tested as a polygon.

    A lasso drawn across the seam arrives as 170, -175, -170 - which a
    point-in-polygon test reads as a shape spanning the whole planet. Each step
    is taken the short way round instead, giving 170, 185, 190.
    """
    if not lons:
        return []
    unwrapped = [float(lons[0])]
    for previous, lon in pairwise(lons):
        step = (lon - previous + 180.0) % WORLD_DEGREES - 180.0
        unwrapped.append(unwrapped[-1] + step)
    return unwrapped


def ids_in_viewport(locations, bounds) -> list[int]:
    """The ids of (id, lat, lon) locations visible in `bounds`.

    `bounds` is (min_lat, min_lon, max_lat, max_lon) as Leaflet reports it,
    which may run past the antimeridian.
    """
    min_lat, min_lon, max_lat, max_lon = bounds
    return [
        item_id
        for item_id, lat, lon in locations
        if min_lat <= lat <= max_lat
        and shift_longitude_into(lon, min_lon, max_lon) is not None
    ]


def cluster_points(points, cell_size: float, bounds=None) -> list[Cluster]:
    """Bucket (id, lat, lon) triples into a grid.

    `bounds` is (min_lat, min_lon, max_lat, max_lon); points outside it are
    dropped. Restricting to the viewport is what bounds the emitted count -
    without it a zoomed-in map would still pay for every photo in the library.
    A point on the far side of the antimeridian is placed at the longitude the
    viewport shows it at, so its cluster is drawn where the user can see it.

    Cluster order is stable for a given input, because the index of a cluster is
    what gets sent to the page and looked up again when the user hovers it.
    """
    # Guard against invalid cell_size. The size derives from a zoom level that a
    # later task will receive from JavaScript over QWebChannel, which is the least
    # controlled input in this codebase. A bare ZeroDivisionError deep in clustering
    # would be obscure to diagnose, so we fail early with a clear message.
    if cell_size <= 0:
        raise ValueError("cell_size must be positive")

    buckets: dict[tuple[int, int], list] = {}
    order: list[tuple[int, int]] = []

    for item_id, lat, lon in points:
        if bounds is not None:
            min_lat, min_lon, max_lat, max_lon = bounds
            if not min_lat <= lat <= max_lat:
                continue
            lon = shift_longitude_into(lon, min_lon, max_lon)
            if lon is None:
                continue
        key = (int(lat // cell_size), int(lon // cell_size))
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append((item_id, lat, lon))

    clusters = []
    for key in order:
        members = buckets[key]
        clusters.append(
            Cluster(
                lat=sum(m[1] for m in members) / len(members),
                lon=sum(m[2] for m in members) / len(members),
                ids=[m[0] for m in members],
            )
        )
    return clusters


class ClusterState:
    """What the map clusters: its locations, and the viewport they are seen in.

    Pure so the rule that matters can be tested directly. A new set of
    locations comes with a new map document, whose viewport the page has not
    reported yet, so the previous viewport must not clip it. Until the page
    reports one, everything is clustered at the fitted zoom.
    """

    def __init__(self):
        self.locations = []
        self.zoom = 0
        self.bounds = None

    def set_locations(self, rows) -> None:
        self.locations = list(rows)
        self.zoom = 0
        self.bounds = None

    def set_viewport(self, zoom, min_lat, min_lon, max_lat, max_lon) -> None:
        self.zoom = zoom
        self.bounds = (min_lat, min_lon, max_lat, max_lon)

    def cluster(self) -> list[Cluster]:
        zoom = self.zoom if self.zoom > 0 else FITTED_ZOOM
        return cluster_points(self.locations, cell_size_for_zoom(zoom), self.bounds)


def point_in_polygon(lat: float, lon: float, polygon) -> bool:
    """Ray-casting point-in-polygon test.

    Used for lasso selection. A lasso that selected everything in its bounding
    box would not be a lasso - a concave shape has to exclude its own notches.
    """
    if len(polygon) < 3:
        return False

    inside = False
    count = len(polygon)
    for i in range(count):
        lat_i, lon_i = polygon[i]
        lat_j, lon_j = polygon[(i - 1) % count]
        intersects = (lon_i > lon) != (lon_j > lon) and lat < (
            (lat_j - lat_i) * (lon - lon_i) / (lon_j - lon_i) + lat_i
        )
        if intersects:
            inside = not inside
    return inside
