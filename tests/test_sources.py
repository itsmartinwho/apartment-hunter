"""StreetEasy and Zillow parsing against the synthetic sample pages. Offline."""

import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from apartment_hunter.criteria import DEFAULT_LIMITS
from apartment_hunter.sources import streeteasy, zillow

FIXTURES = Path(__file__).parent / "fixtures"


def se_page():
    return streeteasy.parse_page((FIXTURES / "streeteasy_search_flight.txt").read_text())


def z_page():
    return zillow.parse_page((FIXTURES / "zillow_search_next_data.json").read_text())


def test_streeteasy_page_listings_are_complete():
    page = se_page()
    assert page["total"] == 1500 and len(page["listings"]) == 6
    by_id = {x["id"]: x for x in page["listings"]}
    first = by_id["se:9100001"]
    assert first["price"] == 4950 and first["net_effective"] == 4538 and first["months_free"] == 1
    assert first["area_name"] == "Lower East Side" and first["area_id"] == 109
    assert len(first["photos"]) == 3 and first["photos"][0].endswith("-se_large_800_400.webp")
    assert first["url"] == "https://streeteasy.com/building/sample-house/401"
    assert first["lat"] and first["lon"] and first["beds"] == 1 and first["baths"] == 1
    assert by_id["se:9100004"]["sqft"] == 713 and by_id["se:9100004"]["baths"] == 1.5
    assert "se:9100007" not in by_id  # Rented: off the market.


def test_streeteasy_net_effective_zero_means_none():
    assert {x["id"]: x for x in se_page()["listings"]}["se:9100003"]["net_effective"] is None


def test_streeteasy_search_url_defaults():
    url = streeteasy.search_url(DEFAULT_LIMITS)
    assert url.startswith("https://streeteasy.com/for-rent/nyc/price:-7500%7Carea:100,301,")
    assert "%7Cbeds%3E=1%7C" in url and url.endswith("%7Cavailable:20261115?sort_by=listed_desc")
    assert "baths" not in url and "amenities" not in url


def test_streeteasy_url_amenities_and_pets():
    url = streeteasy.search_url({**DEFAULT_LIMITS, "must_have": ["laundry_in_unit", "elevator", "pets"]})
    assert "amenities:washer_dryer,elevator" in url and "pets:allowed" in url


def test_streeteasy_beds_formats():
    assert streeteasy._beds(0, 0) == "beds:0"
    assert streeteasy._beds(1, 2) == "beds:1-2"
    assert streeteasy._beds(0, 2) == "beds<=2"
    assert streeteasy._beds(2, 4) == "beds>=2"
    assert streeteasy._beds(0, 4) is None


def test_streeteasy_map_response():
    body = json.dumps({"data": {"searchRentals": {"search": {"criteria": "x"}, "totalCount": 1500, "edges": [
        {"node": {"id": "1", "areaName": "Chelsea", "bedroomCount": 1, "buildingType": "RENTAL",
                  "fullBathroomCount": 1, "geoPoint": {"latitude": 40.745, "longitude": -73.998},
                  "halfBathroomCount": 1, "leadMedia": {"photo": {"key": "a" * 32}}, "price": 5100,
                  "totalMonthlyPrice": None, "sourceGroupLabel": "X", "status": "ACTIVE", "street": "1 Mock Street",
                  "unit": "#5A", "urlPath": "/building/x/5a", "tier": None}},
        {"node": {"id": "2", "status": "RENTED", "price": 1}},
        {"node": None},
    ]}}})
    out = streeteasy.parse_map(body)
    assert out["total"] == 1500 and len(out["listings"]) == 1
    item = out["listings"][0]
    assert item["id"] == "se:1" and item["baths"] == 1.5 and item["detail_level"] == "map"
    assert item["photos"] == [f"https://photos.zillowstatic.com/fp/{'a' * 32}-se_large_800_400.webp"]
    assert item["area_id"] == 115 and item["unit"] == "#5A"


def test_streeteasy_map_ignores_other_queries():
    assert streeteasy.parse_map('{"data": {"viewer": {"id": 1}}}') == {"listings": [], "total": None}
    assert streeteasy.parse_map("not json") == {"listings": [], "total": None}


def test_streeteasy_detail_reads_description_and_photos():
    key = "b" * 32
    flight = '1:{"listing":{"description":"' + "Sunny corner one-bedroom with oversized windows. " * 3 + \
        '","amenities":["Doorman","Elevator"],"photos":[{"url":"https://photos.zillowstatic.com/fp/' + key + \
        '-p_e.webp"}]}}\n'
    out = streeteasy.parse_detail({"flight": flight, "ldjson": [], "text": "x"})
    assert out["description"].startswith("Sunny corner") and out["amenities"] == ["Doorman", "Elevator"]
    assert out["photos"] == [streeteasy.photo_url(key)]


def test_zillow_page_units_and_buildings():
    page = z_page()
    by_id = {x["id"]: x for x in page["listings"]}
    assert page["total"] == 2500
    tower = by_id["zb:Smp001:1"]
    assert tower["kind"] == "building_group" and tower["price"] == 5200 and tower["price_is_from"]
    assert tower["title"] == "Sample Tower" and len(tower["photos"]) == 4 and tower["lat"]
    unit = next(x for x in page["listings"] if x["title"] == "123 Example Ave Apt 7B")
    assert unit["kind"] == "unit" and unit["price"] == 4745 and unit["sqft"] == 608
    assert unit["street"] == "123 Example Ave" and unit["unit"] == "Apt 7B" and unit["beds"] == 1
    assert unit["url"].startswith("https://www.zillow.com/")


def test_zillow_page_counts():
    listings = z_page()["listings"]
    assert sum(1 for x in listings if x["kind"] == "unit") == 4
    assert sum(1 for x in listings if x["kind"] == "building_group") == 11
    ids = {x["id"] for x in listings}
    # A room for rent, a unit without a price and a building without units add no groups.
    assert "zb:Smp002:3" not in ids and not any(i.startswith("zb:Smp006") for i in ids)
    assert not any(x["price"] == 900 for x in listings)


def test_zillow_photo_falls_back_to_the_lead_image():
    key = "d" * 32
    result = {"zpid": "7", "unformattedPrice": 3000, "addressStreet": "1 Mock Street Apt 2", "beds": 1,
              "imgSrc": f"https://photos.zillowstatic.com/fp/{key}-p_e.jpg", "detailUrl": "/homedetails/x/7_zpid/"}
    assert zillow.normalize(result)[0]["photos"] == [zillow.photo_url(key)]


def test_zillow_money():
    assert zillow.money("$6,440+") == 6440 and zillow.money("$4,489+/mo") == 4489 and zillow.money(None) is None


def test_zillow_search_url_filters():
    url = zillow.search_url({**DEFAULT_LIMITS, "must_have": ["laundry_in_unit", "doorman"]})
    parsed = urlparse(url)
    assert parsed.path == "/homes/for_rent/"
    state = json.loads(unquote(parse_qs(parsed.query)["searchQueryState"][0]))
    f = state["filterState"]
    assert f["mp"] == {"min": None, "max": 7500} and f["beds"] == {"min": 1, "max": None}
    assert f["lau"] == {"value": True} and f["sort"] == {"value": "days"} and f["fr"] == {"value": True}
    b = state["mapBounds"]
    assert b["south"] < 40.70 and b["north"] > 40.85 and b["west"] < -74.0 and b["east"] > -73.95


def test_zillow_manhattan_only_uses_region():
    url = zillow.search_url({**DEFAULT_LIMITS, "areas": [100]})
    assert "/manhattan-new-york-ny/rentals/" in url and "12530" in unquote(url)


def test_zillow_map_response_shape():
    body = json.dumps({"cat1": {"searchResults": {"mapResults": [
        {"zpid": "123", "price": "$3,900/mo", "beds": 1, "baths": 1, "area": 700,
         "detailUrl": "/homedetails/x/123_zpid/",
         "latLong": {"latitude": 40.72, "longitude": -73.95}, "addressStreet": "10 N 5th St APT 3F"}]}},
        "categoryTotals": {"cat1": {"totalResultCount": 800}}})
    out = zillow.parse_map(body)
    assert out["total"] == 800 and out["listings"][0]["id"] == "z:123" and out["listings"][0]["price"] == 3900
    assert out["listings"][0]["unit"] == "APT 3F"


def test_zillow_detail_expands_client_cache():
    key = "c" * 32
    inner = json.dumps({"q": {"property": {"description": "Renovated two-bedroom with city views. " * 4,
                                           "photos": [f"https://photos.zillowstatic.com/fp/{key}-p_e.jpg"]}}})
    page = json.dumps({"props": {"pageProps": {"componentProps": {"gdpClientCache": inner}}}})
    out = zillow.parse_detail({"next": page, "ldjson": []})
    assert out["description"].startswith("Renovated two-bedroom") and out["photos"] == [zillow.photo_url(key)]
