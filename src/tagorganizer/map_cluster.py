"""Clustering photo locations for the map, and the geometry a lasso needs.

Clustering happens here rather than in Leaflet because Leaflet's MarkerCluster
builds a JavaScript object per photo - measured at ~208 bytes each, which hits
QtWebEngine's ~2 MB setHtml ceiling at roughly 10 000 photos and then silently
blanks the map. Bucketing here means the page carries a few hundred centroids
whatever the library size.

Deliberately free of Qt and of the database, so it can be tested directly.
"""

from dataclasses import dataclass, field

# Leaflet's world is 256 pixels wide at zoom 0 and doubles each level.
TILE_SIZE_PX = 256
WORLD_DEGREES = 360.0


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


def cluster_points(points, cell_size: float, bounds=None) -> list[Cluster]:
    """Bucket (id, lat, lon) triples into a grid.

    `bounds` is (min_lat, min_lon, max_lat, max_lon); points outside it are
    dropped. Restricting to the viewport is what bounds the emitted count -
    without it a zoomed-in map would still pay for every photo in the library.

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
            if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
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
