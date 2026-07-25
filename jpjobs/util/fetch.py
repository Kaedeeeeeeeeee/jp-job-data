"""Thin HTTP helper with sensible defaults, retries, and rate-limit awareness."""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx


DEFAULT_UA = (
    "jpjobs/0.4 (+https://github.com/Kaedeeeeeeeeee/jp-job-data; "
    "responsible research crawler)"
)


def make_client(
    user_agent: str = DEFAULT_UA,
    follow_redirects: bool = True,
    timeout: float = 15.0,
) -> httpx.AsyncClient:
    """Return a configured async HTTP client."""
    return httpx.AsyncClient(
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.6,ja;q=0.4",
        },
        follow_redirects=follow_redirects,
        timeout=timeout,
    )


async def fetch_html(
    client: httpx.AsyncClient,
    url: str,
    *,
    retries: int = 1,
    pacing_ms: int = 1500,
) -> Optional[str]:
    """GET html with one retry on transient error. Returns None on 429/403."""
    for attempt in range(retries + 1):
        try:
            r = await client.get(url)
            if r.status_code in (429, 403):
                return None  # caller decides whether to raise RateLimitError
            r.raise_for_status()
            return r.text
        except (httpx.TimeoutException, httpx.HTTPError):
            if attempt == retries:
                return None
            await asyncio.sleep(pacing_ms / 1000)
    return None
