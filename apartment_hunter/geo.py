"""Small geometry helpers: distance, Google polyline decoding, point in polygon."""

import math

EARTH_M = 6_371_000


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(a))


def decode_polyline(encoded):
    """Decode a Google encoded polyline into [(lat, lon), ...]."""
    points, index, lat, lon = [], 0, 0, 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        points.append((round(lat / 1e5, 6), round(lon / 1e5, 6)))
    return points


def point_in_polygon(lat, lon, polygon):
    """Ray casting. polygon is [(lat, lon), ...]; the ring may be open or closed."""
    inside, n = False, len(polygon)
    for i in range(n):
        y1, x1 = polygon[i]
        y2, x2 = polygon[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x:
                inside = not inside
    return inside


def bbox(polygon):
    """(south, west, north, east) of [(lat, lon), ...]."""
    lats = [p[0] for p in polygon]
    lons = [p[1] for p in polygon]
    return (min(lats), min(lons), max(lats), max(lons))
