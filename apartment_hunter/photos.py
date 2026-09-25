"""Listing photos from the public photo CDN. No listing site is contacted, so no human check can appear."""

import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor

import httpx

from .config import settings

CDN = "https://photos.zillowstatic.com/fp/"
TIMEOUT = 15


def choose(listing, k=6):
    """The first k photos; the first photos on a listing are usually the main rooms."""
    detail = listing.get("detail") or {}
    photos = detail.get("photos") if len(detail.get("photos") or []) > len(listing.get("photos") or []) else None
    return [u for u in (photos or listing.get("photos") or []) if u.startswith(CDN)][:k]


def _cache_path(url):
    folder = settings()["home"] / "photos"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (hashlib.sha1(url.encode()).hexdigest() + "." + url.rsplit(".", 1)[-1])


def _mime(url):
    return "image/webp" if url.endswith(".webp") else "image/png" if url.endswith(".png") else "image/jpeg"


def _get(url):
    path = _cache_path(url)
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes(), _mime(url)
    try:
        response = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if response.status_code != 200 or not response.content:
        return None
    path.write_bytes(response.content)
    return response.content, _mime(url)


def download(urls):
    """[(bytes, mime)] for the photos that downloaded; failures are skipped."""
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=6) as pool:
        return [x for x in pool.map(_get, urls) if x]


def data_url(content, mime):
    return f"data:{mime};base64," + base64.b64encode(content).decode()


def photo_set_hash(urls):
    return hashlib.sha1("|".join(urls).encode()).hexdigest()[:16]
