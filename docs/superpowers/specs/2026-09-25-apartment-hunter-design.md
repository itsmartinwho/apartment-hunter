# Apartment Hunter: design

Date: 2026-09-25. Status: approved by the author for overnight build (the user asked for autonomous work).

## Goal

One local web page where you set hard limits and priorities, click Search, and get a ranked, tiered list and a map of New York rentals from StreetEasy and Zillow. You change limits and priorities at any time. Weight changes re-rank instantly, with no new page loads.

## What the user said (source of truth)

- Search StreetEasy and Zillow. Reuse `jev-ultrafast` to control Chrome.
- Use Jev for fast, multi-dimensional judgments. Use a cheap, fast vision model for judgments that need photos.
- Criteria: price, neighborhood tier, subway distance, size, bedrooms, views, window size and light, floor height, renovation (new versus old), and similar.
- UI: sliders for limits (minimum, maximum, move-in date), levers for importance, and a mode that sets only limits and optimizes everything else.
- Output: links in tiers from best to worst, with photo and location, and a map with the tiers.
- Two passes: cheap deterministic data for a long list, then vision for a shortlist.
- Every option has a schema with rankings.
- Defaults from the user: single, $300,000 income, 1 bedroom or more, Manhattan plus close Brooklyn, move-in late October to mid-November 2026.
- Safety: do not get the user's IP or Chrome flagged. Never log in to any account.

## Findings that shape the design

### Bot protection

Both sites use PerimeterX. In a Chrome tab under CDP control, the first page load passes and later loads show a "Press & Hold" human check. A custom API request from the page also triggered the check.

Rules that follow:

1. The tool never solves, clicks, or hides from a human check. It brings the tab to the front and waits for the user.
2. The tool never sends its own API requests to StreetEasy or Zillow. It reads only data that a normal page load already delivers: the server-rendered page data and the responses to the page's own requests.
3. One page load per site per search, by default. More loads only when the user allows them.
4. At least 20 seconds between page loads on one site. Detail pages are opt-in and paced.
5. No login. No background searches. A search runs only when the user clicks Search.
6. No stealth changes: no user-agent changes, no fingerprint changes, no cookie resets, no proxies.
7. The tool uses its own named Browser Harness daemon, which opens its own blank tab. It never attaches to the user's open tabs.

### StreetEasy data (verified on a live page)

- The search page embeds Next.js flight data (`self.__next_f`). It holds 14 full listings per page: id, area name, rent, net effective rent, months free, lease term, bedrooms, bathrooms, size, available date, map point, all photo keys, unit, URL, new development flag.
- The same data holds the full area list: 349 areas with IDs, parents, and encoded boundary polygons.
- The page's own map request (`searchRentals`, `perPage: 500`) returns up to 500 listings with map point, rent, bedrooms, bathrooms, area, unit, URL, and one lead photo. The tool captures this response from Chrome's network events.
- URL filters: `status:open`, `price:MIN-MAX`, `area:ID,ID`, `beds>=N`, `beds<=N`, or `beds:N-M`, `baths>=N`, `amenities:...`, `pets:allowed`, `available:YYYYMMDD`, `sqft>=N`, `sort_by:listed_desc`.
- Photos come from `photos.zillowstatic.com`. The photo CDN has no human check.

### Zillow data (verified on a live page)

- The search page embeds `__NEXT_DATA__` with 41 results per page. In Manhattan, most results are buildings with a "from" rent for each bedroom count. All results have photo keys.
- `searchQueryState` in the URL carries filters. Short keys: `mp` (rent), `beds`, `baths`, `sqft`, `built`, `lau` (in-unit laundry), `eaa` (elevator), `dish`, `os` (outdoor space), `pet`, `cat`, `sdog`, `ldog`, `rad` (move-in date), `sort`.
- The page may also request map results. The tool captures them when they arrive; the embedded 41 results are the fallback.

### Models (verified)

- Jev (`jev-latest`, text only): 6 Score and Noul questions in one request take about 370 ms and cost about $0.00006.
- Vision: `google/gemini-2.5-flash-lite` on OpenRouter. Six photos take about 3 seconds and cost about $0.0005. It returns structured observations.
- Composition: the vision model describes what is visible. Jev turns the description into calibrated Scores. Code combines Scores with the user's weights.

## Architecture

```text
UI (browser, 127.0.0.1:8777)
  │  limits, weights, tiers ─────────────► re-rank in the page (no server call)
  │  Search / Inspect / Deep look
  ▼
server.py (stdlib HTTP, loopback, token)
  ▼
pipeline.py ── job thread, progress events
  ├── pass 1: sources/streeteasy.py, sources/zillow.py ── chrome.py (Browser Harness)
  │            enrich.py (subway, neighborhood, floor, size estimate) ── geo.py, data/*.json
  │            dedupe, store.py (SQLite)
  └── pass 2: photos.py (CDN) → vision.py (OpenRouter) → jev.py (TypeSafe)
scoring.py and criteria.py: one schema for every criterion, used by server and UI
```

### Units and their jobs

| Unit | Job |
| --- | --- |
| `rsc.py` | Parse Next.js flight data into Python objects |
| `chrome.py` | Own a background tab, navigate, capture the page's own responses, detect human checks, wait for the user |
| `sources/streeteasy.py` | Build search URLs; read embedded listings, the area list, and map responses |
| `sources/zillow.py` | Build search URLs; read embedded results and map responses; expand buildings into bedroom groups |
| `geo.py` | Distance, polyline decoding, point in polygon |
| `enrich.py` | Nearest subway, lines nearby, neighborhood, tier, floor from unit, size estimate |
| `criteria.py` | The criteria schema: id, label, pass, default weight, levels |
| `scoring.py` | Criterion scores from 0 to 1, composite score, tiers |
| `photos.py` | Choose and download photos from the CDN |
| `vision.py` | Ask the vision model for structured observations |
| `jev.py` | Ask Jev the Score and Noul questions; validate answers |
| `store.py` | SQLite cache of listings, observations, and judgments |
| `pipeline.py` | Run pass 1, pass 2, and deep look as jobs with progress |
| `server.py` | HTTP API and static files |
| `static/` | The UI: limits, weights, tier editor, tiered list, map |

## Listing schema

Every listing is a flat JSON object:

```text
id            "se:5116741" | "z:452682722" | "zb:5XjKmx:1" (Zillow building, 1-bedroom group)
source        "streeteasy" | "zillow"
kind          "unit" | "building_group"
url, title, street, unit, zip
lat, lon
area_id, area_name, borough      (StreetEasy area taxonomy)
price, price_is_from, net_effective, months_free, lease_months
beds, baths, sqft, sqft_estimated
available_at  "YYYY-MM-DD" or null
floor, floor_source ("unit" | "vision" | null), is_penthouse
building_type, is_new_development, furnished
photos        list of photo URLs; photo_count
subway        {station, lines, distance_m, walk_min}, lines_nearby
detail        null or {description, amenities, ...} after a deep look
first_seen, last_seen
```

## Criteria

All criterion scores run from 0 (worst) to 1 (best). Unknown values count as 0.5 and the UI marks them.

| Id | Pass | Source | Default weight |
| --- | --- | --- | --- |
| `price` | 1 | rent within the user's range; net effective optional | 8 |
| `neighborhood` | 1 | user tier: 1.0, 0.65, 0.3, 0.0 | 10 |
| `subway` | 1 | walk minutes to the nearest station: 1 at 3 min or less, 0 at 15 min or more | 5 |
| `lines` | 1 | distinct lines within an 8-minute walk | 2 |
| `size` | 1 | size in sqft, or an estimate from bedrooms and bathrooms | 6 |
| `bedrooms` | 1 | bedroom count above the minimum | 3 |
| `floor` | 1, then 2 | floor from the unit number; Jev estimate from photos when unknown | 4 |
| `move_in` | 1 | available date against the move-in window | 3 |
| `deal` | 1 | discount from months free | 2 |
| `views` | 2 | Jev Score from vision observations | 5 |
| `light` | 2 | Jev Score | 7 |
| `windows` | 2 | Jev Score | 4 |
| `renovation` | 2 | Jev Score | 6 |
| `space` | 2 | Jev Score | 4 |

A Jev Noul (`real_unit`) says whether photos show the actual unit. Pass 2 scores shrink toward 0.5 when this probability is low. This matters for Zillow buildings, where photos often show amenities or model units.

Composite score: the weighted mean of criterion scores. Tiers come from rank within the filtered list: Tier 1 is the top 10 percent, Tier 2 the next 20 percent, Tier 3 the next 30 percent, and Tier 4 the rest.

## Presets and plain-language priorities

Six weight presets (Balanced, Best value, Location, Light and views, Space, New and renovated) set all sliders at once. Balanced is the mode where the user sets only limits and the tool weighs everything else.

A text box takes a plain-language description. Jev answers one Score per criterion ("How much does the renter care about natural light?") on four levels: does not matter, not mentioned, matters somewhat, top priority. Code maps the levels to weights 0, unchanged, 6, and 10, and skips answers with confidence below 0.45.

## Hard limits

Rent range, bedrooms range, minimum bathrooms, minimum size, move-in window, areas, lowest allowed tier, maximum walk to the subway, no ground floor, must-have amenities, sources, include Zillow building groups. The tool applies each limit at the source URL when the source supports it. It also applies all limits in the UI, so a tighter limit takes effect at once. A looser limit needs a new search, and the UI says so.

## Flows

### Pass 1: Search

1. For each enabled source, build one URL from the limits.
2. Open a background tab in Chrome, turn on network events, and load the URL.
3. For up to 20 seconds, read network events every 100 ms and keep the site's own search responses.
4. If a human check appears, bring the tab to the front and show a banner. Wait up to 5 minutes for the user, then continue.
5. Read the embedded page data and the captured responses. Normalize to the listing schema.
6. Enrich, remove duplicates across sources, save, and return the long list.

### Pass 2: Inspect

1. Take the top N listings (default 25) under the current limits and weights.
2. Download up to 6 photos each from the CDN.
3. Ask the vision model for observations, 6 listings at a time.
4. Ask Jev the pass 2 questions, one request per listing.
5. Cache results by listing and photo set, and re-rank.

### Deep look (opt-in)

The user picks listings. The tool loads each detail page, one at a time, at least 30 seconds apart, and stops at the first human check until the user solves it. It reads the description, all photos, and amenities, then runs pass 2 again for those listings.

## Errors

- No Chrome connection: the UI shows the fix ("Click Allow in Chrome").
- Human check: banner and wait; after 5 minutes, skip that site and keep the other results.
- Missing map response: use the embedded results and report the smaller count.
- Model errors: keep pass 1 results; mark pass 2 as failed for that listing; no silent retries of page loads.
- Invalid model output: reject it; never guess values.

## Testing

- Offline tests with real captured pages (StreetEasy flight data, Zillow page data, vision output). No paid API calls in tests.
- A local fixture site served by the tool's server imitates both sites, including a human-check page, for a browser test without touching the real sites.
- Live checks only for the models (cheap) tonight. The first live search runs when the user is present.

## Out of scope for v1

Commute time to a work address, saved searches with alerts, listings from other sites, automatic applications, and any messages to agents.
