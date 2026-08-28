"""Zone definitions: user-drawn polygons overlaid on the camera image.

Zones are stored in normalized (0-1) coordinates so a zone drawn on a
640x480 snapshot still lines up correctly if the camera later opens at
a different resolution. Persisted as plain JSON (``data/zones.json``)
rather than folded into config.yaml because the dashboard rewrites
this file interactively every time someone adds or deletes a zone --
JSON round-trips cleanly; YAML with hand-written comments does not.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Optional

from .geometry import Point, Polygon, point_in_polygon, polygon_area

VALID_KINDS = ("restricted", "normal")


@dataclasses.dataclass
class Zone:
    name: str
    kind: str  # "restricted" | "normal"
    polygon: Polygon  # normalized (0-1) coordinates

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            raise ValueError(f"zone kind must be one of {VALID_KINDS}, got {self.kind!r}")
        if len(self.polygon) < 3:
            raise ValueError(f"zone '{self.name}' needs at least 3 points")

    def contains(self, point: Point) -> bool:
        return point_in_polygon(point, self.polygon)

    def area(self) -> float:
        return polygon_area(self.polygon)

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "polygon": [list(p) for p in self.polygon]}

    @classmethod
    def from_dict(cls, d: dict) -> "Zone":
        return cls(name=d["name"], kind=d["kind"], polygon=[tuple(p) for p in d["polygon"]])


class ZoneManager:
    """Owns the set of configured zones and answers "what zone is this
    point in" queries. When zones overlap (a restricted zone nested
    inside a larger normal area, per the brief's own diagram), the
    smallest containing zone wins -- that's the one whose boundary the
    person actually crossed most recently.
    """

    def __init__(self, zones: Optional[list[Zone]] = None, path: Optional[str | Path] = None):
        self.zones: list[Zone] = zones or []
        self.path = Path(path) if path else None

    # -- persistence --
    @classmethod
    def load(cls, path: str | Path) -> "ZoneManager":
        path = Path(path)
        if not path.exists():
            return cls(zones=[], path=path)
        raw = json.loads(path.read_text() or "[]")
        return cls(zones=[Zone.from_dict(z) for z in raw], path=path)

    def save(self, path: Optional[str | Path] = None) -> None:
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("no path configured for this ZoneManager")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps([z.to_dict() for z in self.zones], indent=2))

    # -- CRUD --
    def add(self, zone: Zone) -> None:
        self.remove(zone.name)
        self.zones.append(zone)

    def remove(self, name: str) -> None:
        self.zones = [z for z in self.zones if z.name != name]

    def get(self, name: str) -> Optional[Zone]:
        return next((z for z in self.zones if z.name == name), None)

    # -- queries --
    def zone_for_point(self, point: Point) -> Optional[Zone]:
        matches = [z for z in self.zones if z.contains(point)]
        if not matches:
            return None
        # Smallest area = most specific (a restricted zone nested in a normal one).
        return min(matches, key=lambda z: z.area())

    def restricted_zones(self) -> list[Zone]:
        return [z for z in self.zones if z.kind == "restricted"]
