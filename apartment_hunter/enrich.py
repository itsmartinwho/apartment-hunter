"""Deterministic features added in code: subway access, neighborhood, floor, and a size estimate."""

import re

from . import areas, subway

SQFT_BY_BEDS = {0: 450, 1: 650, 2: 900, 3: 1200, 4: 1500}
LINES_WALK_MIN = 8
MAX_FLOOR = 110

_PREFIX = re.compile(r"^(#|APT\.?|APARTMENT|UNIT|NO\.?|SUITE|STE\.?)\s*", re.I)


def parse_floor(unit):
    """(floor, is_penthouse) from a unit label. None when the label does not clearly encode a floor."""
    if not unit:
        return None, False
    s = unit.strip().upper()
    for _ in range(2):
        s = _PREFIX.sub("", s).strip()
    s = s.lstrip("#-/ ").strip()
    if s.startswith("PH") or "PENTHOUSE" in s:
        return None, True
    if s in {"GARDEN", "GRDN", "GROUND", "GF", "G/F", "BSMT", "BASEMENT", "LL", "LOWER LEVEL", "CELLAR"}:
        return 0, False
    patterns = [
        (r"(\d{1,2})\s*-?\s*[A-Z]{1,2}", lambda m: int(m.group(1))),  # 11C, 9B, 28H, 11S
        (r"(\d{3,4})", lambda m: int(m.group(1)[:-2])),  # 801 -> 8, 2406 -> 24
        (r"[A-Z](\d{1,2})[A-Z]", lambda m: int(m.group(1))),  # S9C -> 9
        (r"(\d{1,2})(?:ST|ND|RD|TH)?\s*(?:FL|FLR|FLOOR)", lambda m: int(m.group(1))),  # 4th Floor
    ]
    for pattern, floor in patterns:
        match = re.fullmatch(pattern, s)
        if match:
            value = floor(match)
            return (value, False) if 0 < value <= MAX_FLOOR else (None, False)
    return None, False


def estimate_sqft(beds, baths):
    base = SQFT_BY_BEDS.get(min(int(beds), 4), 650) if beds is not None else 650
    return base + max(0, int(round(((baths or 1) - 1) * 2))) * 40


def enrich(listing):
    """Add subway, lines nearby, area, borough, floor, and size estimate. Missing inputs give None, not errors."""
    lat, lon = listing.get("lat"), listing.get("lon")
    has_point = isinstance(lat, (int, float)) and isinstance(lon, (int, float))
    if has_point:
        station, meters = subway.nearest(lat, lon)
        listing["subway"] = {
            "station": station.name,
            "lines": list(station.lines),
            "distance_m": round(meters),
            "walk_min": round(subway.walk_minutes(meters), 1),
        }
        listing["lines_nearby"] = subway.lines_within(lat, lon, subway.meters_for_walk(LINES_WALK_MIN))
    else:
        listing["subway"], listing["lines_nearby"] = None, []
    area = None
    if listing.get("area_id") in areas.load():
        area = areas.load()[listing["area_id"]]
    if area is None and has_point:
        area = areas.locate(lat, lon)
    if area is None and listing.get("area_name"):
        area = areas.by_name(listing["area_name"])
    listing["area_id"] = area.id if area else None
    listing["area_name"] = area.name if area else listing.get("area_name")
    listing["borough"] = area.borough if area else listing.get("borough")
    if listing.get("floor_source") != "vision":
        floor, penthouse = parse_floor(listing.get("unit"))
        listing["floor"], listing["is_penthouse"] = floor, penthouse
        listing["floor_source"] = "unit" if floor is not None or penthouse else None
    estimate = estimate_sqft(listing.get("beds"), listing.get("baths"))
    listing["sqft_estimated"] = None if listing.get("sqft") else estimate
    return listing
