"""Forkwell Jobs source — engineer-focused jobs in Japan."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from jpjobs.enrich import extract_job_posting
from jpjobs.pagination import PaginationController
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


def _parse_page(
    html: str,
    keyword: str,
    seen: dict[str, Job],
    *,
    page_num: int,
) -> tuple[int, int, list[Job], bool]:
    tree = HTMLParser(html)
    links = tree.css("a.job-list__link")
    added = 0
    page_jobs: list[Job] = []
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
        job = Job(
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
        seen[source_id] = job
        page_jobs.append(job)
        added += 1
    has_next = any(
        re.search(
            rf"(?:[?&])page={page_num + 1}(?:&|$)",
            anchor.attributes.get("href") or "",
        )
        for anchor in tree.css("a")
    )
    return len(links), added, page_jobs, has_next


async def _probe_published_date(client, job: Job) -> str | None:
    try:
        response = await client.get(job.url)
        response.raise_for_status()
    except Exception:
        return None
    posting = extract_job_posting(response.text)
    if not posting or not posting.get("datePosted"):
        return None
    return str(posting["datePosted"])


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    pacing_ms = opts.get("rate_limit_ms", default_rate_limit_ms)
    seen: dict[str, Job] = {}
    async with make_client() as client:
        for keyword in keywords:
            pagination = PaginationController(
                opts=opts,
                ctx=ctx,
                source=name,
                keyword=keyword,
            )
            for page_num in range(1, pagination.limit + 1):
                params: dict[str, Any] = {
                    "page": page_num,
                    "q[sort]": "published_at desc",
                }
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
                rows, added, page_jobs, has_next = _parse_page(
                    html,
                    keyword,
                    seen,
                    page_num=page_num,
                )
                oldest_date = None
                if pagination.auto and pagination.cutoff and page_jobs:
                    oldest_date = await _probe_published_date(client, page_jobs[-1])
                    if oldest_date:
                        page_jobs[-1].date_posted = oldest_date
                ctx.emit(
                    "source.page",
                    source=name,
                    keyword=keyword,
                    page=page_num,
                    rows=rows,
                    added=added,
                    total=len(seen),
                )
                decision = pagination.decide(
                    page=page_num,
                    rows=rows,
                    added=added,
                    dates=[oldest_date] if oldest_date else [],
                    has_next=has_next,
                    date_ordered=True,
                )
                if decision.stop:
                    break
                await asyncio.sleep(max(0, pacing_ms) / 1000)
    return list(seen.values())
