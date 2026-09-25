"""Tab.load against a fake Browser Harness. No real browser, no network."""

import base64
import time

import pytest

from apartment_hunter import chrome


class FakeChrome:
    """Scripted CDP: page state per poll, network events, response bodies."""

    def __init__(self, states, events, bodies):
        self.states, self.events, self.bodies = list(states), list(events), bodies
        self.calls, self.activated, self.navigated = [], False, False

    def cdp(self, method, session_id=None, **params):
        self.calls.append(method)
        if method == "Target.createTarget":
            return {"targetId": "T"}
        if method == "Target.attachToTarget":
            return {"sessionId": "S"}
        if method == "Target.activateTarget":
            self.activated = True
            return {}
        if method == "Page.navigate":
            self.navigated = True
            return {"frameId": "MAIN"}
            return {}
        if method == "Network.getResponseBody":
            body = self.bodies[params["requestId"]]
            return {"body": base64.b64encode(body.encode()).decode(), "base64Encoded": True}
        if method == "Runtime.evaluate":
            expression = params["expression"]
            if "readyState" in expression:
                state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
                return {"result": {"value": state}}
            if expression == "location.href":
                return {"result": {"value": "https://example.test/search"}}
            return {"result": {"value": "EXTRACTED"}}
        return {}

    def drain(self):
        if not self.navigated:  # Real events arrive only after navigation.
            return []
        out, self.events = self.events, []
        return out


def ev(method, request_id, **params):
    return {"method": method, "session_id": "S", "params": {"requestId": request_id, **params}}


def test_captures_the_pages_own_response_and_extracts():
    events = [
        ev("Network.requestWillBeSent", "1", request={"url": "https://api.example.test/"}),
        ev("Network.requestWillBeSent", "2", request={"url": "https://ads.example.test/x"}),
        ev("Network.responseReceived", "1", response={"status": 200}),
        ev("Network.loadingFinished", "1"),
        {"method": "Network.loadingFinished", "session_id": "OTHER", "params": {"requestId": "2"}},
    ]
    loaded = ["complete", "Results", "listings", False, "https://example.test/search"]
    fake = FakeChrome([loaded], events, {"1": '{"ok": true}'})
    tab = chrome.Tab(fake)
    out = tab.load("https://example.test/search", lambda u: "api.example" in u, "x", settle=0.2, timeout=5)
    assert out["responses"] == [{"url": "https://api.example.test/", "status": 200, "body": '{"ok": true}'}]
    assert out["extracted"] == "EXTRACTED" and out["human_check"] is False
    assert "Network.enable" in fake.calls and "Emulation.setFocusEmulationEnabled" in fake.calls
    assert fake.calls.count("Page.navigate") == 1


def test_waits_for_the_user_at_a_human_check():
    check = ["complete", "Access to this page has been denied", "Press & Hold to confirm you are a human", True, "https://x/"]
    states = [check, check, check, ["complete", "Results", "ok", False, "https://x/"]]
    fake = FakeChrome(states, [], {})
    seen = []
    out = chrome.Tab(fake).load("https://example.test/", lambda u: False, "x", settle=0.2, timeout=5,
                                human_wait=10, on_event=lambda kind, url: seen.append(kind))
    assert out["human_check"] is True and fake.activated
    assert seen == ["human_check", "human_check_done"]
    assert fake.calls.count("Page.navigate") == 1  # Never re-navigates.


def test_unsolved_human_check_times_out():
    check = ["complete", "Access to this page has been denied", "Press & Hold", True, "https://x/"]
    fake = FakeChrome([check], [], {})
    with pytest.raises(chrome.HumanCheckTimeout):
        chrome.Tab(fake).load("https://example.test/", lambda u: False, "x", settle=0.1, timeout=5, human_wait=0.6)


def test_is_human_check_text_and_title():
    assert chrome.is_human_check("Access to this page has been denied", "")
    assert chrome.is_human_check("StreetEasy", "Press & Hold to confirm you are a human (and not a bot).")
    assert not chrome.is_human_check("Manhattan NY Apartments for Rent", "1,479 results")


def test_old_blank_page_does_not_count_as_loaded():
    blank = ["complete", "", "", False, "about:blank"]
    loading = ["loading", "Results", "", False, "https://example.test/search"]
    done = ["complete", "Results", "ok", False, "https://example.test/search"]
    fake = FakeChrome([blank, loading, loading, done], [], {})
    started = time.monotonic()
    chrome.Tab(fake).load("https://example.test/search", lambda u: False, "x", settle=0.6, timeout=10)
    # Loaded only at the fourth poll (after about 1.5 s), then the settle time.
    assert time.monotonic() - started >= 2.0


@pytest.mark.parametrize('status', [403, 429])
def test_main_document_block_never_retries(status):
    loaded = ['complete', 'Denied', 'Try later', False, 'https://example.test/search']
    events = [ev('Network.responseReceived', 'doc', type='Document', frameId='MAIN',
                 response={'url': 'https://example.test/search', 'status': status, 'headers': {'Retry-After': '3600'}})]
    fake = FakeChrome([loaded], events, {})
    with pytest.raises(chrome.SiteBlocked) as error:
        chrome.Tab(fake).load('https://example.test/search', lambda u: False, 'x', settle=0)
    assert error.value.retry_after == 3600
    assert fake.calls.count('Page.navigate') == 1


def test_listing_api_block_is_detected_but_ads_are_ignored():
    loaded = ['complete', 'Results', 'listings', False, 'https://example.test/search']
    for url, blocked in [('https://ads.test/x', False), ('https://api.example.test/', True)]:
        events = [ev('Network.responseReceived', 'xhr', type='XHR',
                     response={'url': url, 'status': 429})]
        fake = FakeChrome([loaded], events, {})
        tab = chrome.Tab(fake)
        if blocked:
            with pytest.raises(chrome.SiteBlocked):
                tab.load('https://example.test/search', lambda u: 'api.example' in u, 'x', settle=0)
        else:
            assert tab.load('https://example.test/search', lambda u: 'api.example' in u, 'x', settle=0)['extracted']


def test_403_human_check_still_waits_for_user():
    check = ['complete', 'Access to this page has been denied', 'Press & Hold', True, 'https://example.test/']
    loaded = ['complete', 'Results', 'ok', False, 'https://example.test/']
    events = [ev('Network.responseReceived', 'doc', type='Document', frameId='MAIN',
                 response={'url': 'https://example.test/', 'status': 403})]
    fake = FakeChrome([check, loaded], events, {})
    result = chrome.Tab(fake).load('https://example.test/', lambda u: False, 'x', settle=0)
    assert result['human_check'] and fake.activated and fake.calls.count('Page.navigate') == 1


def test_retry_after_http_date_and_invalid_header(monkeypatch):
    monkeypatch.setattr(chrome.time, 'time', lambda: 0)
    assert chrome.retry_after_seconds({'retry-after': 'Thu, 01 Jan 1970 01:00:00 GMT'}) == 3600
    assert chrome.retry_after_seconds({'Retry-After': 'bad'}) == 0
