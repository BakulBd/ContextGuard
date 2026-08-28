"""Minimal polygon geometry -- deliberately dependency-free.

Shapely would be the obvious choice, but as of this writing it has no
Python 3.14 wheel and would force a from-source GEOS build on anyone
trying to set this project up. Zone containment is a handful of lines
of ray-casting; it isn't worth the install risk for a laptop-deployed
research project. If a future contributor needs richer geometry
(zone intersection, buffering), swap this module for shapely then --
the ``Zone`` API in zones.py doesn't leak the implementation.
"""

from __future__ import annotations

Point = tuple[float, float]
Polygon = list[Point]


def point_in_polygon(point: Point, polygon: Polygon) -> bool:
    """Ray-casting point-in-polygon test.

    ``polygon`` is a list of (x, y) vertices in either winding order,
    not necessarily closed (last point need not repeat the first).
    Works in any consistent coordinate system (pixels or normalized
    0-1 both fine, as long as ``point`` uses the same one).
    """
    x, y = point
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    x1, y1 = polygon[-1]
    for x2, y2 in polygon:
        if (y1 > y) != (y2 > y):
            x_intersect = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_intersect:
                inside = not inside
        x1, y1 = x2, y2
    return inside


def polygon_area(polygon: Polygon) -> float:
    """Shoelace formula; used to sort overlapping zones by specificity."""
    n = len(polygon)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def denormalize(polygon: Polygon, width: int, height: int) -> Polygon:
    """Convert normalized (0-1) polygon coordinates to pixel coordinates."""
    return [(x * width, y * height) for x, y in polygon]


def normalize(polygon: Polygon, width: int, height: int) -> Polygon:
    """Convert pixel polygon coordinates to normalized (0-1) coordinates."""
    if width <= 0 or height <= 0:
        raise ValueError("width/height must be positive")
    return [(x / width, y / height) for x, y in polygon]


def ground_point(bbox: tuple[float, float, float, float]) -> Point:
    """Bottom-center of a bounding box -- an approximation of where a
    person is standing, which is a better zone-occupancy signal than
    the box centroid (a tall person's centroid can sit outside a zone
    their feet are inside).
    """
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, y2)
