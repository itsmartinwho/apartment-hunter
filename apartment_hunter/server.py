"""Loopback-only HTTP server for the UI and JSON API. Entry point: uv run hunt."""

import argparse
import json
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import areas, jev, preferences, subway
from .config import STATIC, load_env, settings
from .criteria import (
    AMENITIES,
    CRITERIA,
    DEFAULT_LIMITS,
    DEFAULT_SAFETY,
    DEFAULT_WEIGHTS,
    PRESETS,
    clean_limits,
    clean_safety,
    clean_weights,
)
from .pipeline import Busy, Hunter
from .store import Store

MAX_BODY = 512 * 1024
PUBLIC_PHOTOS = 8
UI_BOROUGHS = ("Manhattan", "Brooklyn")
STATIC_FILES = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                "/style.css": ("style.css", "text/css")}


def public(listing):
    """What the UI needs: trimmed photo lists and no raw page text."""
    out = dict(listing)
    out["photos"] = (listing.get("photos") or [])[:PUBLIC_PHOTOS]
    out["photo_count"] = listing.get("photo_count") or len(listing.get("photos") or [])
    if listing.get("detail"):
        detail = dict(listing["detail"])
        detail.pop("text", None)
        detail["photos"] = (detail.get("photos") or [])[:PUBLIC_PHOTOS]
        out["detail"] = detail
    if listing.get("inspection"):
        inspection = dict(listing["inspection"])
        inspection.pop("vision", None)
        inspection.pop("jev", None)
        out["inspection"] = inspection
    return out


def clean_tiers(tiers):
    out = {}
    for key, value in (tiers or {}).items():
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if str(key).isdigit() and value in (1, 2, 3, 4):
            out[str(key)] = value
    return out


class App:
    def __init__(self, store, hunter, interpret_preferences=preferences.interpret):
        self.store, self.hunter = store, hunter
        self.interpret_preferences = interpret_preferences

    def tiers(self, override=None):
        """Default tiers, then saved tiers, then tiers sent with the request. Values must be 1 to 4."""
        out = dict(areas.DEFAULT_TIERS)
        for source in (self.store.get_setting("tiers") or {}, override or {}):
            out.update(clean_tiers(source))
        return out

    def config(self):
        table = areas.load()
        stations = {}
        for s in subway.load():
            if s.borough in UI_BOROUGHS:
                stations.setdefault((s.complex_id, s.name), {"name": s.name, "lines": list(s.lines), "lat": s.lat,
                                                             "lon": s.lon})
        return {
            "criteria": [{k: c[k] for k in ("id", "label", "pass", "weight", "help")} for c in CRITERIA],
            "weights": clean_weights(self.store.get_setting("weights") or DEFAULT_WEIGHTS),
            "limits": clean_limits(self.store.get_setting("limits") or DEFAULT_LIMITS),
            "safety": clean_safety(self.store.get_setting("safety") or DEFAULT_SAFETY),
            "tiers": self.tiers(),
            "default_tiers": dict(areas.DEFAULT_TIERS),
            "default_limits": dict(DEFAULT_LIMITS),
            "areas": [{"id": a.id, "name": a.name, "level": a.level, "parent_id": a.parent_id, "borough": a.borough}
                      for a in sorted(table.values(), key=lambda a: (a.borough, a.level, a.name))
                      if a.borough in UI_BOROUGHS],
            "amenities": [{"id": k, "label": v["label"]} for k, v in AMENITIES.items()],
            "presets": PRESETS,
            "stations": list(stations.values()),
            "last_search": self.store.last_run("search"),
            "settings": {"chrome_mode": settings()["chrome_mode"], "vision_model": settings()["vision_model"],
                         "typesafe_model": settings()["typesafe_model"], "text_model": settings()["text_model"]},
        }

    def rank(self, body):
        tiers = self.tiers(body.get("tiers") if isinstance(body.get("tiers"), dict) else None)
        result = self.hunter.ranked(body.get("limits") or {}, body.get("weights") or {}, tiers)
        result["listings"] = [public(x) for x in result["listings"]]
        return result

    def save_settings(self, body):
        cleaners = {"limits": clean_limits, "weights": clean_weights, "safety": clean_safety}
        for key, clean in cleaners.items():
            if isinstance(body.get(key), dict):
                self.store.set_setting(key, clean(body[key]))
        if isinstance(body.get("tiers"), dict):
            self.store.set_setting("tiers", clean_tiers(body["tiers"]))
        return {"ok": True}

    def post(self, path, body):
        hunter = self.hunter
        if path == "/api/rank":
            return self.rank(body)
        if path == "/api/search":
            self.save_settings({"limits": body.get("limits"), "safety": body.get("safety")})
            return {"job": hunter.search(body.get("limits") or {}, body.get("safety") or {}).to_dict()}
        if path == "/api/inspect":
            ids = [str(i) for i in body.get("ids") or []][:60]
            if not ids:
                raise ValueError("Pick at least one listing to inspect")
            return {"job": hunter.inspect(ids).to_dict()}
        if path == "/api/deep":
            ids = [str(i) for i in body.get("ids") or []][:10]
            if not ids:
                raise ValueError("Pick at least one listing for a deep look")
            return {"job": hunter.deep_look(ids, body.get("safety") or {}).to_dict()}
        if path == "/api/cancel":
            hunter.cancel()
            return {"ok": True}
        if path == "/api/settings":
            return self.save_settings(body)
        if path == "/api/preferences":
            # A preview only: neither persist settings nor start a search here.
            return self.interpret_preferences(
                body.get("text"), body.get("limits") or {}, body.get("weights") or {},
                self.tiers(body.get("tiers") if isinstance(body.get("tiers"), dict) else None))
        if path == "/api/interpret":
            try:
                return jev.interpret(str(body.get("text") or ""), clean_weights(body.get("weights") or {}))
            except jev.JevError as error:
                raise ValueError(str(error)) from None
        raise LookupError(path)


def make_handler(app, token, port):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {None, f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, content, mime="application/json"):
            data = content if isinstance(content, bytes) else content.encode()
            self.send_response(status)
            self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text") else ""))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

        def json(self, status, value):
            self.send(status, json.dumps(value))

        def do_GET(self):
            if self.headers.get("Host") not in hosts:
                return self.send(403, "Forbidden", "text/plain")
            path = urlparse(self.path).path
            if path == "/api/config":
                return self.json(200, app.config())
            if path == "/api/status":
                return self.json(200, app.hunter.status())
            if path in STATIC_FILES:
                name, mime = STATIC_FILES[path]
                file = STATIC / name
                if not file.exists():
                    return self.send(404, "The UI file is missing: " + name, "text/plain")
                text = file.read_text()
                if name == "index.html":
                    text = text.replace("__TOKEN__", token)
                return self.send(200, text, mime)
            return self.send(404, "Not found", "text/plain")

        def do_POST(self):
            if (self.headers.get("Host") not in hosts or self.headers.get("X-Hunter-Token") != token
                    or self.headers.get("Origin") not in origins):
                return self.json(403, {"error": "Local requests from the Apartment Hunter page only"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    raise ValueError("Invalid request size")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Send a JSON object")
                self.json(200, app.post(urlparse(self.path).path, body))
            except Busy as error:
                self.json(409, {"error": str(error)})
            except LookupError:
                self.json(404, {"error": "Unknown endpoint"})
            except (ValueError, TypeError) as error:
                self.json(400, {"error": str(error)})
            except Exception as error:  # Report, do not hide: the UI shows this message.
                self.json(500, {"error": f"Server error: {type(error).__name__}: {error}"[:400]})

        def log_message(self, *_):
            pass

    return Handler


def check():
    """Quick diagnostics: keys, model endpoints, and the Chrome connection."""
    from .client import post_json

    s = settings()
    print("TypeSafe key:", "set" if s["typesafe_key"] else "MISSING (TYPESAFE_API_KEY)")
    print("Vision key:", "set" if s["vision_key"] else "MISSING (VISION_API_KEY or TEXT_MODEL_API_KEY)")
    try:
        result = post_json("https://api.typesafe.ai/v1/systemone", s["typesafe_key"], {
            "model": s["typesafe_model"], "state": "A bright apartment with large windows.",
            "questions": {"bright": {"type": "noul", "instructions": "Is the apartment bright?"}}})
        print("Jev:", result.get("model"), "answered", result["answers"]["bright"]["noul"])
    except Exception as error:
        print("Jev: FAILED", error)
    print("Chrome mode:", s["chrome_mode"], "(if Chrome asks \"Allow remote debugging?\", click Allow)")
    try:
        from .pipeline import default_chrome

        default_chrome().connect()
        print("Chrome: connected")
    except Exception as error:
        print("Chrome: FAILED", error)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="hunt", description="Apartment Hunter: rank NYC rentals your way.")
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-open", action="store_true", help="Do not open the page in your browser")
    parser.add_argument("--check", action="store_true", help="Check keys, Jev, and the Chrome connection")
    args = parser.parse_args(argv)
    load_env()
    if args.check:
        return check()
    s = settings()
    port = args.port or s["port"]
    s["home"].mkdir(parents=True, exist_ok=True)
    store = Store(s["home"] / "hunter.db")
    app = App(store, Hunter(store))
    token = secrets.token_urlsafe(24)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, token, port))
    except OSError as error:
        sys.exit(f"Port {port} is busy ({error}). Is Apartment Hunter already running? Try --port.")
    url = f"http://127.0.0.1:{port}"
    print(f"Apartment Hunter: {url}  (data in {s['home']})", flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
