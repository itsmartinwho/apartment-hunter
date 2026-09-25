"""Areas, subway, floor parsing, and enrichment. Offline."""

import pytest

from apartment_hunter import areas, enrich, subway


def test_areas_have_manhattan_and_boundaries():
    table = areas.load()
    assert table[100].name == "Manhattan"
    assert table[157].name == "West Village" and len(table[157].polygon) > 10


def test_locate_returns_deepest_area():
    assert areas.locate(40.7359, -74.0036).name == "West Village"
    assert areas.locate(40.7178, -73.9571).name == "Williamsburg"
    assert areas.locate(40.0, -75.0) is None


def test_tier_inherits_from_ancestors():
    tiers = {"144": 4, "147": 3}
    assert areas.tier_for(147, tiers) == 3  # Morningside Heights has its own tier.
    assert areas.tier_for(154, tiers) == 4  # Central Harlem inherits Upper Manhattan.
    assert areas.tier_for(None, tiers) == 3


def test_default_tiers_match_user_examples():
    t = areas.DEFAULT_TIERS
    assert areas.tier_for(115, t) == 1 and areas.tier_for(157, t) == 1 and areas.tier_for(105, t) == 1
    assert areas.tier_for(137, t) == 2


def test_by_name_matches_listing_labels():
    assert areas.by_name("Stuyvesant Town/PCV").id == 106
    assert areas.by_name("hell's kitchen").id == 152
    assert areas.by_name("Nowhere") is None


def test_stations_cover_manhattan_lines():
    lines = {line for s in subway.load() for line in s.lines}
    assert {"1", "2", "3", "A", "C", "E", "L", "N", "Q", "R", "W", "4", "5", "6", "7", "F", "M", "G"} <= lines


def test_nearest_station_west_village():
    station, meters = subway.nearest(40.7359, -74.0036)
    assert station.name == "Christopher St-Stonewall" and meters < 500
    assert "1" in subway.lines_within(40.7359, -74.0036, 600)


@pytest.mark.parametrize(
    "unit,floor,ph",
    [
        ("#2406", 24, False),
        ("#11C", 11, False),
        ("#801", 8, False),
        ("#9B", 9, False),
        ("Apt 28H", 28, False),
        ("# 11S", 11, False),
        ("#PH1I", None, True),
        ("Ph G", None, True),
        ("#S9C", 9, False),
        ("#5", None, False),
        ("#G29", None, False),
        ("# 42981d232", None, False),
        ("#3807", 38, False),
        ("#1119", 11, False),
        ("GARDEN", 0, False),
        ("#B", None, False),
        ("# 1B-1Ba-721Sqft", None, False),
        ("4th Floor", 4, False),
        (None, None, False),
    ],
)
def test_parse_floor(unit, floor, ph):
    assert enrich.parse_floor(unit) == (floor, ph)


def test_enrich_adds_subway_and_area():
    out = enrich.enrich({"lat": 40.7359, "lon": -74.0036, "unit": "#4B", "beds": 1, "baths": 1, "sqft": None})
    assert out["area_name"] == "West Village" and out["borough"] == "Manhattan"
    assert out["subway"]["walk_min"] < 8
    assert out["floor"] == 4 and out["floor_source"] == "unit"
    assert out["sqft_estimated"] == 650


def test_enrich_without_point_is_safe():
    out = enrich.enrich({"lat": None, "lon": None, "unit": None, "beds": 2, "baths": 1})
    assert out["subway"] is None and out["area_id"] is None and out["lines_nearby"] == []


def test_enrich_keeps_source_area_label():
    out = enrich.enrich({"lat": None, "lon": None, "area_name": "Hell's Kitchen", "beds": 1})
    assert out["area_id"] == 152 and out["borough"] == "Manhattan"
