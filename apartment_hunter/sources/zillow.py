"""Zillow: search URLs, embedded __NEXT_DATA__ results, and the page's own map response."""

import json
import re
from urllib.parse import quote

from .. import areas
from ..criteria import AMENITIES
from . import amenity_strings, deep_values, loads, longest_text, photo_keys

BASE = "https://www.zillow.com"
SITE = "zillow"
LABEL = "Zillow"
SETTLE = 6.0  # Seconds after load for the page's own map request, when the page makes one.
MANHATTAN = {"regionId": 12530, "regionType": 17}

EXTRACT_JS = "document.getElementById('__NEXT_DATA__')?.textContent ?? null"
DETAIL_JS = """(() => ({
  next: document.getElementById('__NEXT_DATA__')?.textContent ?? null,
  ldjson: [...document.querySelectorAll('script[type="application/ld+json"]')].map(s => s.textContent),
  description: document.querySelector('meta[name="description"]')?.content || null,
  text: document.body ? document.body.innerText.slice(0, 20000) : ''
}))()"""

_MONEY = re.compile(r"\$?\s*([\d,]+)")
_UNIT = re.compile(r"\s+((?:APT|UNIT|#|PH|FL|STE)\b.*|#.*)$", re.I)


def is_search_response(url):
    return "async-create-search-page-state" in url or "GetSearchPageState" in url


def photo_url(key):
    return f"https://photos.zillowstatic.com/fp/{key}-cc_ft_768.webp"


def money(text):
    if isinstance(text, (int, float)):
        return int(text)
    match = _MONEY.search(text or "")
    return int(match.group(1).replace(",", "")) if match and match.group(1).replace(",", "") else None


def bounds(area_ids):
    """(south, west, north, east) around the selected areas."""
    table = areas.load()
    boxes = [table[a].box for a in area_ids if a in table and table[a].box]
    if not boxes:
        return (40.68, -74.03, 40.88, -73.90)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def unverified(limits):
    """Must-haves that the Zillow search URL cannot express (for example, a doorman)."""
    return [AMENITIES[a]["label"] for a in limits.get("must_have") or [] if not AMENITIES[a]["zillow"]]


def search_url(limits):
    selected = [int(a) for a in limits.get("areas") or []]
    south, west, north, east = bounds(selected)
    state = {
        "fr": {"value": True}, "fsba": {"value": False}, "fsbo": {"value": False}, "nc": {"value": False},
        "cmsn": {"value": False}, "auc": {"value": False}, "fore": {"value": False},
        "sort": {"value": "days"},
    }
    low, high = limits.get("price_min") or None, limits.get("price_max") or None
    if low or high:
        state["mp"] = {"min": low, "max": high}
    beds_high = limits.get("beds_max")
    state["beds"] = {"min": limits.get("beds_min") or None, "max": beds_high if beds_high is not None and beds_high < 4
                     else None}
    if (limits.get("baths_min") or 0) > 1:
        state["baths"] = {"min": limits["baths_min"]}
    if limits.get("sqft_min"):
        state["sqft"] = {"min": limits["sqft_min"]}
    for need in limits.get("must_have") or []:
        code = AMENITIES[need]["zillow"]
        if code:
            state[code] = {"value": True}
    query = {
        "pagination": {},
        "isMapVisible": True,
        "isListVisible": True,
        "mapBounds": {"west": round(west, 5), "east": round(east, 5), "south": round(south, 5),
                      "north": round(north, 5)},
        "filterState": state,
    }
    path = "/homes/for_rent/"
    if selected == [100]:
        query["regionSelection"] = [MANHATTAN]
        path = "/manhattan-new-york-ny/rentals/"
    return BASE + path + "?searchQueryState=" + quote(json.dumps(query, separators=(",", ":")), safe="")


def _photos(result):
    carousel = (result.get("carouselPhotosComposable") or {}).get("photoData") or []
    keys = [p["photoKey"] for p in carousel if isinstance(p, dict) and p.get("photoKey")]
    if not keys:
        keys = photo_keys(result.get("imgSrc") or "")
    return [photo_url(k) for k in keys]


def _absolute(url):
    if not url:
        return None
    return url if url.startswith("http") else BASE + url


def _split_unit(street):
    if not street:
        return None, None
    match = _UNIT.search(street)
    if not match:
        return street.strip(), None
    return street[:match.start()].strip(), match.group(1).strip()


def normalize(result):
    """One listing for a unit; one building group per bedroom count for a building."""
    point = result.get("latLong") or {}
    lat, lon = point.get("latitude"), point.get("longitude")
    photos = _photos(result)
    url = _absolute(result.get("detailUrl"))
    if result.get("isBuilding"):
        key = (url or "").rstrip("/").split("/")[-1] or str(result.get("lotId") or result.get("zpid"))
        street = (result.get("address") or "").split(",")[0].strip() or None
        name = result.get("buildingName") or street
        out = []
        for unit in result.get("units") or []:
            price, beds = money(unit.get("price")), unit.get("beds")
            if unit.get("roomForRent") or price is None or beds is None or not str(beds).isdigit():
                continue
            out.append({
                "id": f"zb:{key}:{int(beds)}", "source": SITE, "kind": "building_group",
                "url": url, "urls": {"zillow": url}, "title": name, "building_name": result.get("buildingName"),
                "street": street, "unit": None, "zip": result.get("addressZipcode"), "lat": lat, "lon": lon,
                "area_id": None, "area_name": None,
                "price": price, "price_is_from": True, "net_effective": None, "months_free": None,
                "lease_months": None, "beds": int(beds), "baths": None, "sqft": None, "available_at": None,
                "building_type": "BUILDING", "is_new_development": None, "furnished": None,
                "photos": photos, "photo_count": len(photos), "units_available": result.get("availabilityCount"),
                "status": result.get("statusType"), "broker": None, "detail_level": "full",
            })
        return out
    home = (result.get("hdpData") or {}).get("homeInfo") or {}
    price = result.get("unformattedPrice") or home.get("price") or money(result.get("price"))
    street, unit = _split_unit(result.get("addressStreet") or home.get("streetAddress"))
    unit = home.get("unit") or unit
    zpid = result.get("zpid") or home.get("zpid")
    if not zpid or not price:
        return []
    return [{
        "id": f"z:{zpid}", "source": SITE, "kind": "unit", "url": url, "urls": {"zillow": url},
        "title": " ".join(x for x in (street, unit) if x) or result.get("address"),
        "building_name": result.get("buildingName"), "street": street, "unit": unit,
        "zip": result.get("addressZipcode") or home.get("zipcode"), "lat": lat or home.get("latitude"),
        "lon": lon or home.get("longitude"), "area_id": None, "area_name": None,
        "price": int(price), "price_is_from": "+" in str(result.get("price") or ""), "net_effective": None,
        "months_free": None, "lease_months": None,
        "beds": result.get("beds") if result.get("beds") is not None else home.get("bedrooms"),
        "baths": result.get("baths") if result.get("baths") is not None else home.get("bathrooms"),
        "sqft": result.get("area") or home.get("livingArea") or None, "available_at": None,
        "building_type": home.get("homeType"), "is_new_development": None, "furnished": None,
        "photos": photos, "photo_count": len(photos), "days_on_market": home.get("daysOnZillow"),
        "status": result.get("statusType"), "broker": None, "detail_level": "full",
    }]


def _collect(search_results):
    listings = {}
    for key in ("listResults", "mapResults"):
        for result in search_results.get(key) or []:
            for listing in normalize(result):
                listings.setdefault(listing["id"], listing)
    return list(listings.values())


def _total(state):
    for path in (("cat1", "searchList", "totalResultCount"), ("categoryTotals", "cat1", "totalResultCount")):
        value = state
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, int):
            return value
    return None


def parse_page(text):
    data = loads(text)
    if not isinstance(data, dict):
        return {"listings": [], "total": None}
    state = ((data.get("props") or {}).get("pageProps") or {}).get("searchPageState") or {}
    results = (state.get("cat1") or {}).get("searchResults") or {}
    return {"listings": _collect(results), "total": _total(state)}


def parse_map(body):
    data = loads(body)
    if not isinstance(data, dict):
        return {"listings": [], "total": None}
    results = (data.get("cat1") or {}).get("searchResults") or {}
    return {"listings": _collect(results), "total": _total(data)}


def _expand_json_strings(obj):
    """Zillow stores parts of its page state as JSON strings; parse those in place."""
    for _, value in deep_values(obj, lambda k: k in ("gdpClientCache", "apiCache")):
        if isinstance(value, str) and value[:1] in "{[":
            yield loads(value)


def parse_detail(extracted):
    extracted = extracted or {}
    raw = extracted.get("next") or ""
    data = loads(raw) or {}
    trees = [data, *[t for t in _expand_json_strings(data) if t]]
    blobs = [loads(x) for x in extracted.get("ldjson") or []]
    description = None
    for tree in trees + [blobs]:
        description = description or longest_text(tree, lambda k: k in ("description", "buildingDescription"))
    amenities = []
    for tree in trees:
        amenities = amenities or amenity_strings(tree)
    return {
        "description": description or extracted.get("description"),
        "photos": [photo_url(k) for k in photo_keys(raw + json.dumps(blobs))],
        "amenities": amenities,
        "text": (extracted.get("text") or "")[:6000],
    }
