"""HTTP calls that back off when Gmail or Graph say to slow down."""

from __future__ import annotations

import time

import httpx

# Enough pages for a month of mail. This stops a stuck next-page token.
# It is not the old 3-page or 50-message product cap.
MAX_PAGES = 100
_RETRYABLE = {429, 500, 503}


def send(method: str, url: str, **kwargs) -> httpx.Response:
    response: httpx.Response | None = None
    for attempt in range(4):
        response = httpx.request(method, url, **kwargs)
        if response.status_code not in _RETRYABLE or attempt == 3:
            return response
        time.sleep(_delay(response, attempt))
    assert response is not None
    return response


def _delay(response: httpx.Response, attempt: int) -> float:
    header = (response.headers.get("Retry-After") or "").strip()
    if header.isdigit():
        return min(30.0, float(header))
    return min(8.0, 0.5 * (2**attempt))
