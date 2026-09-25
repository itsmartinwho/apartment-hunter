"""Parse Next.js React Server Component flight data (self.__next_f) into Python objects."""

import json
import re

HEX = re.compile(r"^[0-9a-f]+$")
REF = re.compile(r"^\$([0-9a-f]+)$")
MAX_DEPTH = 80


def rows(raw):
    """Split flight data into {row id: ("text" | "src", value)}. Text rows carry a UTF-8 byte length."""
    out, i, n = {}, 0, len(raw)
    while i < n:
        colon = raw.find(":", i)
        if colon < 0:
            break
        key = raw[i:colon]
        if not HEX.match(key):
            newline = raw.find("\n", i)
            i = n if newline < 0 else newline + 1
            continue
        j = colon + 1
        comma = raw.find(",", j, j + 12)
        if raw.startswith("T", j) and comma > 0 and HEX.match(raw[j + 1:comma] or "x"):
            length, k, size = int(raw[j + 1:comma], 16), comma + 1, 0
            while size < length and k < n:
                size += len(raw[k].encode("utf-8", "surrogatepass"))
                k += 1
            out[key] = ("text", raw[comma + 1:k])
            i = k
        else:
            newline = raw.find("\n", j)
            end = n if newline < 0 else newline
            out[key] = ("src", raw[j:end])
            i = end + 1
    return out


def parse(raw):
    """Return {row id: value} with "$<id>" references resolved. Module and hint rows become None."""
    table, cache = rows(raw), {}

    def get(key, depth):
        if key in cache:
            return cache[key]
        kind, value = table.get(key, ("src", "null"))
        cache[key] = None  # Cycle guard: a self-reference resolves to None.
        if kind == "text":
            cache[key] = value
        elif not (value[:1] in "IHEDW" and value[1:2] in "[{L"):
            try:
                cache[key] = resolve(json.loads(value), depth + 1)
            except ValueError:
                cache[key] = None
        return cache[key]

    def resolve(value, depth):
        if depth > MAX_DEPTH:
            return value
        if isinstance(value, str):
            match = REF.match(value)
            return get(match.group(1), depth + 1) if match else value
        if isinstance(value, list):
            return [resolve(v, depth + 1) for v in value]
        if isinstance(value, dict):
            return {k: resolve(v, depth + 1) for k, v in value.items()}
        return value

    return {key: get(key, 0) for key in table}


def find(obj, predicate):
    """All dicts in a nested structure for which predicate(dict) is true."""
    found, stack, seen = [], [obj], set()
    while stack:
        item = stack.pop()
        if isinstance(item, (dict, list)):
            if id(item) in seen:
                continue
            seen.add(id(item))
        if isinstance(item, dict):
            if predicate(item):
                found.append(item)
            stack.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            stack.extend(reversed(item))
    return found
