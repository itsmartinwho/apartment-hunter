"""One schema for every criterion, limit, and safety setting. The UI and the scorer both read it."""

from .areas import DEFAULT_SEARCH_AREAS

CRITERIA = [
    {"id": "price", "label": "Price", "pass": 1, "weight": 8,
     "help": "Lower rent within your range scores higher."},
    {"id": "neighborhood", "label": "Neighborhood tier", "pass": 1, "weight": 10,
     "help": "Your tier for the neighborhood: tier 1 scores highest."},
    {"id": "subway", "label": "Subway walk", "pass": 1, "weight": 5,
     "help": "Walk time to the nearest station: 3 minutes or less is best, 15 or more is worst."},
    {"id": "lines", "label": "Subway lines nearby", "pass": 1, "weight": 2,
     "help": "Different subway lines within an 8-minute walk."},
    {"id": "size", "label": "Size", "pass": 1, "weight": 6,
     "help": "Square feet. When a listing does not say, the tool estimates from bedrooms and bathrooms."},
    {"id": "bedrooms", "label": "Bedrooms", "pass": 1, "weight": 3,
     "help": "More bedrooms than your minimum score higher."},
    {"id": "floor", "label": "Floor height", "pass": 1, "weight": 4,
     "help": "Higher floors score higher. From the unit number, or from the photos when the number says nothing."},
    {"id": "move_in", "label": "Move-in fit", "pass": 1, "weight": 3,
     "help": "Available date inside your move-in window."},
    {"id": "deal", "label": "Free months", "pass": 1, "weight": 2,
     "help": "Discount from free months on the lease."},
    {"id": "views", "label": "Views", "pass": 2, "weight": 5,
     "help": "From photos: skyline, park, or water views score highest.",
     "question": "Rate the view from this apartment. "
                 "Use `photo_observations.view` and `photo_observations.floor_cues`.",
     "levels": [
         "No real view: the windows face a wall or an airshaft, or no window view is visible",
         "Street-level or courtyard view, or close buildings block most of the view",
         "Open view over nearby rooftops, or a partial skyline",
         "Wide, open view of the skyline, a park, or the river",
     ]},
    {"id": "light", "label": "Natural light", "pass": 2, "weight": 7,
     "help": "From photos: how much daylight the rooms get.",
     "question": "Rate how much natural daylight this apartment gets. "
                 "Use `photo_observations.light` and `photo_observations.windows`.",
     "levels": [
         "Dark: little daylight, and artificial light dominates",
         "Some daylight in a few rooms",
         "Bright: strong daylight in most rooms",
         "Flooded with daylight: very large windows and direct sun",
     ]},
    {"id": "windows", "label": "Window size", "pass": 2, "weight": 4,
     "help": "From photos: small windows score low, floor-to-ceiling windows score highest.",
     "question": "Rate the size of the windows in this apartment. Use `photo_observations.windows`.",
     "levels": [
         "Small or few windows",
         "Standard-size windows",
         "Oversized windows",
         "Floor-to-ceiling windows or window walls",
     ]},
    {"id": "renovation", "label": "New or renovated", "pass": 2, "weight": 6,
     "help": "From photos: modern, renovated finishes score high; old and worn finishes score low.",
     "question": "Rate how new or recently renovated the interior of this apartment looks. "
                 "Use `photo_observations.finishes` and `photo_observations.condition`.",
     "levels": [
         "Old and worn: dated kitchen and bathroom, worn floors",
         "Clean but older finishes",
         "Recently renovated with modern finishes",
         "Brand-new construction or luxury finishes",
     ]},
    {"id": "space", "label": "Spacious feel", "pass": 2, "weight": 4,
     "help": "From photos: how roomy the apartment looks for New York.",
     "question": "Rate how spacious this apartment looks for New York City. "
                 "Use `photo_observations.space` and the facts in `listing`.",
     "levels": [
         "Cramped: the rooms barely fit basic furniture",
         "Typical New York City size",
         "Spacious: the rooms fit furniture with room to spare",
         "Very spacious: large, open rooms",
     ]},
]

CRITERION_IDS = [c["id"] for c in CRITERIA]
DEFAULT_WEIGHTS = {c["id"]: c["weight"] for c in CRITERIA}


def _preset(**changes):
    return {**DEFAULT_WEIGHTS, **changes}


# One-click weight profiles. "Balanced" lets the tool optimize everything inside your limits.
PRESETS = [
    {"id": "balanced", "label": "Balanced", "help": "Set only your limits; the tool weighs everything else evenly.",
     "weights": dict(DEFAULT_WEIGHTS)},
    {"id": "budget", "label": "Best value", "help": "Rent and free months first.",
     "weights": _preset(price=10, deal=7, neighborhood=5, size=5, light=5, renovation=4)},
    {"id": "location", "label": "Location", "help": "Neighborhood and subway first.",
     "weights": _preset(neighborhood=10, subway=9, lines=6, price=5, size=4)},
    {"id": "light", "label": "Light and views", "help": "Daylight, views, big windows, and high floors first.",
     "weights": _preset(light=10, views=9, windows=8, floor=7, price=5, renovation=5)},
    {"id": "space", "label": "Space", "help": "Square feet, bedrooms, and a roomy feel first.",
     "weights": _preset(size=10, space=9, bedrooms=7, price=5)},
    {"id": "new", "label": "New and renovated", "help": "Modern finishes first.",
     "weights": _preset(renovation=10, light=7, windows=5, price=5)},
]

# id -> label, StreetEasy URL amenity code, Zillow searchQueryState short key.
AMENITIES = {
    "elevator": {"label": "Elevator", "streeteasy": "elevator", "zillow": "eaa"},
    "doorman": {"label": "Doorman", "streeteasy": "doorman", "zillow": None},
    "laundry_in_unit": {"label": "Washer/dryer in unit", "streeteasy": "washer_dryer", "zillow": "lau"},
    "laundry_building": {"label": "Laundry in building", "streeteasy": "laundry", "zillow": None},
    "dishwasher": {"label": "Dishwasher", "streeteasy": "dishwasher", "zillow": "dish"},
    "outdoor_space": {"label": "Private outdoor space", "streeteasy": "private_outdoor_space", "zillow": "os"},
    "pets": {"label": "Pets allowed", "streeteasy": None, "zillow": "pet"},
    "gym": {"label": "Gym", "streeteasy": "gym", "zillow": "fit"},
}

DEFAULT_LIMITS = {
    "price_min": 0,
    "price_max": 7500,  # 40x rule: $300,000 income supports $7,500 a month.
    "beds_min": 1,
    "beds_max": 4,  # 4 means 4 or more.
    "baths_min": 1,
    "sqft_min": 0,
    "move_in_from": "2026-10-20",
    "move_in_by": "2026-11-15",
    "strict_move_in": False,
    "areas": DEFAULT_SEARCH_AREAS,
    "max_tier": 4,
    "max_walk_min": 15,
    "no_ground_floor": False,
    "must_have": [],
    "sources": ["streeteasy", "zillow"],
    "include_building_groups": True,
    "use_net_effective": False,
}

DEFAULT_SAFETY = {
    "page_loads_per_site": 1,
    "pause_s": 20,
    "deep_look_max": 5,
    "deep_look_pause_s": 30,
    "human_wait_s": 300,
    "inspect_top_n": 25,
}

SAFETY_BOUNDS = {
    "page_loads_per_site": (1, 3),
    "pause_s": (20, 600),
    "deep_look_max": (1, 10),
    "deep_look_pause_s": (30, 600),
    "human_wait_s": (30, 900),
    "inspect_top_n": (1, 60),
}


def clean_safety(safety):
    """Clamp user safety settings to the allowed bounds. The minimum pauses cannot go lower."""
    out = dict(DEFAULT_SAFETY)
    for key, (low, high) in SAFETY_BOUNDS.items():
        try:
            out[key] = int(min(high, max(low, int((safety or {}).get(key, out[key])))))
        except (TypeError, ValueError):
            pass
    return out


def clean_limits(limits):
    out = dict(DEFAULT_LIMITS)
    out.update({k: v for k, v in (limits or {}).items() if k in DEFAULT_LIMITS})
    for key in ("price_min", "price_max", "beds_min", "beds_max", "sqft_min", "max_tier", "max_walk_min"):
        try:
            out[key] = int(out[key])
        except (TypeError, ValueError):
            out[key] = DEFAULT_LIMITS[key]
    try:
        out["baths_min"] = float(out["baths_min"])
    except (TypeError, ValueError):
        out["baths_min"] = DEFAULT_LIMITS["baths_min"]
    out["areas"] = [int(a) for a in out.get("areas") or [] if str(a).isdigit()] or list(DEFAULT_SEARCH_AREAS)
    out["must_have"] = [a for a in out.get("must_have") or [] if a in AMENITIES]
    out["sources"] = [s for s in out.get("sources") or [] if s in ("streeteasy", "zillow")]
    return out


def clean_weights(weights):
    out = dict(DEFAULT_WEIGHTS)
    for key, value in (weights or {}).items():
        if key in out:
            try:
                out[key] = max(0, min(10, int(value)))
            except (TypeError, ValueError):
                pass
    return out
