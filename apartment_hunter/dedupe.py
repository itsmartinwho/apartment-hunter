"""Merge the same apartment listed on both sites. StreetEasy fields win; Zillow fills gaps."""

import re

from .geo import haversine_m

WORDS = {"street": "st", "avenue": "ave", "av": "ave", "east": "e", "west": "w", "north": "n", "south": "s",
         "place": "pl", "boulevard": "blvd", "drive": "dr", "road": "rd", "lane": "ln", "terrace": "ter",
         "parkway": "pkwy", "square": "sq", "plaza": "plz"}
NEAR_M = 30
PRICE_TOLERANCE = 0.03


def street_key(street):
    tokens = re.sub(r"[^a-z0-9 ]", " ", (street or "").lower()).split()
    out = [re.sub(r"^(\d+)(st|nd|rd|th)$", r"\1", WORDS.get(t, t)) for t in tokens]
    return " ".join(out)


def unit_key(unit):
    return re.sub(r"^(APT|UNIT|NO|APARTMENT)", "", re.sub(r"[^A-Z0-9]", "", (unit or "").upper()))


def _merge(primary, other):
    merged = dict(primary)
    for key, value in other.items():
        if merged.get(key) in (None, "", []) and value not in (None, "", []):
            merged[key] = value
    if len(other.get("photos") or []) > len(primary.get("photos") or []):
        merged["photos"], merged["photo_count"] = other["photos"], other.get("photo_count")
    merged["urls"] = {**(other.get("urls") or {}), **{k: v for k, v in (primary.get("urls") or {}).items() if v}}
    merged["sources"] = sorted({primary["source"], other["source"]})
    merged["merged_ids"] = sorted({*primary.get("merged_ids", [primary["id"]]), other["id"]})
    return merged


def _same_place(a, b):
    if a.get("beds") != b.get("beds") or not all(isinstance(x.get(k), (int, float)) for x in (a, b)
                                                   for k in ("lat", "lon", "price")):
        return False
    close = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"]) <= NEAR_M
    return close and abs(a["price"] - b["price"]) <= PRICE_TOLERANCE * max(a["price"], b["price"])


def merge(listings):
    """One entry per apartment. Building groups are never merged with units."""
    streeteasy = [x for x in listings if x["source"] == "streeteasy"]
    others = [x for x in listings if x["source"] != "streeteasy"]
    by_key = {}
    for listing in streeteasy:
        key = (street_key(listing.get("street")), unit_key(listing.get("unit")))
        if all(key):
            by_key[key] = listing["id"]
    result = {x["id"]: x for x in streeteasy}
    for listing in others:
        target = None
        if listing.get("kind") == "unit":
            key = (street_key(listing.get("street")), unit_key(listing.get("unit")))
            target = by_key.get(key) if all(key) else None
            if target is None:
                # Two different unit numbers are two apartments, even in the same building at the same rent.
                target = next((x["id"] for x in streeteasy if _same_place(x, listing)
                               and not (unit_key(x.get("unit")) and unit_key(listing.get("unit")))), None)
        if target:
            result[target] = _merge(result[target], listing)
        else:
            result[listing["id"]] = listing
    return list(result.values())
