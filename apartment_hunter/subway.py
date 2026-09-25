"""MTA subway stops (NY Open Data) and walking distance estimates."""

import json
from dataclasses import dataclass
from functools import lru_cache

from .config import DATA
from .geo import haversine_m

WALK_FACTOR = 1.25  # Street grid detour over straight-line distance.
WALK_M_PER_MIN = 80
BOX_DEG = 0.03  # About 3 km: nothing farther matters for a walk.


@dataclass(frozen=True)
class Station:
    name: str
    lines: tuple
    lat: float
    lon: float
    borough: str
    complex_id: str


@lru_cache(maxsize=1)
def load():
    return [
        Station(s["name"], tuple(s["lines"]), s["lat"], s["lon"], s["borough"], s["complex_id"])
        for s in json.loads((DATA / "subway_stations.json").read_text())
    ]


def _near(lat, lon):
    return [s for s in load() if abs(s.lat - lat) < BOX_DEG and abs(s.lon - lon) < BOX_DEG * 1.3] or load()


def nearest(lat, lon):
    """(station, straight-line meters) of the closest stop."""
    return min(((s, haversine_m(lat, lon, s.lat, s.lon)) for s in _near(lat, lon)), key=lambda x: x[1])


def lines_within(lat, lon, meters):
    lines = {line for s in _near(lat, lon) if haversine_m(lat, lon, s.lat, s.lon) <= meters for line in s.lines}
    return sorted(lines, key=lambda x: (len(x), x))


def walk_minutes(meters):
    return meters * WALK_FACTOR / WALK_M_PER_MIN


def meters_for_walk(minutes):
    return minutes * WALK_M_PER_MIN / WALK_FACTOR
