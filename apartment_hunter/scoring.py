"""Criterion scores from 0 (worst) to 1 (best), limits, composite score, and tiers. Pure functions."""

from datetime import date

from . import areas
from .criteria import CRITERIA, CRITERION_IDS

TIER_SCORE = {1: 1.0, 2: 0.65, 3: 0.3, 4: 0.0}
TIER_CUTS = (0.10, 0.30, 0.60)  # Tier 1 is the top 10 percent, tier 2 the next 20, tier 3 the next 30.
PASS2 = [c["id"] for c in CRITERIA if c["pass"] == 2]
BUILDING_TRUST = 0.6  # Building-group photos show the building and model units, not the unit you would rent.


def clamp(x):
    return max(0.0, min(1.0, x))


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def effective_price(listing, limits):
    net = listing.get("net_effective")
    if limits.get("use_net_effective") and isinstance(net, (int, float)) and net > 0:
        return net
    return listing.get("price")


def photo_trust(listing):
    """How much pass 2 scores count, from 0.3 to 1: lower when the photos may not show this unit."""
    judgments = (listing.get("inspection") or {}).get("judgments") or {}
    p_real = (judgments.get("real_unit") or {}).get("p", 1.0)
    trust = clamp(0.3 + 0.7 * p_real)
    return trust * BUILDING_TRUST if listing.get("kind") == "building_group" else trust


def _judgment(listing, key):
    """A pass 2 score from Jev, pulled toward 0.5 by photo_trust."""
    answer = ((listing.get("inspection") or {}).get("judgments") or {}).get(key)
    if not answer or answer.get("score") is None:
        return None
    return round(0.5 + (answer["score"] - 0.5) * photo_trust(listing), 4)


FLOOR_LEVELS = (0, 3, 8, 18)  # Typical floor for each Jev floor_estimate level.


def estimated_floor(listing):
    """Expected floor from Jev's floor_estimate probabilities, or None."""
    judgments = (listing.get("inspection") or {}).get("judgments") or {}
    probabilities = (judgments.get("floor_estimate") or {}).get("probabilities")
    if not probabilities:
        return None
    return sum(FLOOR_LEVELS[int(k)] * p for k, p in probabilities.items() if int(k) < len(FLOOR_LEVELS))


def _estimated_floor_score(listing):
    floor = estimated_floor(listing)
    if floor is None:
        return None
    return round(0.5 + (clamp((floor - 1) / 19) - 0.5) * photo_trust(listing), 4)


def criterion_scores(listing, limits, tiers):
    s = {key: None for key in CRITERION_IDS}
    price = effective_price(listing, limits)
    high = limits.get("price_max") or 0
    low = max(limits.get("price_min") or 0, 0.4 * high)
    if isinstance(price, (int, float)) and price > 0 and high > 0:
        s["price"] = clamp((high - price) / (high - low)) if high > low else float(price <= high)
    if listing.get("area_id") is not None:
        s["neighborhood"] = TIER_SCORE[areas.tier_for(listing["area_id"], tiers)]
    subway = listing.get("subway")
    if subway:
        s["subway"] = clamp((15 - subway["walk_min"]) / 12)
        s["lines"] = clamp(len(listing.get("lines_nearby") or []) / 8)
    sqft = listing.get("sqft") or listing.get("sqft_estimated")
    if sqft:
        s["size"] = clamp((sqft - 450) / 850)
    beds = listing.get("beds")
    if isinstance(beds, (int, float)):
        s["bedrooms"] = clamp((beds - limits.get("beds_min", 0) + 1) / 3)
    if listing.get("is_penthouse"):
        s["floor"] = 1.0
    elif isinstance(listing.get("floor"), (int, float)):
        s["floor"] = clamp((listing["floor"] - 1) / 19)
    else:
        s["floor"] = _estimated_floor_score(listing)
    available, start, end = _date(listing.get("available_at")), _date(limits.get("move_in_from")), _date(
        limits.get("move_in_by"))
    if available and start and end:
        if start <= available <= end:
            s["move_in"] = 1.0
        elif available < start:
            s["move_in"] = max(0.2, 1 - (start - available).days / 60)
        else:
            s["move_in"] = clamp(0.6 - (available - end).days / 30)
    months_free, lease = listing.get("months_free"), listing.get("lease_months")
    net, gross = listing.get("net_effective"), listing.get("price")
    if isinstance(net, (int, float)) and net > 0 and isinstance(gross, (int, float)) and gross > net:
        s["deal"] = clamp((1 - net / gross) / 0.12)
    elif isinstance(months_free, (int, float)):
        s["deal"] = clamp((months_free / (lease or 12)) / 0.12) if months_free else 0.0
    for key in PASS2:
        s[key] = _judgment(listing, key)
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()}


def check_limits(listing, limits, tiers):
    """The first reason the listing fails a hard limit, or None when it passes."""
    if listing.get("source") not in limits.get("sources", ["streeteasy", "zillow"]):
        return "Source turned off"
    if listing.get("kind") == "building_group" and not limits.get("include_building_groups", True):
        return "Zillow building group"
    price = effective_price(listing, limits)
    if not isinstance(price, (int, float)) or price <= 0:
        return "No price"
    if price > limits.get("price_max", 10**9):
        return "Over budget"
    if price < limits.get("price_min", 0):
        return "Under minimum rent"
    beds = listing.get("beds")
    if beds is None:
        return "Unknown bedrooms"
    if beds < limits.get("beds_min", 0):
        return "Too few bedrooms"
    if limits.get("beds_max", 4) < 4 and beds > limits["beds_max"]:
        return "Too many bedrooms"
    baths = listing.get("baths")
    if isinstance(baths, (int, float)) and baths < limits.get("baths_min", 0):
        return "Too few bathrooms"
    if listing.get("sqft") and listing["sqft"] < limits.get("sqft_min", 0):
        return "Too small"
    if not areas.in_selection(listing.get("area_id"), limits.get("areas") or []):
        return "Outside selected areas"
    if areas.tier_for(listing.get("area_id"), tiers) > limits.get("max_tier", 4):
        return "Neighborhood tier too low"
    subway = listing.get("subway")
    if subway and subway["walk_min"] > limits.get("max_walk_min", 99):
        return "Too far from the subway"
    if limits.get("no_ground_floor") and listing.get("floor") == 0:
        return "Ground floor"
    available, start, end = _date(listing.get("available_at")), _date(limits.get("move_in_from")), _date(
        limits.get("move_in_by"))
    if end and available and available > end:
        return "Available too late"
    if limits.get("strict_move_in"):
        if not available:
            return "No move-in date"
        if start and (start - available).days > 14:
            return "Available too early"
    amenities = listing.get("amenities") or {}
    for need in limits.get("must_have") or []:
        if amenities.get(need) is False:
            return "Missing a must-have"
    return None


def composite(scores, weights):
    total = sum(max(0, weights.get(k, 0)) for k in scores)
    if total == 0:
        return 0.5
    value = sum(max(0, weights.get(k, 0)) * (0.5 if v is None else v) for k, v in scores.items())
    return round(value / total, 4)


def tier_for_rank(index, count):
    position = index / max(count, 1)
    for tier, cut in enumerate(TIER_CUTS, start=1):
        if position < cut:
            return tier
    return 4


def rank(listings, limits, weights, tiers):
    kept, excluded = [], {}
    for listing in listings:
        reason = check_limits(listing, limits, tiers)
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        scores = criterion_scores(listing, limits, tiers)
        kept.append({**listing, "scores": scores, "score": composite(scores, weights)})
    kept.sort(key=lambda x: (-x["score"], effective_price(x, limits) or 0, x["id"]))
    for index, listing in enumerate(kept):
        listing["rank"] = index + 1
        listing["tier"] = tier_for_rank(index, len(kept))
        listing["area_tier"] = areas.tier_for(listing.get("area_id"), tiers)
        estimate = None if listing.get("floor") is not None or listing.get("is_penthouse") else estimated_floor(listing)
        listing["floor_estimated"] = round(estimate) if estimate is not None else None
    return {"listings": kept, "excluded": excluded}
