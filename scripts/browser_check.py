"""Real-Chrome check of Tab.load against local pages only. It never contacts StreetEasy or Zillow.

uv run python scripts/browser_check.py            # starts a throwaway Chrome profile on port 9333
uv run python scripts/browser_check.py --user     # uses your running Chrome (Chrome may ask you to Allow)
"""

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from apartment_hunter.chrome import Chrome

PORT = 8799
NODE = {"id": "1", "price": 4000, "status": "ACTIVE"}
MAP = {"data": {"searchRentals": {"totalCount": 1, "edges": [{"node": NODE}]}}}
SEARCH = """<!doctype html><title>Results</title><body>3 results
<script>self.__next_f=[[1,'1:{"ok":true}\\n']];
setTimeout(() => fetch('/api/map', {method: 'POST', body: '{}'}), 800);</script></body>"""
CHECK = """<!doctype html><title>Access to this page has been denied</title>
<body>Press &amp; Hold to confirm you are a human (and not a bot).
<script>setTimeout(() => { document.title = 'Results'; document.body.textContent = 'ok';
  self.__next_f = [[1, '1:{"after":true}\\n']]; fetch('/api/map', {method: 'POST', body: '{}'}); }, 4000);</script>
</body>"""


class Pages(BaseHTTPRequestHandler):
    def do_GET(self):
        body = {"/search": SEARCH, "/check": CHECK}.get(self.path.split("?")[0])
        self.reply(200 if body else 404, body or "missing", "text/html")

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.reply(200, json.dumps(MAP), "application/json")

    def reply(self, status, body, mime):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


def ensure_dedicated_chrome():
    try:
        urllib.request.urlopen("http://127.0.0.1:9333/json/version", timeout=1)
        return
    except OSError:
        pass
    profile = tempfile.mkdtemp(prefix="hunter-check-")
    subprocess.Popen(["open", "-na", "Google Chrome", "--args", "--remote-debugging-port=9333",
                      f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", "about:blank"])
    for _ in range(40):
        time.sleep(0.25)
        try:
            urllib.request.urlopen("http://127.0.0.1:9333/json/version", timeout=1)
            return
        except OSError:
            continue
    sys.exit("The dedicated Chrome did not start on port 9333")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Pages)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if not args.user:
        ensure_dedicated_chrome()
    chrome = Chrome("user" if args.user else "dedicated")
    chrome.connect()
    capture = lambda url: url.endswith("/api/map")  # noqa: E731
    results = {}
    tab = chrome.open_tab()
    try:
        out = tab.load(f"http://127.0.0.1:{PORT}/search", capture, "JSON.stringify(self.__next_f)", settle=2)
        results["search"] = {"responses": len(out["responses"]), "extracted": out["extracted"],
                             "human_check": out["human_check"]}
    finally:
        tab.close()
    events = []
    tab = chrome.open_tab()
    try:
        out = tab.load(f"http://127.0.0.1:{PORT}/check", capture, "JSON.stringify(self.__next_f)", settle=2,
                       human_wait=20, on_event=lambda kind, url: events.append(kind))
        results["check"] = {"responses": len(out["responses"]), "extracted": out["extracted"],
                            "human_check": out["human_check"], "events": events}
    finally:
        tab.close()
    server.shutdown()
    print(json.dumps(results, indent=2))
    ok = (results["search"]["responses"] == 1 and results["search"]["extracted"]
          and results["check"]["events"] == ["human_check", "human_check_done"]
          and results["check"]["responses"] == 1)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
