"""Forkwell Jobs source — engineer-focused jobs in Japan."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import fetch_html, make_client


name = "forkwell"
description = "Forkwell Jobs — engineer-focused jobs in Japan"
status = "active"
requires_browser = False
supports = {
    "prefecture": False,
    "keywords": True,
    "category": False,
    "employment_type": False,
    "language": False,
    "date": False,
    "pagination": True,
}
default_rate_limit_ms = 1500

BASE = "https://jobs.forkwell.com/jobs/search"


def _parse_page(html: str, keyword: str, seen: dict[str, Job]) -> tuple[int, int]:
    tree = HTMLParser(html)
    links = tree.css("a.job-list__link")
    added = 0
    for link in links:
        href = link.attributes.get("href") or ""
        match = re.match(r"^/([A-Za-z0-9_-]+)/jobs/(\d+)", href)
        if not match:
            continue
        company_slug, job_id = match.group(1), match.group(2)
        source_id = f"{company_slug}/{job_id}"
        if source_id in seen:
            continue
        title_element = link.css_first("span")
        title = (
            title_element.text(strip=True) if title_element else link.text(strip=True)
        )[:200]
        if not title:
            continue
        row = link.parent
        while row is not None and "row" not in (row.attributes.get("class") or ""):
            row = row.parent
        company = ""
        workplace = "Japan"
        if row is not None:
            detail = row.css_first(".avatar__detail")
            if detail:
                company = detail.text(strip=True)
            for item in row.css("li.list-inline-item"):
                if item.css_first("i.fa-map-marker-alt"):
                    workplace = item.text(strip=True) or workplace
                    break
        if not company:
            company = company_slug.replace("-", " ").title()
        seen[source_id] = Job(
            id=make_job_id(name, source_id),
            source=name,
            source_id=source_id,
            url=f"https://jobs.forkwell.com{href}",
            title=title,
            company=company,
            workplace=workplace,
            matched_keyword=keyword or None,
            scraped_at=now_iso(),
        )
        added += 1
    return len(links), added


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    pages = opts.get("pages", 2)
    pacing_ms = opts.get("rate_limit_ms", default_rate_limit_ms)
    seen: dict[str, Job] = {}
    async with make_client() as client:
        for keyword in keywords:
            for page_num in range(1, pages + 1):
                params: dict[str, Any] = {"page": page_num}
                if keyword:
                    params["q"] = keyword
                url = f"{BASE}?{urlencode(params)}"
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
                rows, added = _parse_page(html, keyword, seen)
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
