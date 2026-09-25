# Apartment Hunter

Apartment Hunter ranks New York rentals from StreetEasy and Zillow by your own priorities. You set hard limits and weights on one local page. The tool reads the listings through your Chrome, adds data it computes itself (subway walk, neighborhood tier, floor), and checks photos with a vision model and Jev. The result is a tiered list and a map.

## Start

```bash
uv sync
uv run hunt
```

The page opens at http://127.0.0.1:8777. When you click Search for the first time, Chrome asks "Allow remote debugging?". Click **Allow**. Chrome asks again only when the connection restarts, for example after Chrome restarts. The tool works in its own background tabs; it never attaches to your open tabs. While it is connected, it keeps one blank background tab open for the connection.

`.env` holds the keys (copied from `jev-ultrafast`): `TYPESAFE_API_KEY` for Jev and `TEXT_MODEL_API_KEY` (OpenRouter) for the vision model. See `.env.example`.

To check the keys, Jev, and the Chrome connection:

```bash
uv run hunt --check
```

## How to use it

1. Set your **limits** in the left panel: rent range, bedrooms, bathrooms, size, move-in window, areas, lowest tier, walk to the subway, must-haves, and sources.
2. Click **Search**. The tool loads one StreetEasy page and one Zillow page in a background tab of your Chrome. This takes about 30 seconds.
3. Move the **priority** sliders. The list and the map re-rank at once. No page loads. To let the tool optimize everything inside your limits, click the **Balanced** preset. Other presets: Best value, Location, Light and views, Space, New and renovated. You can also type what matters in plain words ("I work from home, so light matters most; I bike, so the subway does not matter") and click **Set priorities**. Jev reads the text and moves the sliders in about 0.4 seconds.
4. Click **Inspect top N**. The tool downloads photos of the top listings and asks the vision model and Jev to judge views, light, window size, renovation, and space. This takes about 20 seconds for 25 listings and costs about 2 cents.
5. For a listing you like, click **Deep look**. The tool opens that listing page, reads the description and all photos, and inspects it again.
6. Edit the **neighborhood tiers** to match your taste. Tier 1 is best.

The database already holds 67 real listings from pages captured on 2026-09-25, with 28 inspected, so the page shows results before your first search.

## Safety rules

StreetEasy and Zillow check for bots. In a Chrome tab under automation, the first page load passes and later loads can show a "Press & Hold" human check. The tool follows these rules:

- It never solves or hides from a human check. When one appears, it brings that tab to the front and waits up to 5 minutes for you. If you do not complete it, the tool skips that site and keeps the other results.
- It sends no requests of its own to StreetEasy or Zillow. It reads the data that a normal page load already contains, plus the responses to the page's own requests.
- It loads one page per site per search by default, and it waits at least 20 seconds between page loads on one site. You can allow up to 3 loads per site (price bands) in **Safety**.
- It never logs in, and it never searches in the background. A search runs only when you click Search.
- Photos come from the public photo CDN, which has no human check.

## What each pass uses

| Pass | Data | Criteria |
| --- | --- | --- |
| 1 (Search) | StreetEasy: 14 full listings from the page plus up to 500 from the page's own map request. Zillow: 41 results from the page (most are buildings with "from" prices), plus map results if the page loads them. | price, neighborhood tier, subway walk, subway lines nearby, size, bedrooms, floor (from the unit number), move-in fit, free months |
| 2 (Inspect) | Up to 6 photos per listing from the CDN | views, natural light, window size, new or renovated, spacious feel, floor (when the unit number says nothing) |

Every criterion score runs from 0 to 1. An unknown value counts as 0.5. The composite score is the weighted mean. Tier 1 is the top 10 percent of the listings that pass your limits, tier 2 the next 20 percent, tier 3 the next 30 percent, and tier 4 the rest.

Jev is text only. The vision model (`google/gemini-2.5-flash-lite`) describes what the photos show. Jev turns that description into calibrated Scores. A Jev yes/no question checks whether the photos show the actual unit; when it is unlikely, the photo scores count less. Photo scores of Zillow building groups always count less, because their photos show the building, not your unit.

## Limits of v1

- With one page load, a search returns up to about 500 StreetEasy listings and about 41 to 500 Zillow results. The status line shows how many matched in total. Narrow the limits, or allow more page loads in **Safety**, to see more.
- Most StreetEasy map listings have one photo until you run a Deep look.
- Zillow buildings appear as one entry per bedroom count with a "from" rent. A Deep look reads the building page, but it does not split the building into units yet.
- The detail-page readers (Deep look) are written defensively, because those pages were not captured live. If a Deep look finds no description, the listing keeps its search data.
- Zillow's search cannot filter a doorman or laundry in the building. When those are must-haves, Zillow listings show "Not verified" for them.
- The move-in window filters StreetEasy at the source. Zillow search results rarely state a date, so the tool checks Zillow dates only when it knows them.
- Commute time to an address is not in v1.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `CHROME_MODE` | `user` | `user`: your Chrome (asks you to Allow). `dedicated`: a separate Chrome profile in `~/.apartment-hunter/chrome`, with no Allow popup. |
| `VISION_MODEL` | `google/gemini-2.5-flash-lite` | Any OpenRouter model with image input |
| `TYPESAFE_MODEL` | `jev-latest` | Jev model |
| `HUNTER_PORT` | `8777` | Local port |
| `HUNTER_HOME` | `~/.apartment-hunter` | Database and photo cache |

## Development

Before committing captured pages, run `uv run python scripts/sanitize_fixtures.py`. Public page payloads can
include the listing sites' Google Maps keys; these are unrelated to your model API credentials and are
replaced with inert, same-length placeholders. The fixture hygiene test guards against reintroducing them.

```bash
uv run ruff check .
uv run pytest
node --check apartment_hunter/static/app.js
uv run python scripts/browser_check.py
```

Tests are offline and use real pages captured on 2026-09-25 (`tests/fixtures`). `scripts/browser_check.py` checks the Chrome capture and the human-check wait against local pages only. `scripts/import_sample.py --inspect 25` loads the captured pages into the database and inspects the top 25 (paid model calls, about 2 cents). `scripts/build_data.py` rebuilds the subway and area data. `scripts/fake_sites_server.py` runs the real server with a fake Chrome on port 8778, so you can test the whole page, including Search and the human-check banner, without contacting StreetEasy or Zillow.

| File | Job |
| --- | --- |
| [chrome.py](apartment_hunter/chrome.py) | Owned background tab, passive capture, human-check wait |
| [sources/streeteasy.py](apartment_hunter/sources/streeteasy.py) | StreetEasy URLs and readers |
| [sources/zillow.py](apartment_hunter/sources/zillow.py) | Zillow URLs and readers |
| [enrich.py](apartment_hunter/enrich.py) | Subway, neighborhood, floor, size estimate |
| [criteria.py](apartment_hunter/criteria.py) | Criteria, limits, and safety schema |
| [scoring.py](apartment_hunter/scoring.py) | Scores, limits, composite, tiers |
| [vision.py](apartment_hunter/vision.py) | Photo observations |
| [jev.py](apartment_hunter/jev.py) | Jev questions and answer checks |
| [pipeline.py](apartment_hunter/pipeline.py) | Search, inspect, and deep look jobs |
| [server.py](apartment_hunter/server.py) | Local HTTP API and the `hunt` command |
| [static/](apartment_hunter/static) | The page: limits, priorities, tiers, list, map |

Data sources: subway stations from [MTA Subway Stations](https://data.ny.gov/Transportation/MTA-Subway-Stations/39hk-dx4f) (NY Open Data); neighborhood names and boundaries from StreetEasy's own area list.
