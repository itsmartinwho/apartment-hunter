"""HTTP API: host and token checks, config, ranking. Offline; uses a real loopback server."""

import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from apartment_hunter import enrich, server
from apartment_hunter.pipeline import Hunter
from apartment_hunter.store import Store


@pytest.fixture
def running(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert([enrich.enrich({"id": "se:1", "source": "streeteasy", "kind": "unit", "title": "1 Bank St #4B",
                                 "street": "1 Bank St", "unit": "#4B", "lat": 40.7359, "lon": -74.0036, "price": 4800,
                                 "beds": 1, "baths": 1, "photos": [f"https://photos.zillowstatic.com/fp/{i}.webp"
                                                                     for i in range(20)]})])
    app = server.App(store, Hunter(store, chrome_factory=lambda: None))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = server.make_handler(app, "tok", port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield port
    httpd.shutdown()


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    data = json.dumps(body).encode() if body is not None else None
    base = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"}
    conn.request(method, path, body=data, headers={**base, **(headers or {})})
    response = conn.getresponse()
    return response.status, response.read().decode()


def test_foreign_host_is_rejected(running):
    status, _ = request(running, "GET", "/api/config", headers={"Host": "evil.test"})
    assert status == 403


def test_post_needs_the_token(running):
    status, _ = request(running, "POST", "/api/rank", {"limits": {}})
    assert status == 403
    status, _ = request(running, "POST", "/api/rank", {"limits": {}},
                        {"X-Hunter-Token": "tok", "Origin": "https://evil.test"})
    assert status == 403


def test_config_lists_criteria_areas_and_stations(running):
    status, text = request(running, "GET", "/api/config")
    config = json.loads(text)
    assert status == 200 and {c["id"] for c in config["criteria"]} >= {"price", "views", "light"}
    assert any(a["name"] == "West Village" for a in config["areas"]) and len(config["stations"]) > 100
    assert config["limits"]["price_max"] == 7500 and "question" not in config["criteria"][-1]


def test_rank_returns_trimmed_listings(running):
    status, text = request(running, "POST", "/api/rank", {"limits": {}, "weights": {}, "tiers": {}},
                           {"X-Hunter-Token": "tok"})
    data = json.loads(text)
    assert status == 200 and data["counts"]["shown"] == 1
    listing = data["listings"][0]
    assert listing["tier"] == 1 and len(listing["photos"]) == 8 and listing["photo_count"] == 20
    assert listing["area_name"] == "West Village" and listing["scores"]["neighborhood"] == 1.0


def test_settings_round_trip(running):
    status, _ = request(running, "POST", "/api/settings", {"weights": {"price": 2}, "tiers": {"157": 3, "x": 9}},
                        {"X-Hunter-Token": "tok"})
    assert status == 200
    config = json.loads(request(running, "GET", "/api/config")[1])
    assert config["weights"]["price"] == 2 and config["tiers"]["157"] == 3 and "x" not in config["tiers"]
    assert config["tiers"]["144"] == 4  # Saved tiers merge over the defaults.


def test_index_gets_the_token(running, tmp_path, monkeypatch):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text('<meta name="hunter-token" content="__TOKEN__">')
    monkeypatch.setattr(server, "STATIC", static)
    status, text = request(running, "GET", "/")
    assert status == 200 and 'content="tok"' in text


def test_bad_json_is_a_400(running):
    conn = http.client.HTTPConnection("127.0.0.1", running, timeout=5)
    conn.request("POST", "/api/rank", body=b"{not json", headers={"Host": f"127.0.0.1:{running}",
                                                                  "X-Hunter-Token": "tok"})
    assert conn.getresponse().status == 400
