"""Pipeline jobs with a fake Chrome and fake models, fed by the real captured pages. Offline."""

import json
import time
from pathlib import Path

import pytest

from apartment_hunter import pipeline
from apartment_hunter.chrome import HumanCheckTimeout
from apartment_hunter.criteria import DEFAULT_LIMITS, DEFAULT_SAFETY, DEFAULT_WEIGHTS
from apartment_hunter.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
SE_FLIGHT = (FIXTURES / "streeteasy_search_flight.txt").read_text()
Z_NEXT = (FIXTURES / "zillow_search_next_data.json").read_text()
MAP = json.dumps({"data": {"searchRentals": {"totalCount": 2872, "edges": [{"node": {
    "id": "999", "areaName": "Chelsea", "bedroomCount": 2, "fullBathroomCount": 1, "halfBathroomCount": 0,
    "geoPoint": {"latitude": 40.7465, "longitude": -73.9990}, "leadMedia": {"photo": {"key": "e" * 32}},
    "price": 6900, "status": "ACTIVE", "street": "200 W 24th St", "unit": "#12A", "urlPath": "/building/x/12a"}}]}}})


class FakeTab:
    def __init__(self, owner):
        self.owner = owner

    def load(self, url, capture, extract_js, human_wait=0, on_event=None, **_):
        self.owner.loads.append(url)
        if "zillow" in url and self.owner.zillow_check:
            on_event("human_check", url)
            raise HumanCheckTimeout("not completed")
        if "streeteasy.com/for-rent" in url:
            return {"extracted": SE_FLIGHT, "responses": [{"url": "https://api-v6.streeteasy.com/", "status": 200,
                                                             "body": MAP}], "human_check": False}
        if "zillow.com" in url and "for_rent" in url or "rentals" in url:
            return {"extracted": Z_NEXT, "responses": [], "human_check": False}
        return {"extracted": {"flight": "", "ldjson": [], "text": "Great light. " * 20,
                              "description": "Sunny renovated corner unit with open views over the rooftops."},
                "responses": [], "human_check": False}

    def close(self):
        pass


class FakeChrome:
    connected = True

    def __init__(self, zillow_check=False):
        self.loads, self.zillow_check = [], zillow_check

    def connect(self):
        pass

    def open_tab(self):
        return FakeTab(self)


def wait(hunter):
    for _ in range(200):
        if not hunter.running():
            return hunter.job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


class Clock:
    """Fake time: sleeping advances the clock at once."""

    def __init__(self):
        self.t, self.slept = 1000.0, []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


def make(tmp_path, chrome=None, **kw):
    fake, clock = chrome or FakeChrome(), Clock()
    hunter = pipeline.Hunter(Store(tmp_path / "t.db"), chrome_factory=lambda: fake, sleep=clock.sleep,
                             clock=clock.now, **kw)
    hunter.fake_clock = clock
    return hunter, fake


def test_search_reads_both_sites_with_one_load_each(tmp_path):
    hunter, fake = make(tmp_path)
    wait_job = hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    job = wait(hunter)
    assert job is wait_job and job.status == "done", job.message
    assert len(fake.loads) == 2
    stats = job.stats
    assert stats["streeteasy"]["found"] == 15 and stats["streeteasy"]["total"] == 2872
    assert stats["zillow"]["found"] > 40
    ranked = hunter.ranked(DEFAULT_LIMITS, DEFAULT_WEIGHTS, {})
    ids = {x["id"] for x in ranked["listings"]}
    assert "se:999" in ids and "se:5116741" in ids
    assert ranked["counts"]["total"] == stats["listings"] and all(x["is_new"] for x in ranked["listings"])


def test_second_search_waits_the_safety_pause(tmp_path):
    hunter, fake = make(tmp_path)
    hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    wait(hunter)
    assert hunter.fake_clock.slept == []
    hunter.search({**DEFAULT_LIMITS, "price_max": 7400}, {**DEFAULT_SAFETY, "pause_s": 20})
    wait(hunter)
    assert 19 <= sum(hunter.fake_clock.slept) <= 21, "the second search must pause before loading a site again"


def test_human_check_timeout_keeps_other_site(tmp_path):
    hunter, fake = make(tmp_path, FakeChrome(zillow_check=True))
    hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    job = wait(hunter)
    assert job.status == "done"
    assert job.stats["zillow"]["error"] == "human check not completed" and job.stats["streeteasy"]["found"] == 15
    assert any(e["level"] == "warn" and "human check" in e["message"] for e in hunter.events)


def test_busy_while_running(tmp_path):
    hunter, _ = make(tmp_path)
    hunter.job = pipeline.Job("search")
    with pytest.raises(pipeline.Busy):
        hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)


def test_price_bands_cover_the_range():
    bands = pipeline.price_bands({"price_min": 0, "price_max": 7500}, 3)
    assert bands[0][0] == 0 and bands[-1][1] == 7500 and len(bands) == 3
    assert all(bands[i][1] < bands[i + 1][0] for i in range(2))
    assert pipeline.price_bands({"price_min": 0, "price_max": 7500}, 1) == [(0, 7500)]


def fake_observe(listing, images):
    return {"view": "skyline", "light": "bright", "windows": "large", "finishes": "modern", "condition": "new",
            "space": "open", "floor_cues": "high", "unit_photos": "actual", "red_flags": "none", "photos": []}, {}


def fake_judge(listing, observations, n):
    return {"views": {"score": 1.0, "confidence": 1.0}, "light": {"score": 0.8, "confidence": 1.0},
            "windows": {"score": 0.6, "confidence": 1.0}, "renovation": {"score": 0.9, "confidence": 1.0},
            "space": {"score": 0.5, "confidence": 1.0}, "floor_estimate": {"score": 1.0, "confidence": 1.0,
            "probabilities": {"0": 0, "1": 0, "2": 0, "3": 1.0}}, "real_unit": {"p": 1.0}}, {"model": "jev"}


def test_inspect_stores_judgments_and_uses_cache(tmp_path):
    hunter, _ = make(tmp_path, observe=fake_observe, judge=fake_judge, download=lambda urls: [(b"x", "image/webp")])
    hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    wait(hunter)
    hunter.inspect(["se:5116741", "se:999"])
    job = wait(hunter)
    assert job.status == "done" and job.stats["inspected"] == 2
    top = {x["id"]: x for x in hunter.ranked(DEFAULT_LIMITS, DEFAULT_WEIGHTS, {})["listings"]}
    assert top["se:5116741"]["scores"]["views"] == 1.0 and top["se:5116741"]["inspection"]["photos_used"] == 1
    hunter.inspect(["se:5116741"])
    assert wait(hunter).stats["cached"] == 1


def test_inspect_failure_is_reported_not_fatal(tmp_path):
    def broken(listing, images):
        raise pipeline.vision.VisionError("bad output")

    hunter, _ = make(tmp_path, observe=broken, judge=fake_judge, download=lambda urls: [(b"x", "image/webp")])
    hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    wait(hunter)
    hunter.inspect(["se:5116741"])
    job = wait(hunter)
    assert job.status == "done" and job.stats["failed"] == 1


def test_deep_look_saves_detail_then_inspects(tmp_path):
    hunter, fake = make(tmp_path, observe=fake_observe, judge=fake_judge,
                        download=lambda urls: [(b"x", "image/webp")])
    hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    wait(hunter)
    hunter.deep_look(["se:5116741"], DEFAULT_SAFETY)
    job = wait(hunter)
    assert job.status == "done", job.message
    row = hunter.store.get(["se:5116741"])[0]
    assert row["detail"]["description"].startswith("Sunny renovated") and row["inspection"]
    assert fake.loads[-1] == "https://streeteasy.com/building/the-suffolk/801"


def test_status_is_running_again_after_a_human_check_timeout(tmp_path):
    hunter, fake = make(tmp_path, FakeChrome(zillow_check=True))
    hunter.search({**DEFAULT_LIMITS, "sources": ["zillow", "streeteasy"]}, DEFAULT_SAFETY)
    job = wait(hunter)
    assert job.status == "done"


def test_safety_pause_survives_a_restart(tmp_path):
    hunter, _ = make(tmp_path)
    hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    wait(hunter)
    again = pipeline.Hunter(hunter.store, chrome_factory=lambda: FakeChrome(), sleep=hunter.fake_clock.sleep,
                            clock=hunter.fake_clock.now)
    assert again.last_load == hunter.last_load and again.last_load


def test_inspect_runs_again_after_a_deep_look_adds_a_description(tmp_path):
    hunter, _ = make(tmp_path, observe=fake_observe, judge=fake_judge, download=lambda urls: [(b"x", "image/webp")])
    hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    wait(hunter)
    hunter.inspect(["se:5116741"])
    wait(hunter)
    hunter.store.save_detail("se:5116741", {"description": "South-facing, renovated in 2025.", "photos": []})
    hunter.inspect(["se:5116741"])
    assert wait(hunter).stats["inspected"] == 1


class SlowChrome(FakeChrome):
    def connect(self):
        time.sleep(0.3)  # Real time, so the test can cancel while the job connects.


def test_cancelled_search_is_not_the_last_search(tmp_path):
    hunter, _ = make(tmp_path, SlowChrome())
    hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    wait(hunter)
    first = hunter.store.last_run("search")
    job = hunter.search({**DEFAULT_LIMITS, "price_max": 5000}, DEFAULT_SAFETY)
    job.cancel.set()
    assert wait(hunter).status == "cancelled"
    assert hunter.store.last_run("search") == first


def test_zillow_listings_carry_unverified_must_haves(tmp_path):
    hunter, _ = make(tmp_path)
    hunter.search({**DEFAULT_LIMITS, "must_have": ["doorman"]}, DEFAULT_SAFETY)
    wait(hunter)
    rows = hunter.store.all()
    assert all(r["unverified_must_have"] == ["Doorman"] for r in rows if r["source"] == "zillow")
    assert all(not r.get("unverified_must_have") for r in rows if r["source"] == "streeteasy")


def test_identical_search_uses_persistent_cache_without_connecting(tmp_path):
    hunter, fake = make(tmp_path)
    hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    wait(hunter)
    original = hunter.store.get(['se:5116741'])[0]
    # A newer observation must not be overwritten by an older cached search.
    hunter.store.upsert([{**original, 'price': 1234}])

    def no_browser():
        pytest.fail('A cached search must not connect to Chrome')

    again = pipeline.Hunter(hunter.store, chrome_factory=no_browser, clock=hunter.fake_clock.now)
    again.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    job = wait(again)
    assert job.status == 'done' and len(fake.loads) == 2
    assert job.stats['streeteasy']['cached_pages'] == 1
    assert job.stats['zillow']['page_loads'] == 0
    assert again.store.get(['se:5116741'])[0]['price'] == 1234
    assert job.stats['updated'] == 0


def test_expired_search_cache_requires_explicit_search(tmp_path):
    hunter, fake = make(tmp_path)
    hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    wait(hunter)
    hunter.fake_clock.t += pipeline.SEARCH_CACHE_SECONDS + 1
    assert len(fake.loads) == 2  # Advancing time alone cannot navigate.
    hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    assert wait(hunter).stats['zillow']['cached_pages'] == 0
    assert len(fake.loads) == 4


def test_human_check_cooldown_survives_restart_and_skips_browser(tmp_path):
    hunter, fake = make(tmp_path, FakeChrome(zillow_check=True))
    hunter.search({**DEFAULT_LIMITS, 'sources': ['zillow']}, DEFAULT_SAFETY)
    assert wait(hunter).stats['zillow']['page_loads'] == 1

    def no_browser():
        pytest.fail('A blocked source must not connect to Chrome')

    again = pipeline.Hunter(hunter.store, chrome_factory=no_browser, clock=hunter.fake_clock.now)
    assert again.status()['source_cooldowns']['zillow']['remaining_s'] == pipeline.SOURCE_COOLDOWN_SECONDS
    again.search({**DEFAULT_LIMITS, 'sources': ['zillow']}, DEFAULT_SAFETY)
    job = wait(again)
    assert 'paused' in job.stats['zillow']['error'] and job.stats['zillow']['page_loads'] == 0
    assert len(fake.loads) == 1


def test_resolved_human_check_stops_extra_price_bands(tmp_path):
    class CheckedTab(FakeTab):
        def load(self, url, *args, on_event=None, **kwargs):
            on_event('human_check', url)
            on_event('human_check_done', url)
            out = super().load(url, *args, on_event=on_event, **kwargs)
            out['human_check'] = True
            return out

    class CheckedChrome(FakeChrome):
        def open_tab(self):
            return CheckedTab(self)

    hunter, fake = make(tmp_path, CheckedChrome())
    hunter.search({**DEFAULT_LIMITS, 'sources': ['streeteasy']}, {**DEFAULT_SAFETY, 'page_loads_per_site': 3})
    job = wait(hunter)
    assert len(fake.loads) == 1 and job.stats['streeteasy']['found'] > 0
    assert 'paused' in job.stats['streeteasy']['error']


def test_block_honors_longer_retry_after_and_keeps_other_source(tmp_path):
    class BlockedTab(FakeTab):
        def load(self, url, *args, **kwargs):
            if 'streeteasy' in url:
                self.owner.loads.append(url)
                raise pipeline.SiteBlocked(429, 3600)
            return super().load(url, *args, **kwargs)

    class BlockedChrome(FakeChrome):
        def open_tab(self):
            return BlockedTab(self)

    hunter, fake = make(tmp_path, BlockedChrome())
    hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    job = wait(hunter)
    assert len(fake.loads) == 2 and job.stats['zillow']['found'] > 0
    assert hunter.cooldowns['streeteasy']['until'] >= hunter.fake_clock.t + 3500
    assert job.stats['streeteasy']['page_loads'] == 1


def test_load_attempt_is_persisted_before_navigation(tmp_path):
    hunter, fake = make(tmp_path)

    class CheckTab(FakeTab):
        def load(self, url, *args, **kwargs):
            assert hunter.store.get_setting('last_load')['streeteasy'] == hunter.fake_clock.t
            return super().load(url, *args, **kwargs)

    fake.open_tab = lambda: CheckTab(fake)
    hunter.search({**DEFAULT_LIMITS, 'sources': ['streeteasy']}, DEFAULT_SAFETY)
    assert wait(hunter).stats['streeteasy']['found'] > 0


def test_deep_look_respects_search_cooldown(tmp_path):
    hunter, fake = make(tmp_path)
    hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    wait(hunter)
    hunter._cool_down('streeteasy', 'human check')
    hunter.deep_look(['se:5116741'], DEFAULT_SAFETY)
    wait(hunter)
    assert len(fake.loads) == 2
    assert hunter.store.get(['se:5116741'])[0]['detail'] is None


def test_unverified_amenities_follow_current_limits_without_a_search(tmp_path):
    hunter, fake = make(tmp_path)
    hunter.search(DEFAULT_LIMITS, DEFAULT_SAFETY)
    wait(hunter)
    result = hunter.ranked({**DEFAULT_LIMITS, 'must_have': ['doorman']}, DEFAULT_WEIGHTS, {})
    zillow = [x for x in result['listings'] if x['source'] == 'zillow']
    assert zillow and all('Doorman' in x['unverified_must_have'] for x in zillow)
    result = hunter.ranked(DEFAULT_LIMITS, DEFAULT_WEIGHTS, {})
    assert all(not x['unverified_must_have'] for x in result['listings'])
    assert len(fake.loads) == 2
