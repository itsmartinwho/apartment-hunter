"""Scores, limits, composite, and tiers. Offline."""

from apartment_hunter import areas, criteria, scoring
from apartment_hunter.criteria import DEFAULT_LIMITS, DEFAULT_WEIGHTS

WV = 157  # West Village, tier 1 by default.


def listing(**kw):
    base = {"id": "se:1", "source": "streeteasy", "kind": "unit", "price": 5000, "beds": 1, "baths": 1,
            "area_id": WV, "subway": {"walk_min": 4.0}, "lines_nearby": ["1", "2", "3"]}
    return {**base, **kw}


def test_price_scores_cheaper_higher():
    lim = {**DEFAULT_LIMITS, "price_max": 7000}
    cheap = scoring.criterion_scores(listing(price=3500), lim, {})["price"]
    dear = scoring.criterion_scores(listing(price=6500), lim, {})["price"]
    assert cheap > dear
    assert scoring.criterion_scores(listing(price=2800), lim, {})["price"] == 1.0  # 40 percent of the maximum


def test_net_effective_is_optional():
    lim = {**DEFAULT_LIMITS, "use_net_effective": True}
    l1 = listing(price=7000, net_effective=6000)
    assert scoring.effective_price(l1, lim) == 6000
    assert scoring.effective_price(l1, DEFAULT_LIMITS) == 7000


def test_unknown_counts_as_half():
    assert scoring.composite({"views": None, "price": 1.0}, {"views": 5, "price": 5}) == 0.75


def test_zero_weights_give_neutral_score():
    assert scoring.composite({"price": 1.0}, {"price": 0}) == 0.5


def test_limits_exclude_over_budget_and_wrong_area():
    lim = {**DEFAULT_LIMITS, "price_max": 5000, "areas": [100]}
    assert scoring.check_limits(listing(price=6000), lim, {}) == "Over budget"
    assert scoring.check_limits(listing(price=4000, area_id=302), lim, {}) == "Outside selected areas"
    assert scoring.check_limits(listing(price=4000), lim, {}) is None


def test_limits_walk_and_ground_floor_and_late_date():
    lim = {**DEFAULT_LIMITS, "max_walk_min": 5, "no_ground_floor": True}
    assert scoring.check_limits(listing(subway={"walk_min": 9.0}), lim, {}) == "Too far from the subway"
    assert scoring.check_limits(listing(floor=0), lim, {}) == "Ground floor"
    assert scoring.check_limits(listing(available_at="2027-01-10"), lim, {}) == "Available too late"


def test_strict_move_in_needs_a_date():
    lim = {**DEFAULT_LIMITS, "strict_move_in": True}
    assert scoring.check_limits(listing(), lim, {}) == "No move-in date"
    assert scoring.check_limits(listing(available_at="2026-11-01"), lim, {}) is None


def test_max_tier_filters_weak_neighborhoods():
    lim = {**DEFAULT_LIMITS, "max_tier": 2}
    assert scoring.check_limits(listing(area_id=154), lim, areas.DEFAULT_TIERS) == "Neighborhood tier too low"


def test_floor_and_penthouse_scores():
    s = scoring.criterion_scores(listing(floor=20), DEFAULT_LIMITS, {})
    assert s["floor"] == 1.0
    assert scoring.criterion_scores(listing(is_penthouse=True), DEFAULT_LIMITS, {})["floor"] == 1.0
    assert scoring.criterion_scores(listing(floor=1), DEFAULT_LIMITS, {})["floor"] == 0.0


def test_pass2_scores_shrink_when_photos_may_not_show_the_unit():
    inspection = {"judgments": {"views": {"score": 1.0}, "real_unit": {"p": 0.0}}}
    s = scoring.criterion_scores(listing(inspection=inspection), DEFAULT_LIMITS, {})
    assert 0.5 < s["views"] < 0.7
    trusted = {"judgments": {"views": {"score": 1.0}, "real_unit": {"p": 1.0}}}
    assert scoring.criterion_scores(listing(inspection=trusted), DEFAULT_LIMITS, {})["views"] == 1.0


def test_move_in_scores_inside_window_best():
    lim = DEFAULT_LIMITS
    inside = scoring.criterion_scores(listing(available_at="2026-11-01"), lim, {})["move_in"]
    early = scoring.criterion_scores(listing(available_at="2026-09-01"), lim, {})["move_in"]
    assert inside == 1.0 and early < inside


def test_rank_assigns_tiers_by_percentile():
    ls = [listing(id=str(i), price=3000 + i * 100) for i in range(20)]
    out = scoring.rank(ls, DEFAULT_LIMITS, DEFAULT_WEIGHTS, {})
    tiers = [x["tier"] for x in out["listings"]]
    assert tiers[:2] == [1, 1] and tiers[2] == 2 and tiers[-1] == 4
    assert [x["rank"] for x in out["listings"]] == list(range(1, 21))
    assert out["listings"][0]["price"] == 3000


def test_rank_counts_exclusions():
    out = scoring.rank([listing(price=9000), listing(id="2")], DEFAULT_LIMITS, DEFAULT_WEIGHTS, {})
    assert out["excluded"] == {"Over budget": 1} and len(out["listings"]) == 1


def test_clean_safety_keeps_minimum_pauses():
    safe = criteria.clean_safety({"pause_s": 1, "page_loads_per_site": 99, "deep_look_pause_s": "x"})
    assert safe["pause_s"] == 20 and safe["page_loads_per_site"] == 3 and safe["deep_look_pause_s"] == 30


def test_building_group_photos_count_less():
    inspection = {"judgments": {"views": {"score": 1.0}, "real_unit": {"p": 1.0}}}
    unit = scoring.criterion_scores(listing(inspection=inspection), DEFAULT_LIMITS, {})["views"]
    group = scoring.criterion_scores(listing(inspection=inspection, kind="building_group"), DEFAULT_LIMITS, {})["views"]
    assert unit == 1.0 and 0.75 < group < 0.85


def test_rank_reports_estimated_floor_from_photos():
    probabilities = {"0": 0.0, "1": 0.0, "2": 1.0, "3": 0.0}
    inspection = {"judgments": {"floor_estimate": {"score": 0.67, "probabilities": probabilities}}}
    out = scoring.rank([listing(inspection=inspection)], DEFAULT_LIMITS, DEFAULT_WEIGHTS, {})["listings"][0]
    assert out["floor_estimated"] == 8 and out["scores"]["floor"] is not None
    known = scoring.rank([listing(floor=3)], DEFAULT_LIMITS, DEFAULT_WEIGHTS, {})["listings"][0]
    assert known["floor_estimated"] is None
