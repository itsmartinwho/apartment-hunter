"""JSON POST with short, bounded retries for model APIs (as in jev-ultrafast). Never used for listing sites."""

import time

import httpx

CLIENT = httpx.Client(timeout=60)  # HTTP/1.1 pool: steadier than one HTTP/2 connection across threads.


class ModelError(RuntimeError):
    pass


def post_json(url, key, body, attempts=3):
    for attempt in range(attempts):
        try:
            response = CLIENT.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as error:
            if attempt < attempts - 1:
                time.sleep(0.5 * 2**attempt)
                continue
            raise ModelError(f"Model connection failed: {type(error).__name__}") from None
        if response.status_code in {429, 500, 502, 503, 529} and attempt < attempts - 1:
            time.sleep(0.75 * 2**attempt)
            continue
        if response.is_error:
            raise ModelError(f"Model provider returned HTTP {response.status_code}: {response.text[:300]}")
        try:
            return response.json()
        except ValueError:
            raise ModelError("Model provider returned a body that is not JSON") from None
    raise ModelError("Model unavailable")
