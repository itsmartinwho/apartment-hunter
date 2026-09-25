"""Listing sources. Each source builds search URLs and reads data that a normal page load delivers."""

import json
import re

PHOTO_RE = re.compile(r"https://photos\.zillowstatic\.com/fp/([0-9a-f]{32})-[A-Za-z0-9_]+\.(?:jpg|jpeg|webp|png)")


def deep_values(obj, key_test):
    """(key, value) pairs anywhere in nested JSON whose key passes key_test."""
    out, stack = [], [obj]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for k, v in item.items():
                if key_test(k):
                    out.append((k, v))
                stack.append(v)
        elif isinstance(item, list):
            stack.extend(item)
    return out


def longest_text(obj, key_test, minimum=80):
    texts = [v for _, v in deep_values(obj, key_test) if isinstance(v, str) and len(v) >= minimum]
    return max(texts, key=len) if texts else None


def photo_keys(text):
    """Unique CDN photo keys in order of appearance."""
    seen, out = set(), []
    for key in PHOTO_RE.findall(text or ""):
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def amenity_strings(obj):
    out = []
    for _, value in deep_values(obj, lambda k: "amenit" in str(k).lower()):
        items = value if isinstance(value, list) else [value]
        for item in items:
            if isinstance(item, str) and 2 < len(item) < 60:
                out.append(item)
            elif isinstance(item, dict):
                for field in ("name", "label", "title", "displayName", "value"):
                    if isinstance(item.get(field), str) and 2 < len(item[field]) < 60:
                        out.append(item[field])
                        break
    seen = set()
    return [a for a in out if not (a.lower() in seen or seen.add(a.lower()))][:60]


def loads(text):
    try:
        return json.loads(text) if isinstance(text, str) else text
    except ValueError:
        return None
