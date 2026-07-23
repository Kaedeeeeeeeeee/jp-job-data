"""JobsInJapan source — English-speaker general jobs in Japan."""

from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from jpjobs.pagination import PaginationController
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


def _relative_date(value: str, as_of: date) -> str | None:
    text = value.strip().casefold()
    if not text:
        return None
    if any(unit in text for unit in ("second", "minute", "hour", "just now", "today")):
        return as_of.isoformat()
    match = re.search(r"(\d+)\s+(day|week|month|year)", text)
    if not match:
        return None
    count = int(match.group(1))
    unit = match.group(2)
    days = count * {"day": 1, "week": 7, "month": 30, "year": 365}[unit]
    return (as_of - timedelta(days=days)).isoformat()


def _parse_cards(
    html: str,
    keyword: str,
    seen: dict[str, Job],
    *,
    as_of: date,
) -> tuple[int, int, list[Job], bool]:
    tree = HTMLParser(html)
    cards = tree.css("article.noo_job")
    added = 0
    page_jobs: list[Job] = []
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
        date_element = card.css_first(".job-date-ago")
        date_posted = (
            _relative_date(date_element.text(strip=True), as_of)
            if date_element
            else None
        )
        job = Job(
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
            date_posted=date_posted,
            language=["english"],
            matched_keyword=keyword or None,
            scraped_at=now_iso(),
        )
        seen[source_id] = job
        page_jobs.append(job)
        added += 1
    has_next = any(
        (
            "next" in (anchor.attributes.get("class") or "").casefold()
            or anchor.text(strip=True).casefold() in {"next", "next page", "›", "»"}
        )
        for anchor in tree.css("a")
        if "/page/" in (anchor.attributes.get("href") or "")
    )
    return len(cards), added, page_jobs, has_next


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    pacing_ms = opts.get("rate_limit_ms", default_rate_limit_ms)
    as_of = date.fromisoformat(opts.get("as_of") or date.today().isoformat())
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
                params: dict[str, str] = {"orderby": "date"}
                if keyword:
                    path = "" if page_num == 1 else f"page/{page_num}/"
                    params.update({"s": keyword, "post_type": "noo_job"})
                    url = f"{SEARCH_BASE}{path}?{urlencode(params)}"
                else:
                    path = BASE if page_num == 1 else f"{BASE}page/{page_num}/"
                    url = f"{path}?{urlencode(params)}"
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
                rows, added, page_jobs, has_next = _parse_cards(
                    html,
                    keyword,
                    seen,
                    as_of=as_of,
                )
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
                    dates=[job.date_posted for job in page_jobs],
                    has_next=has_next,
                    date_ordered=True,
                )
                if decision.stop:
                    break
                await asyncio.sleep(max(0, pacing_ms) / 1000)
    return list(seen.values())
