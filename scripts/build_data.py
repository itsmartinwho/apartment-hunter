"""Build apartment_hunter/data/*.json from open data and a captured StreetEasy page.

uv run python scripts/build_data.py --mta mta_stations.csv --flight tests/fixtures/streeteasy_search_flight.txt

MTA stations: https://data.ny.gov/api/views/39hk-dx4f/rows.csv?accessType=DOWNLOAD
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from apartment_hunter import rsc
from apartment_hunter.config import DATA

BOROUGHS = {"M": "Manhattan", "Bk": "Brooklyn", "Q": "Queens", "Bx": "Bronx", "SI": "Staten Island"}


def stations(path):
    rows = list(csv.DictReader(open(path, newline="")))
    lines_by_complex = defaultdict(set)
    for row in rows:
        lines_by_complex[row["Complex ID"]].update(row["Daytime Routes"].split())
    out = []
    for row in rows:
        out.append(
            {
                "stop_id": row["GTFS Stop ID"],
                "complex_id": row["Complex ID"],
                "name": row["Stop Name"],
                "lines": sorted(lines_by_complex[row["Complex ID"]], key=lambda x: (len(x), x)),
                "lat": float(row["GTFS Latitude"]),
                "lon": float(row["GTFS Longitude"]),
                "borough": BOROUGHS.get(row["Borough"], row["Borough"]),
            }
        )
    return out


def areas(path):
    table = rsc.rows(Path(path).read_text())
    for kind, value in table.values():
        if kind == "text" and value.startswith('[{"id":"1","name":"NYC and NJ"'):
            raw = json.loads(value)
            break
    else:
        raise SystemExit("Area list not found in the flight data")
    return [
        {
            "id": int(a["id"]),
            "name": a["name"],
            "short": a["short"],
            "level": a["level"],
            "parent_id": int(a["parentId"] or 0),
            "borough": a["borough"]["name"],
            "boundary": (a.get("mapCoordinates") or {}).get("encodedBoundary"),
        }
        for a in raw
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mta", required=True)
    parser.add_argument("--flight", required=True)
    args = parser.parse_args()
    DATA.mkdir(exist_ok=True)
    s, a = stations(args.mta), areas(args.flight)
    (DATA / "subway_stations.json").write_text(json.dumps(s, separators=(",", ":")))
    (DATA / "streeteasy_areas.json").write_text(json.dumps(a, separators=(",", ":")))
    print(f"{len(s)} subway stops, {len(a)} StreetEasy areas")


if __name__ == "__main__":
    main()
