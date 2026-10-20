"""Write the two synthetic search pages in tests/fixtures.

Nothing in them was captured from StreetEasy or Zillow. The addresses, prices, ids and photo keys are made up (the
neighborhood names are the only real names, because the readers look them up), and the pages carry no URLs, people,
phone numbers, visitor ids or keys. They hold only the structure and fields the readers use
(sources/streeteasy.py, sources/zillow.py). Real captures never go in this repo: both sites forbid scraping and
redistributing their pages, and the pages carry visitor ids and third-party keys.

uv run python scripts/build_sample_fixtures.py

tests/test_fixture_hygiene.py fails when a fixture differs from this script's output, so change the fixtures here.
"""

import itertools
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
FLIGHT = "streeteasy_search_flight.txt"
NEXT_DATA = "zillow_search_next_data.json"

STREETEASY_TOTAL = 1500
ZILLOW_TOTAL = 2500


def photo_keys(tag):
    """Made-up photo keys in the shape the photo CDN uses (32 hex characters): a tag, then a counter.

    They are plainly not real hashes, so no scanner takes them for secrets and none can match a real photo.
    """
    counter = itertools.count(1)
    return lambda: f"{tag}{next(counter):030x}"


# --- StreetEasy: Next.js flight data -------------------------------------------------------------------------------

# Listings: (id, area, beds, full baths, half baths, price, net effective, months free, lease months, sqft, available,
# street, unit, zip, lat, lon, url path, broker, new development, photos, edge type, status)
STREETEASY = [
    ("9100001", "Lower East Side", 1, 1, 0, 4950, 4538, 1, 12, 0, "2026-11-01", "100 Sample Street", "#401",
     "10002", 40.7153, -73.9855, "/building/sample-house/401", "Sample Realty A", False, 3, "Featured", "ACTIVE"),
    ("9100002", "Central Harlem", 2, 2, 0, 3995, 3662, 1, 13, 0, "2026-11-15", "250 Example Avenue", "#12C",
     "10027", 40.8113, -73.9496, "/building/example-court/12c", "Sample Realty B", True, 4, "Organic", "ACTIVE"),
    ("9100003", "Chelsea", 1, 1, 0, 5800, 0, 0, 12, 0, "2026-10-25", "75 Mock Place", "#6F",
     "10011", 40.7448, -74.0006, "/building/mock-place/6f", "Sample Realty A", False, 3, "Organic", "ACTIVE"),
    ("9100004", "Upper West Side", 1, 1, 1, 5200, 0, 0, 12, 713, "2026-12-01", "310 Example Drive", "#3B",
     "10024", 40.7871, -73.9754, "/building/example-drive/3b", "Sample Realty C", False, 5, "Organic", "ACTIVE"),
    ("9100005", "East Village", 0, 1, 0, 3400, 0, 0, 12, 400, "2026-11-10", "18 Sample Avenue", "#2R",
     "10003", 40.7265, -73.9815, "/building/sample-avenue/2r", "Sample Realty B", False, 3, "Organic", "ACTIVE"),
    ("9100006", "Williamsburg", 2, 1, 0, 6700, 0, 0, 12, 0, "2026-11-01", "5 Mock Street", "#8A",
     "11211", 40.7142, -73.9610, "/building/mock-street/8a", "Sample Realty C", True, 4, "Sponsored", "ACTIVE"),
    # Off the market: the reader skips it.
    ("9100007", "Chelsea", 1, 1, 0, 4100, 0, 0, 12, 0, "2026-10-20", "9 Mock Place", "#1A",
     "10011", 40.7440, -74.0010, "/building/mock-place/1a", "Sample Realty A", False, 2, "Organic", "RENTED"),
]


class Flight:
    """Rows of flight data: "<hex id>:<payload>" lines and length-prefixed text rows."""

    def __init__(self):
        self.parts, self.next_id = [], 0x10

    def row(self, payload, rid=None):
        if rid is None:
            rid, self.next_id = format(self.next_id, "x"), self.next_id + 1
        self.parts.append(f"{rid}:{payload}\n")
        return rid

    def text(self, value):
        """A text row: the UTF-8 byte length in hex, then the text; the next row follows at once."""
        rid, self.next_id = format(self.next_id, "x"), self.next_id + 1
        self.parts.append(f"{rid}:T{len(value.encode('utf-8')):x},{value}")
        return rid

    def build(self):
        return "".join(self.parts)


def dump(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def streeteasy_flight():
    flight, next_key = Flight(), photo_keys("5e")
    flight.row('HL["/static/css/sample.css","style"]', "1")
    flight.row('I[1,[],""]', "2")
    flight.row(dump(["searchQuery", "for-rent/manhattan/price%3A-7500%7Cbeds%3E%3D1", "c"]), "3")
    flight.text(dump({"summary": "Sample rentals – café district"}))
    edges = []
    for (listing_id, area, beds, full, half, price, net, free, lease, sqft, available, street, unit, zipcode, lat,
         lon, path, broker, new, photos, kind, status) in STREETEASY:
        shots = [flight.row(dump({"description": f"{street} image {n} of {photos}",
                                  "key": next_key()})) for n in range(1, photos + 1)]
        shot_list = flight.row(dump([f"${s}" for s in shots]))
        node = flight.row(dump({
            "id": listing_id, "areaName": area, "availableAt": available, "bedroomCount": beds,
            "buildingType": "RENTAL", "fullBathroomCount": full, "furnished": False,
            "geoPoint": {"latitude": lat, "longitude": lon}, "halfBathroomCount": half, "isNewDevelopment": new,
            "leaseTermMonths": lease, "livingAreaSize": sqft, "monthsFree": free, "netEffectivePrice": net,
            "photos": f"${shot_list}", "price": price, "sourceGroupLabel": broker, "status": status,
            "street": street, "displayUnit": unit, "unit": unit, "urlPath": path, "zipCode": zipcode,
        }))
        edge = {"node": f"${node}", "__typename": f"{kind}RentalEdge"}
        if kind != "Sponsored":
            edge.update(amenitiesMatch=None, matchedAmenities=None, missingAmenities=None)
        edges.append(flight.row(dump(edge)))
    edge_list = flight.row(dump([f"${e}" for e in edges]))
    flight.row(dump(["$", "$L2", None, {
        "listingData": {
            "search": {"criteria": "area:100|beds>=1|price:-7500|status:open"},
            "totalCount": STREETEASY_TOTAL, "edges": f"${edge_list}",
            "pageInfo": {"currentPage": 1, "hasNextPage": True, "hasPreviousPage": False},
        },
        "listingType": "rentals", "userId": "$undefined",
    }]), "a")
    return flight.build()


# --- Zillow: __NEXT_DATA__ ------------------------------------------------------------------------------------------

# Buildings: (key, name, street, zip, lat, lon, [(price text, beds)], photos). A unit marked as a room for rent, or
# with no price, is skipped by the reader.
BUILDINGS = [
    ("Smp001", "Sample Tower", "10 Example Plaza", "10001", 40.7502, -73.9972,
     [("$3,950+", "0"), ("$5,200+", "1")], 4),
    ("Smp002", "The Example", "40 Mock Avenue", "10010", 40.7390, -73.9840,
     [("$4,480+", "1"), ("$6,900+", "2"), ("$900+", "1", "room"), (None, "3")], 3),
    ("Smp003", "Example Lofts", "22 Sample Street", "10013", 40.7205, -74.0050,
     [("$3,700+", "0"), ("$4,900+", "1"), ("$6,300+", "2"), ("$8,800+", "3")], 3),
    ("Smp004", "Sample Court", "7 Mock Boulevard", "11201", 40.6925, -73.9895, [("$5,950+", "2")], 2),
    ("Smp005", "Mock Residences", "60 Example Terrace", "10025", 40.7960, -73.9700,
     [("$4,250+", "1"), ("$5,600+", "2")], 3),
    ("Smp006", "Sample Place", "3 Mock Lane", "10002", 40.7190, -73.9880, [], 2),
]

# Units: (zpid, street, unit, zip, lat, lon, price, beds, baths, sqft, home type, days on market, photos)
UNITS = [
    ("900000001", "123 Example Ave", "Apt 7B", "10022", 40.7587, -73.9628, 4745, 1, 1, 608, "APARTMENT", 3, 3),
    ("900000002", "45 Sample Pl", "#3F", "10014", 40.7335, -74.0030, 6150, 2, 2, 900, "APARTMENT", 12, 4),
    ("900000003", "200 Mock St", "Unit 2R", "10009", 40.7250, -73.9780, 3300, 0, 1, 400, "APARTMENT", 1, 0),
    ("900000004", "88 Example Blvd", "Apt 21A", "10023", 40.7780, -73.9810, 12500, 3, 3, 1800, "CONDO", 30, 3),
]


def photos_block(next_key, count):
    keys = [{"photoKey": next_key()} for _ in range(count)]
    return {"photoData": keys} if keys else None


def zillow_building(next_key, key, name, street, zipcode, lat, lon, units, photos):
    entries = []
    for unit in units:
        price, beds, *flags = unit
        entries.append({"price": price, "beds": beds, "roomForRent": "room" in flags})
    return {
        "zpid": f"lot-{key}", "detailUrl": f"/b/sample-{key.lower()}-new-york-ny/{key}/", "statusType": "FOR_RENT",
        "address": f"{street}, New York, NY {zipcode}", "addressStreet": street, "addressCity": "New York",
        "addressState": "NY", "addressZipcode": zipcode, "units": entries, "lotId": 1000000000 + int(key[-3:]),
        "latLong": {"latitude": lat, "longitude": lon}, "buildingName": name, "isBuilding": True,
        "carouselPhotosComposable": photos_block(next_key, photos),
        "availabilityCount": len(entries),
    }


def zillow_unit(next_key, zpid, street, unit, zipcode, lat, lon, price, beds, baths, sqft, home_type, days, photos):
    line = f"{street} {unit}"
    home = {"zpid": zpid, "streetAddress": line, "unit": unit, "zipcode": zipcode, "latitude": lat,
            "longitude": lon, "price": price, "bedrooms": beds, "bathrooms": baths, "livingArea": sqft,
            "homeType": home_type, "daysOnZillow": days}
    return {
        "zpid": zpid, "detailUrl": f"/homedetails/sample-{zpid}/{zpid}_zpid/", "statusType": "FOR_RENT",
        "address": f"{line}, New York, NY {zipcode}", "addressStreet": line, "addressCity": "New York",
        "addressState": "NY", "addressZipcode": zipcode, "price": f"${price:,}/mo", "unformattedPrice": price,
        "beds": beds, "baths": baths, "area": sqft, "latLong": {"latitude": lat, "longitude": lon},
        "hdpData": {"homeInfo": home}, "isBuilding": False,
        "carouselPhotosComposable": photos_block(next_key, photos),
    }


def zillow_page():
    next_key = photo_keys("2b")
    results = [zillow_building(next_key, *b) for b in BUILDINGS] + [zillow_unit(next_key, *u) for u in UNITS]
    return {"props": {"pageProps": {"searchPageState": {
        "cat1": {"searchResults": {"listResults": results, "mapResults": []}},
        "categoryTotals": {"cat1": {"totalResultCount": ZILLOW_TOTAL}},
    }}}}


def build():
    """{file name: text} for every fixture this script writes."""
    return {FLIGHT: streeteasy_flight(), NEXT_DATA: json.dumps(zillow_page(), indent=1) + "\n"}


def main():
    for name, text in build().items():
        (FIXTURES / name).write_text(text, encoding="utf-8")
        print(f"tests/fixtures/{name}: {len(text.encode('utf-8'))} bytes")


if __name__ == "__main__":
    main()
