"""Jobs: search (pass 1), inspect (pass 2), and deep look. One job at a time, in a background thread.

Pass 1 loads one search page per site (or a few price bands, if the user allows more loads) and reads only
what those pages deliver. Pass 2 downloads photos from the CDN, asks the vision model to describe them, and
asks Jev to judge. Page loads on one site are always at least `pause_s` seconds apart.
"""

import itertools
import math
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import dedupe, enrich, jev, photos, scoring, vision
from .chrome import Cancelled, Chrome, HumanCheckTimeout, SiteBlocked, launch_dedicated
from .config import settings
from .criteria import clean_limits, clean_safety, clean_weights
from .sources import streeteasy, zillow
from .store import now

SOURCES = {"streeteasy": streeteasy, "zillow": zillow}
PHOTOS_PER_LISTING = 6
WORKERS = 6
SEARCH_CACHE_SECONDS = 600
SOURCE_COOLDOWN_SECONDS = 900
SEARCH_CACHE_ENTRIES = 24


class Busy(RuntimeError):
    """Another job is running."""


class SourceCoolingDown(RuntimeError):
    """A previous challenge or block prevents another page load. Never auto-retry after cooling down."""


class Job:
    _ids = itertools.count(1)

    def __init__(self, kind):
        self.id = next(Job._ids)
        self.kind = kind
        self.status = "running"
        self.message = "Starting"
        self.site = None
        self.started = now()
        self.finished = None
        self.progress = {"done": 0, "total": 0}
        self.stats = {}
        self.page_loads = {}
        self.cancel = threading.Event()

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "status": self.status, "message": self.message, "site": self.site,
                "started": self.started, "finished": self.finished, "progress": dict(self.progress),
                "stats": self.stats}


def default_chrome():
    s = settings()
    if s["chrome_mode"] == "dedicated":
        launch_dedicated(s["chrome_cdp_url"], s["home"] / "chrome")
    return Chrome(s["chrome_mode"], s["chrome_cdp_url"])


def price_bands(limits, count):
    """Split the rent range into `count` bands so each page load returns a different slice."""
    high = limits.get("price_max") or 10_000
    low = max(limits.get("price_min") or 0, 0)
    if count <= 1:
        return [(low, high)]
    start = max(low, int(high * 0.35))
    width = (high - start) / count
    edges = [low] + [int(start + width * i) for i in range(1, count)] + [high]
    return [(edges[i] if i == 0 else edges[i] + 1, edges[i + 1]) for i in range(count)]


class Hunter:
    def __init__(self, store, chrome_factory=default_chrome, observe=vision.observe, judge=jev.judge,
                 download=photos.download, sleep=time.sleep, clock=time.time):
        self.store = store
        self.clock = clock
        self.chrome_factory = chrome_factory
        self.observe, self.judge, self.download, self.sleep = observe, judge, download, sleep
        self._chrome = None
        self.job = None
        self.events = deque(maxlen=300)
        self.lock = threading.Lock()
        # Wall-clock times of the last page load per site, kept in the database so a restart keeps the pause.
        self.last_load = dict(store.get_setting("last_load") or {})
        self.cooldowns = dict(store.get_setting("source_cooldowns") or {})
        self.search_cache = dict(store.get_setting("search_cache") or {})

    # Status and control.

    def log(self, message, level="info", site=None):
        self.events.append({"t": now(), "level": level, "message": message, "site": site})

    def status(self):
        chrome = self._chrome
        return {
            "job": self.job.to_dict() if self.job else None,
            "events": list(self.events)[-60:],
            "chrome": {"connected": bool(chrome and chrome.connected), "mode": settings()["chrome_mode"]},
            "source_cooldowns": {site: {**item, "remaining_s": math.ceil(item["until"] - self.clock())}
                                 for site, item in self.cooldowns.items() if item["until"] > self.clock()},
        }

    def running(self):
        return bool(self.job and self.job.finished is None)

    def cancel(self):
        if self.running():
            self.job.cancel.set()
            self.job.message = "Stopping after the current step"

    def _start(self, kind, target, *args):
        with self.lock:
            if self.running():
                raise Busy(f"A {self.job.kind} job is running. Wait or cancel it.")
            job = Job(kind)
            self.job = job
        threading.Thread(target=self._run, args=(job, target, args), daemon=True).start()
        return job

    def _run(self, job, target, args):
        try:
            target(job, *args)
            job.status = "cancelled" if job.cancel.is_set() else "done"
        except Exception as error:  # Report every failure; never retry a page load.
            job.status = "failed"
            job.message = str(error)[:300] or type(error).__name__
            self.log(job.message, "error", job.site)
        finally:
            job.finished = now()
            if job.status == "done":
                self.log(job.message)

    def chrome(self, job):
        """Connect at the start of every Chrome job: a healthy connection returns at once, a dead one is replaced."""
        first = self._chrome is None or not self._chrome.connected
        if first:
            job.message = "Connecting to Chrome. If Chrome asks \"Allow remote debugging?\", click Allow."
        chrome = self._chrome or self.chrome_factory()
        self._chrome = chrome
        chrome.connect()
        if first:
            self.log(f"Connected to Chrome ({settings()['chrome_mode']} mode)")
        return chrome

    def _pace(self, site, pause_s, job):
        """Keep page loads on one site at least pause_s seconds apart, across jobs."""
        while not job.cancel.is_set():
            wait = self.last_load.get(site, -1e9) + pause_s - self.clock()
            if wait <= 0:
                return
            job.message = f"Safety pause: next {SOURCES[site].LABEL} page load in {int(wait) + 1} s"
            self.sleep(min(1.0, wait))

    def _human(self, job, module, kind):
        if kind == "human_check":
            self._cool_down(module.SITE, "human check")
            job.status = "waiting_for_user"
            job.message = (f"{module.LABEL} asks you to confirm you are human. Chrome shows that tab now. "
                           "Complete the check there; the job continues by itself.")
            self.log(f"{module.LABEL} showed a human check. Waiting for you.", "warn", module.SITE)
        else:
            job.status = "running"
            job.message = f"Thank you. Reading {module.LABEL}."
            self.log(f"{module.LABEL} human check completed.", site=module.SITE)

    def _cool_down(self, site, reason, seconds=SOURCE_COOLDOWN_SECONDS):
        until = max(self.clock() + max(SOURCE_COOLDOWN_SECONDS, seconds),
                    self.cooldowns.get(site, {}).get("until", 0))
        self.cooldowns[site] = {"until": until, "reason": reason}
        self.store.set_setting("source_cooldowns", self.cooldowns)

    def _check_cooldown(self, site):
        item = self.cooldowns.get(site, {})
        remaining = item.get("until", 0) - self.clock()
        if remaining > 0:
            raise SourceCoolingDown(f"{SOURCES[site].LABEL} paused for {math.ceil(remaining / 60)} more min "
                                    f"after {item['reason']}. Saved listings remain available. "
                                    "Click Search later; there is no automatic retry.")

    def _cached_search(self, url):
        item = self.search_cache.get(url)
        return item if item and 0 <= self.clock() - item["captured_at"] < SEARCH_CACHE_SECONDS else None

    def _cache_search(self, url, listings, total):
        self.search_cache[url] = {"captured_at": self.clock(), "listings": listings, "total": total}
        self.search_cache = dict(sorted(self.search_cache.items(), key=lambda x: x[1]["captured_at"])
                                 [-SEARCH_CACHE_ENTRIES:])
        self.store.set_setting("search_cache", self.search_cache)

    def _load(self, job, chrome, module, url, capture, extract_js, pause_s, human_wait, settle=4.0):
        self._check_cooldown(module.SITE)
        self._pace(module.SITE, pause_s, job)
        if job.cancel.is_set():
            return None
        job.site = module.SITE
        chrome = chrome or self.chrome(job)
        if job.cancel.is_set():
            return None
        tab = chrome.open_tab()
        # Record BEFORE navigation too: a server crash must not erase an attempted load.
        self.last_load[module.SITE] = self.clock()
        self.store.set_setting("last_load", self.last_load)
        job.page_loads[module.SITE] = job.page_loads.get(module.SITE, 0) + 1
        saw_human = False

        def on_event(kind, _url):
            nonlocal saw_human
            saw_human = saw_human or kind == "human_check"
            self._human(job, module, kind)

        try:
            out = tab.load(url, capture, extract_js, human_wait=human_wait, settle=settle,
                           on_event=on_event, cancelled=job.cancel.is_set)
            saw_human = saw_human or out.get("human_check", False)
        except Cancelled:
            return None
        except HumanCheckTimeout:
            saw_human = True
            raise
        except SiteBlocked as error:
            self._cool_down(module.SITE, str(error), error.retry_after)
            raise
        finally:
            if saw_human:
                self._cool_down(module.SITE, "human check")
            job.status = "running"
            self.last_load[module.SITE] = self.clock()
            self.store.set_setting("last_load", self.last_load)
            tab.close()
        if out.get("dropped_events"):
            self.log(f"{module.LABEL}: the page was very busy, so some network events may be missing", "warn",
                     module.SITE)
        return out

    # Pass 1.

    def search(self, limits, safety):
        return self._start("search", self._search, clean_limits(limits), clean_safety(safety))

    def _search(self, job, limits, safety):
        run = self.store.add_run("search", limits)
        sites = [s for s in SOURCES if s in limits["sources"]]
        if not sites:
            raise ValueError("Turn on at least one source")
        job.progress = {"done": 0, "total": len(sites) * safety["page_loads_per_site"]}
        found, fresh, stats = [], [], {}
        for site in sites:
            module = SOURCES[site]
            listings, total, loads, cached = {}, None, 0, 0
            try:
                for low, high in price_bands(limits, safety["page_loads_per_site"]):
                    if job.cancel.is_set():
                        break
                    band = {**limits, "price_min": low, "price_max": high}
                    url = module.search_url(band)
                    item = self._cached_search(url)
                    if item:
                        cached += 1
                        got, band_total = item["listings"], item["total"]
                        self.log(f"{module.LABEL}: reused search captured less than 10 minutes ago", site=site)
                    else:
                        job.message = f"Loading one {module.LABEL} page (${low:,}–${high:,})"
                        out = self._load(job, None, module, url, module.is_search_response,
                                         module.EXTRACT_JS, safety["pause_s"], safety["human_wait_s"], module.SETTLE)
                        if out is None:
                            break
                        loads += 1
                        got, band_total = self._read_search(module, out)
                        self._cache_search(url, got, band_total)
                    job.progress["done"] += 1
                    flags = module.unverified(limits) if hasattr(module, "unverified") else []
                    for listing in got:
                        record = {**listing, "unverified_must_have": flags}
                        listings.setdefault(listing["id"], record)
                        if not item:
                            fresh.append(record)
                    total = (total or 0) + band_total if band_total is not None else total
                stats[site] = {"found": len(listings), "total": total, "page_loads": loads, "cached_pages": cached}
                self.log(f"{module.LABEL}: read {len(listings):,} of {total:,} listings" if total else
                         f"{module.LABEL}: read {len(listings):,} listings", site=site)
            except HumanCheckTimeout:
                stats[site] = {"found": len(listings), "total": total, "page_loads": loads,
                               "error": "human check not completed"}
                self.log(f"{module.LABEL}: the human check was not completed in time. Kept the other results.",
                         "warn", site)
            except (SiteBlocked, SourceCoolingDown) as error:
                stats[site] = {"found": len(listings), "total": total, "page_loads": loads,
                               "cached_pages": cached, "error": str(error)}
                self.log(str(error), "warn", site)
            except Exception as error:
                stats[site] = {"found": len(listings), "total": total, "page_loads": loads, "error": str(error)[:200]}
                self.log(f"{module.LABEL}: {error}", "error", site)
            stats[site]["page_loads"] = job.page_loads.get(site, 0)
            stats[site]["cached_pages"] = cached
            if self.cooldowns.get(site, {}).get("until", 0) > self.clock():
                stats[site]["cooldown_until"] = self.cooldowns[site]["until"]
            found.extend(listings.values())
        merged = dedupe.merge([enrich.enrich(x) for x in found])
        # Cached captures must not refresh last_seen or overwrite a more recent capture of the same apartment.
        new, updated = self.store.upsert(dedupe.merge([enrich.enrich(x) for x in fresh]))
        stats.update(new=new, updated=updated, listings=len(merged))
        if not job.cancel.is_set():  # A cancelled search is not a "last search" to compare limits against.
            self.store.finish_run(run, stats)
        job.stats = stats
        job.site = None
        job.message = f"Search done: {len(merged):,} listings, {new:,} new"

    def _read_search(self, module, out):
        try:
            page = module.parse_page(out.get("extracted"))
        except Exception as error:  # A changed page format must not hide the map data.
            self.log(f"{module.LABEL}: could not read the page data ({error})", "warn", module.SITE)
            page = {"listings": [], "total": None}
        listings = {x["id"]: x for x in page["listings"]}
        total = page["total"]
        for response in out.get("responses") or []:
            status = response.get("status") or 200
            if status >= 400:
                self.log(f"{module.LABEL} map data answered HTTP {status}; using the page data only", "warn",
                         module.SITE)
                continue
            try:
                parsed = module.parse_map(response.get("body"))
            except Exception as error:
                self.log(f"{module.LABEL}: skipped one response ({error})", "warn", module.SITE)
                continue
            for listing in parsed["listings"]:
                listings.setdefault(listing["id"], listing)  # Full page records win over light map records.
            total = parsed["total"] or total
        if not listings and not out.get("extracted"):
            raise RuntimeError("the page had no listing data")
        return list(listings.values()), total

    # Pass 2.

    def inspect(self, ids):
        return self._start("inspect", self._inspect, list(dict.fromkeys(ids)))

    def _inspect(self, job, ids):
        todo, cached, skipped = [], 0, 0
        for listing in self.store.get(ids):
            urls = photos.choose(listing, PHOTOS_PER_LISTING)
            if not urls:
                skipped += 1
                continue
            description = (listing.get("detail") or {}).get("description") or ""
            digest = photos.photo_set_hash(urls + [description])
            if (listing.get("inspection") or {}).get("photo_hash") == digest:
                cached += 1
                continue
            todo.append((listing, urls, digest))
        job.progress = {"done": 0, "total": len(todo)}
        job.message = f"Inspecting photos of {len(todo)} listings"
        ok = failed = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(self._inspect_one, job, *item): item[0] for item in todo}
            for future in as_completed(futures):
                listing = futures[future]
                try:
                    if future.result():
                        ok += 1
                except (vision.VisionError, jev.JevError) as error:
                    failed += 1
                    self.log(f"{listing.get('title')}: {error}", "warn")
                job.progress["done"] += 1
        job.stats = {"inspected": ok, "failed": failed, "cached": cached, "no_photos": skipped}
        job.message = f"Inspect done: {ok} inspected, {cached} already done, {failed} failed"

    def _inspect_one(self, job, listing, urls, digest):
        if job.cancel.is_set():
            return False
        images = self.download(urls)
        if not images:
            raise vision.VisionError("No photo could be downloaded")
        observations, vision_meta = self.observe(listing, images)
        judgments, jev_meta = self.judge(listing, observations, len(images))
        self.store.save_inspection(listing["id"], {
            "photo_hash": digest, "photos_used": len(images), "observations": observations,
            "judgments": judgments, "vision": vision_meta, "jev": jev_meta, "created": now(),
        })
        return True

    # Deep look.

    def deep_look(self, ids, safety):
        return self._start("deep", self._deep, list(dict.fromkeys(ids)), clean_safety(safety))

    def _deep(self, job, ids, safety):
        listings = [x for x in self.store.get(ids) if x.get("url")][: safety["deep_look_max"]]
        job.progress = {"done": 0, "total": len(listings)}
        read = []
        for listing in listings:
            module = SOURCES[listing["source"]]
            job.message = f"Deep look: {listing.get('title')}"
            try:
                out = self._load(job, None, module, listing["url"], lambda _url: False, module.DETAIL_JS,
                                 safety["deep_look_pause_s"], safety["human_wait_s"])
            except HumanCheckTimeout:
                self.log(f"{module.LABEL}: the human check was not completed. Deep look stopped.", "warn",
                         module.SITE)
                break
            except Exception as error:  # One bad page must not stop the others or skip pass 2.
                self.log(f"Deep look: {listing.get('title')}: {error}", "warn", module.SITE)
                job.progress["done"] += 1
                continue
            if out is None:
                break
            try:
                detail = module.parse_detail(out.get("extracted"))
            except Exception as error:
                self.log(f"Deep look: {listing.get('title')}: could not read the page ({error})", "warn")
                job.progress["done"] += 1
                continue
            detail["read_at"] = now()
            self.store.save_detail(listing["id"], detail)
            read.append(listing["id"])
            job.progress["done"] += 1
            self.log(f"Deep look: {listing.get('title')}: {len(detail['photos'])} photos, "
                     f"{'a' if detail.get('description') else 'no'} description")
        job.site = None
        if read and not job.cancel.is_set():
            self._inspect(job, read)
        job.message = f"Deep look done: {len(read)} listings read"

    # Ranking.

    def ranked(self, limits, weights, tiers):
        limits, weights = clean_limits(limits), clean_weights(weights)
        listings = self.store.all()
        result = scoring.rank(listings, limits, weights, tiers or {})
        last = self.store.last_run("search")
        since = last["started"] if last else None
        for listing in result["listings"]:
            listing["is_new"] = bool(since and listing.get("first_seen", "") >= since)
            module = SOURCES.get(listing.get("source"))
            # These labels describe the CURRENT limits, even when no new search/page load was needed.
            listing["unverified_must_have"] = module.unverified(limits) if hasattr(module, "unverified") else []
        result["counts"] = {"total": len(listings), "shown": len(result["listings"]),
                            "inspected": sum(1 for x in result["listings"] if x.get("inspection"))}
        return result
