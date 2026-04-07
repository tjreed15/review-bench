"""HTTP rate limiting with retry logic."""

from __future__ import annotations

import time

import httpx

_client: httpx.Client | None = None


def get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=30)
    return _client


def rate_limited_fetch(
    url: str,
    retries: int = 3,
    delay_ms: int = 1000,
) -> httpx.Response:
    """Fetch with retries and 429 back-off."""
    client = get_client()
    for attempt in range(1, retries + 1):
        try:
            if attempt > 1:
                time.sleep(delay_ms * attempt / 1000)

            resp = client.get(url)

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                wait = int(retry_after) if retry_after else delay_ms * 2 / 1000
                print(f"Rate limited, waiting {wait}s...")
                time.sleep(float(wait))
                continue

            return resp
        except httpx.HTTPError:
            if attempt == retries:
                raise
            print(f"Connection error (attempt {attempt}/{retries}), retrying...")

    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")
