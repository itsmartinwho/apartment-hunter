# Apartment Hunter implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web tool that searches StreetEasy and Zillow through the user's Chrome, ranks the listings on user-weighted criteria in two passes (deterministic, then vision plus Jev), and shows tiers on a list and a map.

**Architecture:** A stdlib Python HTTP server on 127.0.0.1 serves a vanilla JS page. A job thread runs pass 1 (one page load per site through Browser Harness, passive capture of the page's own responses) and pass 2 (CDN photos, OpenRouter vision, TypeSafe Jev). SQLite caches everything. Ranking runs on the server in milliseconds, so every slider change calls `/api/rank`.

**Tech Stack:** Python 3.12+, uv, `browser-harness==0.1.13`, `httpx[http2]`, stdlib `sqlite3` and `http.server`, pytest, ruff; Leaflet 1.9 from a CDN; TypeSafe `jev-latest`; OpenRouter `google/gemini-2.5-flash-lite`.

**Spec:** `docs/superpowers/specs/2026-09-25-apartment-hunter-design.md`

**Execution:** Native (the author implements in this session; the user asked for autonomous overnight work). A final whole-repo review runs at the end.

## Global Constraints

- Never solve, click, or hide from a human check. Bring the tab to the front and wait for the user.
- Never send custom requests to StreetEasy or Zillow. Read only embedded page data and the page's own responses.
- Default: one page load per site per search; at least 20 seconds between loads on one site.
- No login, no background searches, no stealth changes (user agent, fingerprint, cookies, proxies).
- Tests never call paid APIs or real listing sites.
- Credentials stay in `.env` (git-ignored) and on the server side.
- Criterion scores are floats from 0 to 1, or `None` for unknown. Composite treats `None` as 0.5.
- Listing ids: `se:<id>`, `z:<zpid>`, `zb:<buildingKey>:<beds>`.
- Loopback only; POST requests need the page token.

## Review Focus

1. A listing with no map point (null `geoPoint` or `latLong`): enrichment must skip subway and area lookup, not crash; the score marks them unknown.
2. Unit strings that do not encode a floor ("#5", "#G29", "# 42981d232"): `parse_floor` returns `None` instead of a wrong floor.
3. Zillow building prices such as "$6,440+" and missing unit lists: parse the number; skip groups without a price.
4. A human check that the user never solves: the job skips the site after the wait, keeps other results, and says why.
5. Model output that is not valid JSON or has wrong answer shapes: reject and mark pass 2 as failed for that listing; keep pass 1 data.

---

## File structure

```text
pyproject.toml, README.md, AGENTS.md, .env.example, .gitignore
apartment_hunter/
  __init__.py        version
  config.py          env loading, paths, settings
  rsc.py             Next.js flight data parser
  geo.py             distance, polyline, point in polygon
  areas.py           StreetEasy area taxonomy, default areas, default tiers, point lookup
  subway.py          MTA stations, nearest station, lines nearby
  criteria.py        criteria schema, default weights, limits, safety
  enrich.py          floor parsing, size estimate, enrichment
  scoring.py         criterion scores, limits check, composite, tiers, rank
  chrome.py          Browser Harness tab: load, capture, human-check wait
  sources/__init__.py
  sources/streeteasy.py
  sources/zillow.py
  dedupe.py          merge listings across sources
  photos.py          choose and download CDN photos
  vision.py          OpenRouter vision observations
  jev.py             TypeSafe questions and validation
  store.py           SQLite cache
  pipeline.py        jobs: search, inspect, deep look
  server.py          HTTP API, static files, CLI entry point
  data/subway_stations.json, data/streeteasy_areas.json
  static/index.html, static/app.js, static/style.css
scripts/build_data.py     builds data files from MTA CSV and captured StreetEasy data
scripts/browser_check.py  real-Chrome check against local fixture pages
tests/fixtures/…           captured real pages
tests/test_*.py
```

## Task 1: Scaffold and data files

**Files:** Create `pyproject.toml`, `apartment_hunter/__init__.py`, `apartment_hunter/config.py`, `scripts/build_data.py`, `apartment_hunter/data/*.json`, `.env.example`, `AGENTS.md`.

**Interfaces:**
- Produces: `config.load_env(path: Path | None = None) -> None`; `config.settings() -> dict` with keys `typesafe_key`, `typesafe_model`, `vision_key`, `vision_base`, `vision_model`, `chrome_mode` (`"user"` or `"dedicated"`), `chrome_cdp_url`, `port`, `home` (Path).
- Data: `subway_stations.json` = list of `{"stop_id", "complex_id", "name", "lines": [str], "lat", "lon", "borough"}`; lines are the union for the station complex. `streeteasy_areas.json` = list of `{"id": int, "name", "short", "level", "parent_id": int, "borough", "boundary": [[lat, lon], …] | null}`.

- [ ] Step 1: Write `pyproject.toml` (project `apartment-hunter`, script `hunt = "apartment_hunter.server:main"`, deps `browser-harness==0.1.13`, `httpx[http2]>=0.28,<1`; dev `pytest`, `ruff`). Run `uv sync`.
- [ ] Step 2: Write `scripts/build_data.py`: read the MTA CSV (columns `GTFS Stop ID`, `Complex ID`, `Stop Name`, `Borough`, `Daytime Routes`, `GTFS Latitude`, `GTFS Longitude`), union lines by complex; read `tests/fixtures/streeteasy_search_flight.txt`, find the area list row, decode each `encodedBoundary` with `geo.decode_polyline`. Write both JSON files.
- [ ] Step 3: Test `tests/test_data.py`:

```python
from apartment_hunter import areas, subway

def test_areas_have_manhattan_and_boundaries():
    table = areas.load()
    assert table[100].name == "Manhattan"
    assert table[157].name == "West Village" and table[157].polygon

def test_stations_cover_manhattan_lines():
    stations = subway.load()
    lines = {line for s in stations for line in s.lines}
    assert {"1", "2", "3", "A", "C", "E", "L", "N", "Q", "R", "W", "4", "5", "6", "7", "F", "M"} <= lines
```

## Task 2: Flight parser and geometry

**Files:** Create `apartment_hunter/rsc.py`, `apartment_hunter/geo.py`; tests `tests/test_rsc.py`, `tests/test_geo.py`.

**Interfaces:**
- `rsc.rows(raw: str) -> dict[str, tuple[str, str]]`; `rsc.parse(raw: str) -> dict[str, object]`; `rsc.find(obj, predicate) -> list[dict]`.
- `geo.haversine_m(lat1, lon1, lat2, lon2) -> float`; `geo.decode_polyline(s: str) -> list[tuple[float, float]]`; `geo.point_in_polygon(lat, lon, polygon) -> bool`; `geo.bbox(polygon) -> tuple[float, float, float, float]` as `(south, west, north, east)`.

- [ ] Step 1: Tests:

```python
def test_parse_resolves_references_and_text_rows():
    raw = '1:{"a":"$2","b":"$3"}\n2:["x",1]\n3:T5,hello'
    data = rsc.parse(raw)
    assert data["1"] == {"a": ["x", 1], "b": "hello"}

def test_real_streeteasy_page_has_14_listings():
    data = rsc.parse(FIXTURE.read_text())
    edges = rsc.find(list(data.values()), lambda o: str(o.get("__typename", "")).endswith("RentalEdge"))
    assert len({e["node"]["id"] for e in edges}) == 14

def test_polyline_known_value():
    assert geo.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]

def test_point_in_polygon_square():
    square = [(0, 0), (0, 1), (1, 1), (1, 0)]
    assert geo.point_in_polygon(0.5, 0.5, square) and not geo.point_in_polygon(1.5, 0.5, square)
```

- [ ] Step 2: Implement (text rows `T<hexlen>,` count UTF-8 bytes; skip `I[`, `HL[`, `E{` rows; resolve `"$<hex>"` references with a cache and a depth limit).

## Task 3: Areas, subway, enrichment

**Files:** Create `areas.py`, `subway.py`, `enrich.py`; test `tests/test_enrich.py`.

**Interfaces:**
- `areas.Area` dataclass: `id, name, short, level, parent_id, borough, polygon, box`.
- `areas.load() -> dict[int, Area]`; `areas.by_name(name: str) -> Area | None`; `areas.locate(lat, lon) -> Area | None` (deepest containing area); `areas.ancestors(area_id) -> list[int]`; `areas.descendants(area_id) -> set[int]`; `areas.tier_for(area_id, tiers: dict[str, int]) -> int` (walk up; default 3); `areas.DEFAULT_SEARCH_AREAS: list[int]`; `areas.DEFAULT_TIERS: dict[str, int]` (keys are area ids as strings, for JSON).
- `subway.Station` dataclass: `name, lines, lat, lon, borough, complex_id`; `subway.load() -> list[Station]`; `subway.nearest(lat, lon) -> tuple[Station, float]`; `subway.lines_within(lat, lon, meters) -> list[str]`; `subway.walk_minutes(meters) -> float` (distance × 1.25 ÷ 80 m per minute).
- `enrich.parse_floor(unit: str | None) -> tuple[int | None, bool]` returns `(floor, is_penthouse)`; `enrich.estimate_sqft(beds, baths) -> int`; `enrich.enrich(listing: dict) -> dict` (adds `subway`, `lines_nearby`, `area_id`, `area_name`, `borough`, `floor`, `floor_source`, `is_penthouse`, `sqft_estimated`).

- [ ] Step 1: Tests:

```python
@pytest.mark.parametrize("unit,floor,ph", [
    ("#2406", 24, False), ("#11C", 11, False), ("#801", 8, False), ("#9B", 9, False),
    ("Apt 28H", 28, False), ("# 11S", 11, False), ("#PH1I", None, True), ("Ph G", None, True),
    ("#S9C", 9, False), ("#5", None, False), ("#G29", None, False), ("# 42981d232", None, False),
    ("#3807", 38, False), ("#1119", 11, False), ("GARDEN", 0, False), ("#B", None, False), (None, None, False),
])
def test_parse_floor(unit, floor, ph):
    assert enrich.parse_floor(unit) == (floor, ph)

def test_enrich_adds_subway_and_area():
    listing = {"lat": 40.7359, "lon": -74.0036, "unit": "#4B", "beds": 1, "baths": 1, "sqft": None}
    out = enrich.enrich(listing)
    assert out["area_name"] == "West Village"
    assert out["subway"]["walk_min"] < 8
    assert out["floor"] == 4 and out["sqft_estimated"] == 650

def test_enrich_without_point_is_safe():
    out = enrich.enrich({"lat": None, "lon": None, "unit": None, "beds": 2, "baths": 1})
    assert out["subway"] is None and out["area_id"] is None
```

## Task 4: Criteria and scoring

**Files:** Create `criteria.py`, `scoring.py`; test `tests/test_scoring.py`.

**Interfaces:**
- `criteria.CRITERIA: list[dict]` each `{"id", "label", "pass", "weight", "help"}`; pass 2 entries also carry `"question"` and `"levels"` used by `jev.py`.
- `criteria.DEFAULT_WEIGHTS`, `criteria.DEFAULT_LIMITS`, `criteria.DEFAULT_SAFETY`, `criteria.AMENITIES` (id → label, with StreetEasy and Zillow URL codes).
- `scoring.criterion_scores(listing, limits, tiers) -> dict[str, float | None]`.
- `scoring.check_limits(listing, limits, tiers) -> str | None` (reason text, or `None` when the listing passes).
- `scoring.composite(scores, weights) -> float`.
- `scoring.rank(listings, limits, weights, tiers) -> dict` returns `{"listings": [listing + {"scores", "score", "tier", "rank"}], "excluded": {reason: count}}`.

- [ ] Step 1: Tests:

```python
def test_price_scores_cheaper_higher():
    lim = {**DEFAULT_LIMITS, "price_min": 3000, "price_max": 7000}
    cheap = scoring.criterion_scores({"price": 3500}, lim, {})["price"]
    dear = scoring.criterion_scores({"price": 6500}, lim, {})["price"]
    assert cheap > dear

def test_unknown_counts_as_half():
    assert scoring.composite({"views": None, "price": 1.0}, {"views": 5, "price": 5}) == 0.75

def test_limits_exclude_over_budget_and_wrong_area():
    lim = {**DEFAULT_LIMITS, "price_max": 5000, "areas": [100]}
    assert scoring.check_limits({"price": 6000, "area_id": 157, "beds": 1}, lim, {}) == "Over budget"
    assert scoring.check_limits({"price": 4000, "area_id": 302, "beds": 1}, lim, {}) == "Outside selected areas"

def test_rank_assigns_tiers_by_percentile():
    ls = [{"id": str(i), "price": 3000 + i * 100, "beds": 1, "area_id": 157} for i in range(20)]
    out = scoring.rank(ls, DEFAULT_LIMITS, DEFAULT_WEIGHTS, {})
    tiers = [l["tier"] for l in out["listings"]]
    assert tiers[:2] == [1, 1] and tiers[-1] == 4
```

## Task 5: Chrome tab with passive capture

**Files:** Create `chrome.py`, `scripts/browser_check.py`; test `tests/test_chrome.py` (fake `cdp` and `drain_events`).

**Interfaces:**
- `chrome.HumanCheckTimeout(Exception)`; `chrome.ChromeUnavailable(RuntimeError)`.
- `chrome.is_human_check(title: str, text: str) -> bool` (titles "Access to this page has been denied", text "Press & Hold").
- `chrome.Chrome(mode: str = "user", cdp_url: str | None = None)` with `.open_tab() -> Tab`.
- `chrome.Tab.load(url, capture: Callable[[str], bool], extract_js: str, *, timeout=20.0, settle=3.0, human_wait=300.0, on_event=None) -> dict` returns `{"url", "title", "extracted", "responses": [{"url", "status", "body"}], "human_check": bool}`.
- `Tab.close()`, `Tab.activate()`.

- [ ] Step 1: Test with a fake harness: events for `requestWillBeSent` and `loadingFinished` of a captured URL produce one response; a human-check title calls `on_event("human_check", …)` and, after the fake title changes, the load continues; a never-solved check raises `HumanCheckTimeout`.
- [ ] Step 2: Implement: attach with `Target.createTarget(background=True)` and `Target.attachToTarget(flatten=True)` as in `jev-ultrafast`; `Network.enable`; `Emulation.setFocusEmulationEnabled`; drain events every 100 ms; read bodies with `Network.getResponseBody`; poll `document.readyState` and title every 500 ms.
- [ ] Step 3: `scripts/browser_check.py` serves two local pages (data page with a same-origin fetch, and a human-check page that turns normal after 5 s) and runs `Tab.load` against a dedicated Chrome on port 9333.

## Task 6: StreetEasy source

**Files:** Create `sources/streeteasy.py`; test `tests/test_streeteasy.py` (uses the captured flight fixture and a map-response fixture built from the `GetListingRental` query shape).

**Interfaces:**
- `search_url(limits: dict) -> str`: `https://streeteasy.com/for-rent/nyc/status:open%7Carea:…%7Cprice:MIN-MAX%7Cbeds%3E=N…?sort_by=listed_desc`.
- `is_search_response(url: str) -> bool` (`api-v6.streeteasy.com`).
- `EXTRACT_JS: str` (joins `self.__next_f`).
- `parse_page(flight: str) -> dict` returns `{"listings": [...], "total": int | None}`.
- `parse_map(body: str) -> dict` returns `{"listings": [...], "total": int | None}`.
- `photo_url(key: str) -> str` (`-se_large_800_400.webp`).

- [ ] Step 1: Tests: the fixture yields 14 listings with `id` `se:5116741`, `price` 6395, `net_effective` 5862, `photos` 38 URLs, `lat`/`lon` set; `total` 2872. The URL for `DEFAULT_LIMITS` contains `area:100,` and `price:-7500` and `beds%3E=1` and `available:20261115`.

## Task 7: Zillow source

**Files:** Create `sources/zillow.py`; test `tests/test_zillow.py` (captured `__NEXT_DATA__`).

**Interfaces:**
- `search_url(limits: dict) -> str` (`/homes/for_rent/?searchQueryState=` with `mapBounds` from the selected areas and `filterState` short keys).
- `is_search_response(url) -> bool`; `EXTRACT_JS`.
- `parse_page(text: str) -> dict`; `parse_map(body: str) -> dict`; both return `{"listings": [...], "total": int | None}`.
- Buildings expand to one `building_group` listing per bedroom count with `price_is_from=True`.

- [ ] Step 1: Tests: fixture yields the 6 unit listings and building groups; "21 Chelsea" gives `zb:5XjKmx:1` at 6282 with 34 photos; `417 E 57th St APT 7B` gives `z:` id, price 4745, sqft 608, unit `APT 7B`.

## Task 8: Dedupe, store, photos, vision, Jev

**Files:** Create `dedupe.py`, `store.py`, `photos.py`, `vision.py`, `jev.py`; tests `tests/test_models.py`, `tests/test_store.py`.

**Interfaces:**
- `dedupe.merge(listings: list[dict]) -> list[dict]` (same normalized street and unit, or same beds within 30 m and 3 percent price; StreetEasy wins; keeps `urls`).
- `store.Store(path)`: `upsert(listings) -> tuple[int, int]`, `all() -> list[dict]`, `get(ids) -> list[dict]`, `save_inspection(id, record)`, `inspections(ids) -> dict`, `save_detail(id, detail)`, `get_setting(key, default)`, `set_setting(key, value)`, `add_run(limits, stats) -> int`.
- `photos.choose(listing, k=6) -> list[str]`; `photos.download(urls) -> list[tuple[bytes, str]]` (bytes, mime; disk cache).
- `vision.observe(listing, images) -> dict` (keys `photos, view, light, windows, finishes, condition, space, floor_cues, unit_photos, red_flags`); raises `vision.VisionError`.
- `jev.QUESTIONS: dict`; `jev.judge(listing, observations) -> dict` returns `{"views": {"score": 0..1, "confidence"}, …, "floor_estimate": {...}, "real_unit": {"p": float}, "model", "latency_ms"}`; raises `jev.JevError`.

- [ ] Step 1: Tests with mocked `httpx` post: valid answers parse and normalize by top level; a probability map that does not sum to 1, or a missing question, raises `JevError`; vision JSON wrapped in a list is accepted; non-JSON raises `VisionError`.

## Task 9: Pipeline

**Files:** Create `pipeline.py`; test `tests/test_pipeline.py` (fake Chrome, fake vision, fake Jev).

**Interfaces:**
- `pipeline.Hunter(store, chrome_factory=Chrome, observe=vision.observe, judge=jev.judge, download=photos.download)`.
- `Hunter.search(limits, safety) -> Job`, `Hunter.inspect(ids) -> Job`, `Hunter.deep_look(ids, safety) -> Job`, `Hunter.cancel()`, `Hunter.status() -> dict`, `Hunter.ranked(limits, weights, tiers) -> dict`.
- Job status values: `running`, `waiting_for_user`, `done`, `failed`, `cancelled`. Events: `{"t", "level", "message", "site"?}`.

- [ ] Step 1: Tests: a search with a fake tab returning the fixtures stores listings from both sources and records totals; a human-check timeout on one site keeps the other site's listings and logs a warning; inspect stores judgments and `ranked()` returns pass 2 scores.

## Task 10: Server and UI

**Files:** Create `server.py`, `static/index.html`, `static/app.js`, `static/style.css`; test `tests/test_server.py`.

**Interfaces (HTTP, JSON):**
- `GET /api/config` → `{"criteria", "weights", "limits", "safety", "tiers", "areas": [{"id","name","level","parent_id","borough"}], "amenities", "token"}` (token only in the HTML page, not in this response).
- `POST /api/rank {limits, weights, tiers}` → `{"listings": [...], "excluded": {...}, "counts": {"total", "shown", "inspected"}}`.
- `POST /api/search {limits, safety}`, `POST /api/inspect {ids}`, `POST /api/deep {ids, safety}`, `POST /api/cancel {}`, `POST /api/settings {…}`.
- `GET /api/status` → `{"job": {...} | null, "events": [...]}`.

- [ ] Step 1: Tests: host check returns 403 for a foreign Host; POST without the token returns 403; `/api/rank` returns listings from a seeded store.
- [ ] Step 2: UI: sidebar with limits (rent range, bedrooms, bathrooms, size, move-in window, areas tree, lowest tier, walk minutes, must-haves, sources), weight sliders (0 to 10) per criterion, tier editor, safety settings; main area with a tiered list and a Leaflet map; status bar with the human-check banner.

## Task 11: README and end-to-end check

- [ ] Step 1: README in plain STE: what it does, setup, first run, safety rules, how ranking works, limits.
- [ ] Step 2: Run ruff, pytest, `node --check` on JS, `scripts/browser_check.py`, and a live model check on the fixture listings. Import the captured fixtures as a first dataset so the UI has real data before the first live search.
