"""StreetEasy's area taxonomy: ids, names, parents, and boundary polygons. Also the default tiers."""

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from .config import DATA
from .geo import bbox, decode_polyline, point_in_polygon

NYC = {"Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"}

# Manhattan plus close Brooklyn: Greenpoint, Williamsburg, Downtown Brooklyn, Fort Greene, Brooklyn Heights,
# Boerum Hill, DUMBO, Park Slope, Gowanus, Carroll Gardens, Cobble Hill, Prospect Heights,
# Columbia St Waterfront, Clinton Hill.
DEFAULT_SEARCH_AREAS = [100, 301, 302, 303, 304, 305, 306, 307, 319, 320, 321, 322, 326, 328, 364]

# Area id -> tier (1 best, 4 weakest). An area without an entry takes its nearest ancestor's tier; the default is 3.
DEFAULT_TIERS = {
    # Tier 1: the most desirable residential neighborhoods downtown.
    "157": 1, "116": 1, "107": 1, "105": 1, "115": 1, "158": 1, "162": 1, "113": 1,
    # Tier 2: Upper West Side, Upper East Side, and the best close Brooklyn neighborhoods.
    "135": 2, "139": 2, "117": 2, "108": 2, "112": 2, "121": 2, "159": 2,
    "305": 2, "307": 2, "322": 2, "321": 2, "306": 2, "319": 2, "302": 2, "304": 2, "301": 2,
    # Tier 3: Midtown, the Financial District, the Lower East Side, and the rest of close Brooklyn.
    "119": 3, "104": 3, "103": 3, "109": 3, "110": 3, "106": 3, "142": 3, "138": 3, "147": 3,
    "364": 3, "326": 3, "303": 3, "320": 3, "328": 3, "373": 3,
    # Tier 4: Upper Manhattan, Roosevelt Island, and other boroughs.
    "144": 4, "101": 4, "300": 4, "200": 4, "400": 4, "500": 4,
}


@dataclass(frozen=True)
class Area:
    id: int
    name: str
    short: str
    level: int
    parent_id: int
    borough: str
    polygon: tuple
    box: tuple | None


def _key(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


@lru_cache(maxsize=1)
def load():
    table = {}
    for a in json.loads((DATA / "streeteasy_areas.json").read_text()):
        polygon = tuple(decode_polyline(a["boundary"])) if a.get("boundary") else ()
        table[a["id"]] = Area(
            a["id"], a["name"], a["short"], a["level"], a["parent_id"], a["borough"], polygon,
            bbox(polygon) if len(polygon) >= 3 else None,
        )
    return table


@lru_cache(maxsize=1)
def _names():
    index = {}
    for area in sorted(load().values(), key=lambda a: -a.level):
        index[_key(area.name)] = area
        index.setdefault(_key(area.short), area)
    return index


def by_name(name):
    return _names().get(_key(name)) if name else None


def ancestors(area_id):
    table = load()
    out, current = [], table.get(area_id)
    while current and current.parent_id and current.parent_id in table:
        out.append(current.parent_id)
        current = table[current.parent_id]
    return out


@lru_cache(maxsize=None)
def descendants(area_id):
    children = {}
    for area in load().values():
        children.setdefault(area.parent_id, []).append(area.id)
    out, stack = set(), [area_id]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in out:
                out.add(child)
                stack.append(child)
    return frozenset(out)


def locate(lat, lon):
    """The deepest NYC area whose boundary contains the point, or None."""
    best = None
    for area in load().values():
        if area.box is None or area.borough not in NYC:
            continue
        south, west, north, east = area.box
        if not (south <= lat <= north and west <= lon <= east) or not point_in_polygon(lat, lon, area.polygon):
            continue
        size = (north - south) * (east - west)
        if best is None or (area.level, -size) > (best[0].level, -best[1]):
            best = (area, size)
    return best[0] if best else None


def tier_for(area_id, tiers):
    """The user's tier for an area; inherited from the nearest ancestor with a tier. Default 3."""
    if area_id is None:
        return 3
    for candidate in [area_id, *ancestors(area_id)]:
        value = tiers.get(str(candidate))
        if value in (1, 2, 3, 4):
            return value
    return 3


def borough(area_id):
    area = load().get(area_id)
    return area.borough if area else None


def in_selection(area_id, selected):
    """True when the area is one of the selected areas or lies inside one."""
    if area_id is None:
        return False
    chain = {area_id, *ancestors(area_id)}
    return any(int(s) in chain for s in selected)
