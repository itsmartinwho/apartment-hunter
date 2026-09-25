"""Load the search pages captured on 2026-09-25 into the local database, so the UI has real listings before
the first live search. No listing site is contacted. --inspect N also runs pass 2 (paid model calls, cents).

uv run python scripts/import_sample.py --inspect 25
"""

import argparse
import time
from pathlib import Path

from apartment_hunter import areas, dedupe, enrich
from apartment_hunter.config import load_env, settings
from apartment_hunter.criteria import DEFAULT_LIMITS, DEFAULT_WEIGHTS
from apartment_hunter.pipeline import Hunter
from apartment_hunter.sources import streeteasy, zillow
from apartment_hunter.store import Store

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", type=int, default=0, help="Inspect the photos of the top N listings")
    args = parser.parse_args()
    load_env()
    home = settings()["home"]
    home.mkdir(parents=True, exist_ok=True)
    store = Store(home / "hunter.db")
    se = streeteasy.parse_page((FIXTURES / "streeteasy_search_flight.txt").read_text())
    z = zillow.parse_page((FIXTURES / "zillow_search_next_data.json").read_text())
    listings = dedupe.merge([enrich.enrich(x) for x in se["listings"] + z["listings"]])
    run = store.add_run("sample", {"source": "pages captured 2026-09-25"})
    new, updated = store.upsert(listings)
    store.finish_run(run, {"new": new, "updated": updated})
    print(f"Imported {len(listings)} listings ({new} new) into {home / 'hunter.db'}")
    if args.inspect:
        hunter = Hunter(store)
        tiers = store.get_setting("tiers") or areas.DEFAULT_TIERS
        top = hunter.ranked(DEFAULT_LIMITS, DEFAULT_WEIGHTS, tiers)["listings"]
        ids = [x["id"] for x in top[: args.inspect]]
        hunter.inspect(ids)
        while hunter.running():
            time.sleep(0.5)
        print(hunter.job.message)
        for event in list(hunter.events)[-10:]:
            print(" ", event["level"], event["message"])


if __name__ == "__main__":
    main()
