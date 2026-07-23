"""JobsInJapan source — English-speaker general jobs in Japan."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import fetch_html, make_client


name = "jobsinjapan"
description = "JobsInJapan — English-speaker general jobs in Japan"
status = "active"
requires_browser = False
supports = {
    "prefecture": False,
    "keywords": True,
    "category": False,
    "employment_type": True,
    "language": True,
    "date": False,
    "pagination": True,
}
default_rate_limit_ms = 1500

BASE = "https://jobsinjapan.com/jobs/"
SEARCH_BASE = "https://jobsinjapan.com/"


def _parse_cards(html: str, keyword: str, seen: dict[str, Job]) -> tuple[int, int]:
    tree = HTMLParser(html)
    cards = tree.css("article.noo_job")
    added = 0
    for card in cards:
        href = card.attributes.get("data-href") or ""
        title_anchor = card.css_first("h3.loop-item-title a")
        if not href and title_anchor:
            href = title_anchor.attributes.get("href") or ""
        match = re.search(r"/jobs/(\d+)/", href)
        if not match:
            continue
        source_id = match.group(1)
        if source_id in seen:
            continue
        title = title_anchor.text(strip=True)[:200] if title_anchor else ""
        if not title:
            continue
        company_element = card.css_first(".company-name")
        location_element = card.css_first(".job-location")
        employment_element = card.css_first(".loop-job-type a.job-type")
        employment_label = (
            employment_element.text(strip=True).lower() if employment_element else ""
        )
        employment_map = {
            "full time": "fulltime",
            "full-time": "fulltime",
            "part time": "parttime",
            "part-time": "parttime",
            "contract": "contract",
            "dispatch": "dispatch",
            "freelance": "freelance",
            "intern": "intern",
        }
        seen[source_id] = Job(
            id=make_job_id(name, source_id),
            source=name,
            source_id=source_id,
            url=href,
            title=title,
            company=company_element.text(strip=True) if company_element else "",
            workplace=location_element.text(strip=True)
            if location_element
            else "Japan",
            employment_type=employment_map.get(employment_label),
            language=["english"],
            matched_keyword=keyword or None,
            scraped_at=now_iso(),
        )
        added += 1
    return len(cards), added


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    pages = opts.get("pages", 2)
    pacing_ms = opts.get("rate_limit_ms", default_rate_limit_ms)
    seen: dict[str, Job] = {}

    async with make_client() as client:
        for keyword in keywords:
            for page_num in range(1, pages + 1):
                if keyword:
                    path = "" if page_num == 1 else f"page/{page_num}/"
                    params = urlencode({"s": keyword, "post_type": "noo_job"})
                    url = f"{SEARCH_BASE}{path}?{params}"
                else:
                    url = BASE if page_num == 1 else f"{BASE}page/{page_num}/"
                html = await fetch_html(client, url)
                if not html:
                    ctx.emit(
                        "source.error",
                        source=name,
                        keyword=keyword,
                        page=page_num,
                        error="fetch failed",
                    )
                    break
                rows, added = _parse_cards(html, keyword, seen)
                ctx.emit(
                    "source.page",
                    source=name,
                    keyword=keyword,
                    page=page_num,
                    rows=rows,
                    added=added,
                    total=len(seen),
                )
                if rows == 0:
                    break
                await asyncio.sleep(max(0, pacing_ms) / 1000)
    return list(seen.values())
