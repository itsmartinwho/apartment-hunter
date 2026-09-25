"""StreetEasy: search URLs, embedded page data, and the page's own map response (searchRentals, up to 500)."""

import json
from datetime import date

from .. import areas, rsc
from ..criteria import AMENITIES
from . import amenity_strings, loads, longest_text, photo_keys

BASE = "https://streeteasy.com"
SITE = "streeteasy"
LABEL = "StreetEasy"
SETTLE = 5.0  # Seconds after load for the page's own map request (it usually starts before the load ends).

# Joins the Next.js flight chunks. Returns null on pages without flight data (for example, a human check).
EXTRACT_JS = "self.__next_f ? self.__next_f.filter(x => x[0] === 1).map(x => x[1]).join('') : null"
DETAIL_JS = """(() => ({
  flight: self.__next_f ? self.__next_f.filter(x => x[0] === 1).map(x => x[1]).join('') : null,
  ldjson: [...document.querySelectorAll('script[type="application/ld+json"]')].map(s => s.textContent),
  description: document.querySelector('meta[name="description"]')?.content || null,
  text: document.body ? document.body.innerText.slice(0, 20000) : ''
}))()"""


def is_search_response(url):
    return url.rstrip("/") == "https://api-v6.streeteasy.com"


def photo_url(key):
    return f"https://photos.zillowstatic.com/fp/{key}-se_large_800_400.webp"


def _beds(low, high):
    if high is not None and high < 4:
        if low == high:
            return f"beds:{low}"
        return f"beds<={high}" if not low else f"beds:{low}-{high}"
    return f"beds>={low}" if low else None


def search_url(limits):
    """The same path the StreetEasy site builds, in its own filter order."""
    low, high = limits.get("price_min") or 0, limits.get("price_max") or 0
    baths = limits.get("baths_min") or 0
    codes = [AMENITIES[a]["streeteasy"] for a in limits.get("must_have") or [] if AMENITIES[a]["streeteasy"]]
    by = limits.get("move_in_by")
    parts = [  # Active listings are the default, so the site's own URLs carry no status filter.
        f"price:{low or ''}-{high or ''}" if (low or high) else None,
        f"sqft>={limits['sqft_min']}" if limits.get("sqft_min") else None,
        "area:" + ",".join(str(a) for a in sorted(set(limits["areas"])) if a) if limits.get("areas") else None,
        _beds(limits.get("beds_min") or 0, limits.get("beds_max")),
        f"baths>={int(baths) if float(baths).is_integer() else baths}" if baths > 1 else None,
        "amenities:" + ",".join(codes) if codes else None,
        "pets:allowed" if "pets" in (limits.get("must_have") or []) else None,
        "available:" + date.fromisoformat(by).strftime("%Y%m%d") if by else None,
    ]
    path = "|".join(p for p in parts if p).replace("|", "%7C").replace(">", "%3E").replace("<", "%3C")
    return f"{BASE}/for-rent/nyc/{path}?sort_by=listed_desc"


def normalize(node, detail_level="full"):
    photos = [photo_url(p["key"]) for p in node.get("photos") or [] if isinstance(p, dict) and p.get("key")]
    lead = ((node.get("leadMedia") or {}).get("photo") or {}).get("key")
    if not photos and lead:
        photos = [photo_url(lead)]
    point = node.get("geoPoint") or {}
    price = node.get("price")
    net = node.get("netEffectivePrice")
    unit = node.get("displayUnit") or node.get("unit")
    area = areas.by_name(node.get("areaName"))
    url = BASE + node["urlPath"] if node.get("urlPath") else None
    half = node.get("halfBathroomCount") or 0
    full = node.get("fullBathroomCount")
    return {
        "id": f"se:{node['id']}",
        "source": SITE,
        "kind": "unit",
        "url": url,
        "urls": {"streeteasy": url},
        "title": " ".join(x for x in (node.get("street"), unit) if x),
        "street": node.get("street"),
        "unit": unit,
        "zip": node.get("zipCode"),
        "lat": point.get("latitude"),
        "lon": point.get("longitude"),
        "area_id": area.id if area else None,
        "area_name": node.get("areaName"),
        "price": price,
        "price_is_from": False,
        "net_effective": net if isinstance(net, (int, float)) and isinstance(price, (int, float)) and 0 < net < price
        else None,
        "months_free": node.get("monthsFree"),
        "lease_months": node.get("leaseTermMonths"),
        "beds": node.get("bedroomCount"),
        "baths": (full or 0) + 0.5 * half if full is not None else None,
        "sqft": node.get("livingAreaSize") or None,
        "available_at": node.get("availableAt"),
        "building_type": node.get("buildingType"),
        "is_new_development": node.get("isNewDevelopment"),
        "furnished": node.get("furnished"),
        "photos": photos,
        "photo_count": len(photos) if detail_level == "full" else None,
        "status": node.get("status"),
        "broker": node.get("sourceGroupLabel"),
        "detail_level": detail_level,
    }


def _usable(node):
    return isinstance(node, dict) and node.get("id") and node.get("status", "ACTIVE") in {"ACTIVE", "PREVIEW",
                                                                                          "COMING_SOON"}


def parse_page(flight):
    """Listings (14 per page) and the total count from a search page's flight data."""
    if not flight:
        return {"listings": [], "total": None}
    data = list(rsc.parse(flight).values())
    edges = rsc.find(data, lambda o: str(o.get("__typename", "")).endswith("RentalEdge"))
    listings = {}
    for edge in edges:
        node = edge.get("node")
        if _usable(node):
            listings.setdefault(str(node["id"]), normalize(node, "full"))
    totals = [o["totalCount"] for o in rsc.find(data, lambda o: "totalCount" in o and "edges" in o)
              if isinstance(o.get("totalCount"), int)]
    return {"listings": list(listings.values()), "total": max(totals) if totals else None}


def parse_map(body):
    """Listings from the page's own searchRentals map response."""
    payload = loads(body)
    data = payload.get("data") if isinstance(payload, dict) else None
    result = data.get("searchRentals") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        return {"listings": [], "total": None}
    listings = {}
    for edge in result.get("edges") or []:
        node = (edge or {}).get("node")
        if _usable(node):
            listings.setdefault(str(node["id"]), normalize(node, "map"))
    return {"listings": list(listings.values()), "total": result.get("totalCount")}


def parse_detail(extracted):
    """Description, all photos, and amenities from a listing page. Defensive: the page format is not fixed."""
    extracted = extracted or {}
    blobs = [loads(x) for x in extracted.get("ldjson") or []]
    flight = extracted.get("flight") or ""
    tree = list(rsc.parse(flight).values()) if flight else []
    description = longest_text(tree, lambda k: k == "description") or longest_text(
        blobs, lambda k: k == "description") or extracted.get("description")
    keys = photo_keys(flight + json.dumps(blobs))
    amenities = amenity_strings(tree) or amenity_strings(blobs)
    return {
        "description": description,
        "photos": [photo_url(k) for k in keys],
        "amenities": amenities,
        "text": (extracted.get("text") or "")[:6000],
    }
