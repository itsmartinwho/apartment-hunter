"""The real server and pipeline with a fake Chrome that serves the pages captured on 2026-09-25.

Use it to test the UI, including Search, preference previews and the human-check banner, without contacting
listing sites or paid models. It uses a separate database, so your real data stays untouched.

uv run python scripts/fake_sites_server.py        # http://127.0.0.1:8778
"""

import secrets
import shutil
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from apartment_hunter import server, vision
from apartment_hunter.config import load_env, settings
from apartment_hunter.pipeline import Hunter
from apartment_hunter.store import Store

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
PORT = 8778


def demo_preferences(text, limits, weights, tiers):
    """A fixed demo answer for UI checks, clearly labeled; never calls a model."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Describe your search first")
    if text == 'simulate error':
        raise ValueError('Simulated model error. Nothing changed.')
    changes = [
        {"group": "limits", "id": "price_max", "from": limits["price_max"], "to": 6500},
        {"group": "limits", "id": "areas", "from": limits["areas"], "to": [115, 157]},
        {"group": "weights", "id": "light", "from": weights["light"], "to": 10},
    ]
    return {"limits": {**limits, "price_max": 6500, "areas": [115, 157]},
            "weights": {**weights, "light": 10}, "tiers": tiers,
            "changes": [c for c in changes if c["from"] != c["to"]],
            "notes": ["Local demo response: simulated preferences; no model calls."], "latency_ms": 0}


def no_paid_models(*args, **kwargs):
    raise vision.VisionError("Photo inspection is disabled in the offline demo")


class DemoApp(server.App):
    def post(self, path, body):
        if path == "/api/interpret":
            raise ValueError("The legacy priority model is disabled in the offline demo")
        return super().post(path, body)


class FakeTab:
    def __init__(self, owner):
        self.owner = owner

    def load(self, url, capture, extract_js, human_wait=0, on_event=None, **_):
        time.sleep(2)
        if "zillow.com" in url and not self.owner.checked:
            self.owner.checked = True
            on_event("human_check", url)
            time.sleep(6)  # Pretend the user needs six seconds for the check.
            on_event("human_check_done", url)
        if "streeteasy.com/for-rent" in url:
            return {"extracted": (FIXTURES / "streeteasy_search_flight.txt").read_text(), "responses": [],
                    "human_check": False}
        if "zillow.com" in url:
            return {"extracted": (FIXTURES / "zillow_search_next_data.json").read_text(), "responses": [],
                    "human_check": True}
        return {"extracted": {"flight": "", "ldjson": [], "description": "A fake detail page.", "text": ""},
                "responses": [], "human_check": False}

    def close(self):
        pass


class FakeChrome:
    connected = True

    def __init__(self):
        self.checked = False

    def connect(self):
        time.sleep(1)

    def open_tab(self):
        return FakeTab(self)


def main():
    load_env()
    folder = Path(tempfile.mkdtemp(prefix="hunter-fake-"))
    real = settings()["home"] / "hunter.db"
    if real.exists():
        shutil.copy(real, folder / "hunter.db")
    store = Store(folder / "hunter.db")
    fake = FakeChrome()
    hunter = Hunter(store, chrome_factory=lambda: fake, observe=no_paid_models, judge=no_paid_models,
                    download=no_paid_models)
    app = DemoApp(store, hunter, interpret_preferences=demo_preferences)
    token = secrets.token_urlsafe(16)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), server.make_handler(app, token, PORT))
    print(f"Fake-sites server: http://127.0.0.1:{PORT} (database copy in {folder})", flush=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
