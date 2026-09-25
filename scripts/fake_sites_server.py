"""The real server and pipeline with a fake Chrome that serves the pages captured on 2026-09-25.

Use it to test the whole UI, including Search and the human-check banner, without contacting StreetEasy or
Zillow. It uses a separate database, so your real data stays untouched.

uv run python scripts/fake_sites_server.py        # http://127.0.0.1:8778
"""

import secrets
import shutil
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from apartment_hunter import server
from apartment_hunter.config import load_env, settings
from apartment_hunter.pipeline import Hunter
from apartment_hunter.store import Store

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
PORT = 8778


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
    hunter = Hunter(store, chrome_factory=lambda: fake)
    app = server.App(store, hunter)
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
