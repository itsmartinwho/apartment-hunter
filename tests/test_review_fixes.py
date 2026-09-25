"""Regression tests for the backend review findings of 2026-09-25. Offline."""

import base64
import json

import pytest

from apartment_hunter import chrome, dedupe, server
from apartment_hunter.sources import streeteasy, zillow
from apartment_hunter.store import Store


def unit(id_, source, unit_label, **kw):
    return {"id": id_, "source": source, "kind": "unit", "street": "311 11th Avenue", "unit": unit_label, "beds": 1,
            "price": 5495, "lat": 40.7525, "lon": -74.0060, "photos": [], "urls": {source: id_}, **kw}


def test_dedupe_never_merges_two_different_unit_numbers():
    out = dedupe.merge([unit("se:1", "streeteasy", "#1119"), unit("z:2", "zillow", "Apt 2808", price=5500)])
    assert {x["id"] for x in out} == {"se:1", "z:2"}


def test_dedupe_location_fallback_still_works_without_a_unit():
    out = dedupe.merge([unit("se:1", "streeteasy", "#1119"), unit("z:2", "zillow", None, price=5500)])
    assert [x["id"] for x in out] == ["se:1"]


def test_store_full_record_clears_an_ended_concession(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert([unit("se:1", "streeteasy", "#1", net_effective=4400, months_free=1, detail_level="full")])
    store.upsert([unit("se:1", "streeteasy", "#1", net_effective=None, months_free=0, detail_level="full")])
    row = store.get(["se:1"])[0]
    assert row["net_effective"] is None and row["months_free"] == 0


def test_store_map_record_keeps_full_fields(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert([unit("se:1", "streeteasy", "#1", net_effective=4400, detail_level="full")])
    store.upsert([unit("se:1", "streeteasy", "#1", detail_level="map")])
    assert store.get(["se:1"])[0]["net_effective"] == 4400


def test_store_removes_rows_merged_into_another(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert([unit("z:2", "zillow", "Apt 7B")])
    store.upsert([unit("se:1", "streeteasy", "#7B", merged_ids=["se:1", "z:2"])])
    assert [x["id"] for x in store.all()] == ["se:1"]


@pytest.mark.parametrize("body", ["[1, 2]", '"text"', "null", '{"data": []}', '{"data": {"searchRentals": []}}'])
def test_map_parsers_skip_bodies_that_are_not_objects(body):
    assert streeteasy.parse_map(body) == {"listings": [], "total": None}
    assert zillow.parse_map(body)["listings"] == []


def test_zillow_flags_must_haves_its_url_cannot_filter():
    assert zillow.unverified({"must_have": ["doorman", "elevator", "laundry_building"]}) == [
        "Doorman", "Laundry in building"]


def test_server_cleans_tiers_from_requests():
    assert server.clean_tiers({"157": "2", "x": 1, "144": 7, "302": 1}) == {"157": 2, "302": 1}


class Fake:
    def __init__(self, events, state):
        self.events, self.state, self.navigated = events, state, False

    def cdp(self, method, session_id=None, timeout=None, **params):
        if method == "Target.createTarget":
            return {"targetId": "T"}
        if method == "Target.attachToTarget":
            return {"sessionId": "S"}
        if method == "Page.navigate":
            self.navigated = True
            assert timeout and timeout >= 30  # A slow first byte must not fail the navigation call.
            return {}
        if method == "Network.getResponseBody":
            return {"body": base64.b64encode(b'{"ok": 1}').decode(), "base64Encoded": True}
        if method == "Runtime.evaluate":
            if "readyState" in params["expression"]:
                return {"result": {"value": self.state}}
            return {"result": {"value": None}}
        return {}

    def drain(self):
        if not self.navigated:
            return []
        out, self.events = self.events, []
        return out


def test_capture_starts_on_response_when_the_request_event_was_lost():
    events = [{"method": "Network.responseReceived", "session_id": "S",
               "params": {"requestId": "9", "response": {"url": "https://api.example.test/", "status": 200}}},
              {"method": "Network.loadingFinished", "session_id": "S", "params": {"requestId": "9"}}]
    fake = Fake(events, ["complete", "Results", "ok", False, "https://example.test/"])
    out = chrome.Tab(fake).load("https://example.test/", lambda u: "api.example" in u, "x", settle=0.2)
    assert out["responses"] == [{"url": "https://api.example.test/", "status": 200, "body": '{"ok": 1}'}]


def test_cancel_stops_a_page_load():
    fake = Fake([], ["loading", "", "", False, "https://example.test/"])
    with pytest.raises(chrome.Cancelled):
        chrome.Tab(fake).load("https://example.test/", lambda u: False, "x", cancelled=lambda: True)


def test_px_overlay_counts_as_a_human_check():
    assert chrome.is_human_check("StreetEasy", "1,479 results", px_meta=True)


def test_body_json_helpers_are_json():
    assert json.loads('{"ok": 1}') == {"ok": 1}


def test_store_refreshes_unverified_flags_each_search(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert([unit("z:2", "zillow", "Apt 7B", unverified_must_have=["Doorman"])])
    store.upsert([unit("z:2", "zillow", "Apt 7B", unverified_must_have=[])])
    assert store.get(["z:2"])[0]["unverified_must_have"] == []
