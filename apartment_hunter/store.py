"""SQLite cache: listings, photo inspections, detail pages, runs, and UI settings."""

import json
import sqlite3
import threading
from datetime import datetime

# A full record states these even when they are empty (a concession can end); a map record never has them.
FULL_ONLY = ("net_effective", "months_free", "lease_months", "available_at", "sqft")
# Each search states these afresh, even when empty.
ALWAYS = ("unverified_must_have",)

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (id TEXT PRIMARY KEY, source TEXT, data TEXT, first_seen TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS inspections (listing_id TEXT PRIMARY KEY, data TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS details (listing_id TEXT PRIMARY KEY, data TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, started TEXT, finished TEXT,
                                 limits TEXT, stats TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def now():
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)
            self.db.commit()

    def upsert(self, listings):
        """Insert new listings and refresh known ones. Returns (new, updated)."""
        new = updated = 0
        stamp = now()
        with self.lock:
            for listing in listings:
                row = self.db.execute("SELECT data, first_seen FROM listings WHERE id = ?", (listing["id"],)).fetchone()
                if row:
                    old = json.loads(row[0])
                    # A light map record must not erase fields a full record already supplied.
                    merged = {**old, **{k: v for k, v in listing.items() if v not in (None, "", [])}}
                    if listing.get("detail_level") == "full":
                        merged.update({k: listing.get(k) for k in FULL_ONLY if k in listing})
                    merged.update({k: listing[k] for k in ALWAYS if k in listing})
                    if len(old.get("photos") or []) > len(listing.get("photos") or []):
                        merged["photos"], merged["photo_count"] = old["photos"], old.get("photo_count")
                    self.db.execute("UPDATE listings SET data = ?, last_seen = ?, source = ? WHERE id = ?",
                                    (json.dumps(merged), stamp, listing["source"], listing["id"]))
                    updated += 1
                else:
                    self.db.execute("INSERT INTO listings VALUES (?, ?, ?, ?, ?)",
                                    (listing["id"], listing["source"], json.dumps(listing), stamp, stamp))
                    new += 1
                for other in listing.get("merged_ids") or []:
                    if other != listing["id"]:
                        self.db.execute("DELETE FROM listings WHERE id = ?", (other,))
                        self.db.execute("DELETE FROM inspections WHERE listing_id = ?", (other,))
            self.db.commit()
        return new, updated

    def _rows(self, where="", params=()):
        with self.lock:
            rows = self.db.execute(
                "SELECT l.data, l.first_seen, l.last_seen, i.data, d.data FROM listings l "
                "LEFT JOIN inspections i ON i.listing_id = l.id LEFT JOIN details d ON d.listing_id = l.id " + where,
                params).fetchall()
        out = []
        for data, first_seen, last_seen, inspection, detail in rows:
            listing = json.loads(data)
            listing.update(first_seen=first_seen, last_seen=last_seen,
                           inspection=json.loads(inspection) if inspection else None,
                           detail=json.loads(detail) if detail else None)
            out.append(listing)
        return out

    def all(self):
        return self._rows()

    def get(self, ids):
        ids = list(ids)
        if not ids:
            return []
        found = {x["id"]: x for x in self._rows(f"WHERE l.id IN ({','.join('?' * len(ids))})", tuple(ids))}
        return [found[i] for i in ids if i in found]

    def save_inspection(self, listing_id, record):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO inspections VALUES (?, ?, ?)",
                            (listing_id, json.dumps(record), now()))
            self.db.commit()

    def save_detail(self, listing_id, detail):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO details VALUES (?, ?, ?)", (listing_id, json.dumps(detail), now()))
            self.db.commit()

    def get_setting(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))
            self.db.commit()

    def add_run(self, kind, limits):
        with self.lock:
            cursor = self.db.execute("INSERT INTO runs (kind, started, limits, stats) VALUES (?, ?, ?, ?)",
                                     (kind, now(), json.dumps(limits), "{}"))
            self.db.commit()
            return cursor.lastrowid

    def finish_run(self, run_id, stats):
        with self.lock:
            self.db.execute("UPDATE runs SET finished = ?, stats = ? WHERE id = ?", (now(), json.dumps(stats), run_id))
            self.db.commit()

    def last_run(self, kind="search"):
        with self.lock:
            row = self.db.execute("SELECT started, finished, limits, stats FROM runs WHERE kind = ? AND finished "
                                  "IS NOT NULL ORDER BY id DESC LIMIT 1", (kind,)).fetchone()
        if not row:
            return None
        return {"started": row[0], "finished": row[1], "limits": json.loads(row[2]), "stats": json.loads(row[3])}
