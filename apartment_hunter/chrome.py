"""Chrome through Browser Harness, as in jev-ultrafast: one owned background tab per page load.

The tab reads only what a normal page load delivers: the embedded page data and the responses to the
page's own requests. It never answers a human check. When a site shows one, the tab comes to the front
and the load waits for the user.
"""

import base64
import os
import subprocess
import time
import urllib.request
from urllib.parse import urlparse

HUMAN_TITLES = ("access to this page has been denied", "just a moment", "attention required", "are you a robot",
                "verify you are human", "security check")
HUMAN_TEXT = ("press & hold", "press and hold", "confirm you are a human", "not a bot", "verify you are human",
              "complete the security check")
STATE_JS = """(() => [document.readyState, document.title,
  document.body ? document.body.innerText.slice(0, 800) : '',
  !!document.querySelector('meta[content="px-captcha"], #px-captcha, [id^="px-captcha"], ' +
    'iframe[src*="captcha"], iframe[title*="Human verification"]'), location.href])()"""
NAVIGATE_TIMEOUT = 30  # Page.navigate answers when the navigation commits; slow first bytes are normal.
CONNECT_WAIT = 180  # Seconds to wait for the user to click Allow on Chrome's popup.
USER_DAEMON = "apartment-hunter-user"


class ChromeUnavailable(RuntimeError):
    """Chrome cannot be reached or did not allow the connection."""


class HumanCheckTimeout(RuntimeError):
    """A site showed a human check and the user did not complete it in time."""


class Cancelled(RuntimeError):
    """The user cancelled the job during a page load."""


def launch_dedicated(cdp_url, profile_dir):
    """Start a separate Chrome profile with a debug port, unless one already answers on that port."""
    try:
        urllib.request.urlopen(cdp_url.rstrip("/") + "/json/version", timeout=1)
        return
    except OSError:
        pass
    port = urlparse(cdp_url).port or 9333
    profile_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["open", "-na", "Google Chrome", "--args", f"--remote-debugging-port={port}",
                      f"--user-data-dir={profile_dir}", "--no-first-run", "--no-default-browser-check", "about:blank"])
    for _ in range(60):
        time.sleep(0.25)
        try:
            urllib.request.urlopen(cdp_url.rstrip("/") + "/json/version", timeout=1)
            return
        except OSError:
            continue
    raise ChromeUnavailable(f"The dedicated Chrome did not start on {cdp_url}")


def is_human_check(title, text, px_meta=False):
    title, text = (title or "").lower(), (text or "").lower()
    return px_meta or any(h in title for h in HUMAN_TITLES) or any(h in text for h in HUMAN_TEXT)


class Chrome:
    """mode "user": your running Chrome (Chrome asks you to Allow once per connection).
    mode "dedicated": a separate Chrome profile started with --remote-debugging-port (no Allow popup).

    Both modes use a named Browser Harness daemon. A named daemon opens its own blank tab; the default daemon
    would attach to your first open tab and turn on automation domains there, which could be a listing tab."""

    def __init__(self, mode="user", cdp_url=None):
        # Browser Harness reads these at import time, so set them before the first import.
        for key in ("BU_CDP_URL", "BU_CDP_WS"):
            os.environ.pop(key, None)
        if mode == "dedicated":
            os.environ["BU_NAME"] = "apartment-hunter"
            os.environ["BU_CDP_URL"] = cdp_url or "http://127.0.0.1:9333"
        else:
            os.environ["BU_NAME"] = USER_DAEMON
        os.environ.setdefault("BH_TAB_MARKER", "0")
        from browser_harness import helpers
        from browser_harness.admin import ensure_daemon

        self.mode = mode
        self._helpers = helpers
        self._ensure = ensure_daemon
        self.connected = False

    def connect(self):
        """Idempotent: a healthy daemon returns at once; a stale one is replaced (Chrome may ask to Allow)."""
        try:
            self._ensure(wait=CONNECT_WAIT)
        except Exception as error:  # Harness errors carry the fix, for example "click Allow".
            self.connected = False
            raise ChromeUnavailable(str(error)) from None
        self.connected = True

    def cdp(self, method, session_id=None, timeout=None, **params):
        try:
            if timeout:
                return self._helpers.cdp(method, session_id=session_id, _response_timeout=timeout, **params)
            return self._helpers.cdp(method, session_id=session_id, **params)
        except (ConnectionError, FileNotFoundError, OSError):
            self.connected = False
            raise

    def drain(self):
        return self._helpers.drain_events()

    def open_tab(self):
        return Tab(self)


class Tab:
    def __init__(self, chrome):
        self.chrome = chrome
        self.target = chrome.cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
        self.session = chrome.cdp("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]
        self.call("Network.enable", maxTotalBufferSize=100_000_000, maxResourceBufferSize=50_000_000)
        # Keep the page rendering like a focused tab without switching the visible tab (as jev-ultrafast does).
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)

    def call(self, method, timeout=None, **params):
        return self.chrome.cdp(method, session_id=self.session, timeout=timeout, **params)

    def evaluate(self, expression):
        try:
            result = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        except Exception:
            return None
        if result.get("exceptionDetails"):
            return None
        return (result.get("result") or {}).get("value")

    def state(self):
        value = self.evaluate(STATE_JS)
        return value if isinstance(value, list) and len(value) == 5 else [None, "", "", False, ""]

    def activate(self):
        try:
            self.chrome.cdp("Target.activateTarget", targetId=self.target)
        except Exception:
            pass

    def close(self):
        try:
            self.chrome.cdp("Target.closeTarget", targetId=self.target)
        except Exception:
            pass

    def _body(self, request_id):
        try:
            body = self.call("Network.getResponseBody", requestId=request_id)
        except Exception:
            return None
        text = body.get("body", "")
        return base64.b64decode(text).decode("utf-8", "replace") if body.get("base64Encoded") else text

    def load(self, url, capture, extract_js, *, timeout=25.0, settle=4.0, human_wait=300.0, on_event=None,
             cancelled=None):
        """Navigate once and collect: the extracted page data plus the bodies of the page's own requests
        whose URL passes capture(url). Waits for the user at a human check; never retries a navigation."""
        emit = on_event or (lambda *_: None)
        stop = cancelled or (lambda: False)
        self.chrome.drain()
        self.call("Page.navigate", timeout=NAVIGATE_TIMEOUT, url=url)
        pending, responses, done_ids = {}, [], set()
        self.dropped_events = False
        human, human_deadline = False, None
        deadline = time.monotonic() + timeout
        loaded_at, checked_at = None, 0.0
        title = ""
        while True:
            now = time.monotonic()
            if stop():
                raise Cancelled("Cancelled during a page load")
            events = self.chrome.drain()
            if len(events) >= 490:  # The daemon keeps 500 events; older ones may be gone.
                self.dropped_events = True
            for event in events:
                if event.get("session_id") != self.session:
                    continue
                method, params = event.get("method"), event.get("params") or {}
                request_id = params.get("requestId")
                if request_id in done_ids:
                    continue
                if method == "Network.requestWillBeSent" and capture(params.get("request", {}).get("url", "")):
                    pending[request_id] = {"url": params["request"]["url"], "status": None}
                elif method == "Network.responseReceived" and (request_id in pending or capture(
                        params.get("response", {}).get("url", ""))):
                    # Also start here, in case requestWillBeSent fell out of the daemon's buffer.
                    response = params.get("response") or {}
                    item = pending.setdefault(request_id, {"url": response.get("url", ""), "status": None})
                    item["status"] = response.get("status")
                elif method == "Network.loadingFinished" and request_id in pending:
                    item = pending.pop(request_id)
                    done_ids.add(request_id)
                    body = self._body(request_id)
                    if body is not None:
                        responses.append({**item, "body": body})
                elif method == "Network.loadingFailed" and request_id in pending:
                    pending.pop(request_id)
                    done_ids.add(request_id)
            if now - checked_at >= 0.5:
                checked_at = now
                ready, title, text, px_meta, href = self.state()
                if is_human_check(title, text, px_meta):
                    if human_deadline is None:
                        human = True
                        human_deadline = now + human_wait
                        self.activate()
                        emit("human_check", url)
                    if now > human_deadline:
                        raise HumanCheckTimeout(f"The human check at {url} was not completed in time.")
                    loaded_at, deadline = None, now + timeout
                else:
                    if human_deadline is not None:
                        human_deadline = None
                        emit("human_check_done", url)
                    if ready != "complete" or href in ("", "about:blank"):
                        loaded_at = None  # Still the old blank page, or the new page is still loading.
                    elif loaded_at is None:
                        loaded_at = now
            if loaded_at is not None and now - loaded_at >= settle and not pending:
                break
            if now > deadline:
                break
            time.sleep(0.1)
        for request_id, item in list(pending.items()):  # A lost loadingFinished: the body may still be there.
            body = self._body(request_id)
            if body:
                responses.append({**item, "body": body})
        return {
            "url": self.evaluate("location.href") or url,
            "title": title,
            "extracted": self.evaluate(extract_js),
            "responses": responses,
            "human_check": human,
            "dropped_events": self.dropped_events,
        }
