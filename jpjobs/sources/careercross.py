"""CareerCross source — bilingual professional jobs.

Experimental: CareerCross's keyword search URLs redirect to a not-found page for
unauthenticated visitors. The recent-jobs sidebar widget still renders 6 latest
job links, which is the best we can scrape without login.
"""

from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import make_client


async def _fetch_tolerant(client, url: str) -> str | None:
    """CareerCross's keyword search redirects to /en/not-found (HTTP 404) but the
    body still contains the recent-jobs widget we scrape. Don't bail on 404."""
    try:
        r = await client.get(url)
        if r.status_code in (429, 403):
            return None
        # Accept 200 and 404 (the not-found page still has the widget).
        if r.status_code >= 500:
            return None
        return r.text
    except Exception:
        return None


name = "careercross"
description = "CareerCross — bilingual professional jobs in Japan (limited scrape)"
status = "experimental"
requires_browser = False
supports = {
    "prefecture": False,
    "keywords": True,
    "category": False,
    "employment_type": False,
    "language": True,
}
default_rate_limit_ms = 1500

BASE = "https://www.careercross.com/en/job-search"


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    seen: dict[str, Job] = {}
    async with make_client() as client:
        for kw in keywords:
            # The site's main search returns a not-found page for keyword queries
            # without auth, but the response still contains a "new jobs" widget.
            if kw:
                url = f"{BASE}/keyword-{kw.replace(' ', '+')}"
            else:
                url = BASE
            html = await _fetch_tolerant(client, url)
            if not html:
                ctx.emit("source.error", source=name, keyword=kw, error="fetch failed")
                continue
            tree = HTMLParser(html)
            page_count = 0
            # The widget wraps each link in div.new-job
            cards = tree.css("div.new-job a[href*='/en/job/detail-']")
            if not cards:
                # Fallback: any /en/job/detail-N anchor on the page
                cards = [
                    a
                    for a in tree.css("a")
                    if "/en/job/detail-" in (a.attributes.get("href") or "")
                ]
            for a in cards:
                href = a.attributes.get("href") or ""
                m = re.search(r"/en/job/detail-(\d+)", href)
                if not m:
                    continue
                sid = m.group(1)
                if sid in seen:
                    continue
                title = (a.attributes.get("title") or a.text(strip=True))[:200]
                if not title:
                    continue
                full_url = (
                    href
                    if href.startswith("http")
                    else f"https://www.careercross.com{href}"
                )
                seen[sid] = Job(
                    id=make_job_id(name, sid),
                    source=name,
                    source_id=sid,
                    url=full_url,
                    title=title,
                    company="",
                    workplace="Japan",
                    language=["bilingual"],
                    matched_keyword=kw or None,
                    scraped_at=now_iso(),
                )
                page_count += 1
            ctx.emit(
                "source.page", source=name, keyword=kw, rows=page_count, total=len(seen)
            )
    return list(seen.values())
