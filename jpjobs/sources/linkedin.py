"""LinkedIn jobs source via the public jobs-guest endpoint.

No login required. This is the same endpoint linkedin-jobs-api (npm) uses,
reimplemented in Python with httpx + selectolax.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlencode

import httpx
from selectolax.parser import HTMLParser

from jpjobs.pagination import PaginationController
from jpjobs.schema import Job, make_job_id, now_iso


name = "linkedin"
description = "LinkedIn jobs via public guest endpoint"
status = "active"
requires_browser = False
supports = {
    "prefecture": False,  # location is a free-text string
    "keywords": True,
    "category": False,
    "employment_type": True,
    "language": True,
    "date": True,
    "pagination": True,
}
default_rate_limit_ms = 700

GUEST_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

EXPERIENCE_MAP = {
    "intern": "1",
    "entry": "2",
    "associate": "3",
    "mid": "4",
    "director": "5",
    "executive": "6",
}

JOB_TYPE_MAP = {
    "fulltime": "F",
    "parttime": "P",
    "contract": "C",
    "dispatch": "T",
    "temporary": "T",
    "intern": "I",
    "internship": "I",
}


def _pick_date(days: int) -> str:
    """LinkedIn accepts a relative age in seconds (for example ``r2592000``)."""
    return f"r{max(1, days) * 86400}"


async def _fetch_page(
    client: httpx.AsyncClient, params: dict, start: int
) -> tuple[str, str | None]:
    qs = {**params, "start": start}
    url = f"{GUEST_URL}?{urlencode(qs)}"
    try:
        r = await client.get(url, timeout=15)
        if r.status_code in (429, 403):
            return "", f"HTTP {r.status_code}"
        r.raise_for_status()
        return r.text, None
    except Exception as exc:
        return "", str(exc)


def _parse_card(card) -> dict | None:
    a = card.css_first("a.base-card__full-link") or card.css_first("a.base-card")
    if not a:
        return None
    href = a.attributes.get("href") or ""
    if not href:
        return None
    # job ID is the trailing -digits before query string
    import re as _re

    m = _re.search(r"-(\d{8,})(?:\?|$)", href)
    if not m:
        return None
    job_id = m.group(1)
    title_el = card.css_first("h3.base-search-card__title") or card.css_first("h3")
    title = title_el.text(strip=True) if title_el else ""
    company_el = card.css_first("h4.base-search-card__subtitle") or card.css_first("h4")
    company = company_el.text(strip=True) if company_el else ""
    location_el = card.css_first("span.job-search-card__location")
    location = location_el.text(strip=True) if location_el else ""
    date_el = card.css_first("time")
    date_posted = date_el.attributes.get("datetime") if date_el else None
    return {
        "id": job_id,
        "title": title,
        "company": company,
        "location": location,
        "url": href.split("?")[0],
        "date_posted": date_posted,
    }


async def _query_combination(
    client: httpx.AsyncClient,
    keyword: str,
    location: str,
    days: int | None,
    seniority: str | None,
    job_type: str | None,
    pacing_ms: int,
    opts: dict[str, Any],
    ctx,
) -> list[dict]:
    """One (keyword × seniority) sweep, paginated."""
    params = {"keywords": keyword, "location": location}
    if days is not None:
        params["f_TPR"] = _pick_date(days)
    if seniority and seniority in EXPERIENCE_MAP:
        params["f_E"] = EXPERIENCE_MAP[seniority]
    if job_type and job_type in JOB_TYPE_MAP:
        params["f_JT"] = JOB_TYPE_MAP[job_type]

    results = []
    result_ids: set[str] = set()
    pagination = PaginationController(
        opts=opts,
        ctx=ctx,
        source=name,
        keyword=keyword,
        context={"seniority": seniority, "job_type": job_type},
    )
    for p in range(pagination.limit):
        html, fetch_error = await _fetch_page(client, params, p * 25)
        if fetch_error:
            ctx.emit(
                "source.error",
                source=name,
                keyword=keyword,
                page=p + 1,
                error=fetch_error,
            )
            pagination.abort(p + 1)
            break
        if not html:
            pagination.decide(
                page=p + 1,
                rows=0,
                added=0,
                server_date_filtered=days is not None,
            )
            break
        tree = HTMLParser(html)
        cards = tree.css("li") or tree.css(".base-card")
        page_results = [c for c in (_parse_card(card) for card in cards) if c]
        new_results = [row for row in page_results if row["id"] not in result_ids]
        result_ids.update(row["id"] for row in new_results)
        results.extend(page_results)
        ctx.emit(
            "source.page",
            source=name,
            keyword=keyword,
            seniority=seniority,
            job_type=job_type,
            page=p + 1,
            rows=len(page_results),
            added=len(new_results),
            total=len(result_ids),
        )
        decision = pagination.decide(
            page=p + 1,
            rows=len(page_results),
            added=len(new_results),
            dates=[row["date_posted"] for row in page_results],
            has_next=len(page_results) >= 10,
            date_ordered=True,
            server_date_filtered=days is not None,
            stop_on_no_new=True,
        )
        if decision.stop:
            break
        await asyncio.sleep(pacing_ms / 1000)
    return results


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    # An omitted keyword means an unfiltered search. Source adapters must not
    # silently substitute a role bundle because it changes the user's intent.
    keywords = opts.get("keywords") or [""]
    location = opts.get("location") or "Japan"
    days = opts.get("days", 7)
    pacing_ms = opts.get("rate_limit_ms", 700)
    employment_types = opts.get("employment_types") or [None]
    seniorities = opts.get("seniorities") or [None]
    job_type_codes = employment_types or [None]

    seen: dict[str, Job] = {}
    headers = {
        # The public guest endpoint ignores the `start` offset for non-browser
        # user agents and repeats page one.
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        for kw in keywords:
            for sen in seniorities:
                for jt in job_type_codes:
                    try:
                        rows = await _query_combination(
                            client,
                            kw,
                            location,
                            days,
                            sen,
                            jt,
                            pacing_ms,
                            opts,
                            ctx,
                        )
                        for r in rows:
                            sid = r["id"]
                            if sid in seen:
                                continue
                            seen[sid] = Job(
                                id=make_job_id(name, sid),
                                source=name,
                                source_id=sid,
                                url=f"https://www.linkedin.com/jobs/view/{sid}",
                                title=r["title"],
                                company=r["company"],
                                workplace=r["location"],
                                employment_type=jt,
                                date_posted=r["date_posted"],
                                matched_keyword=kw or None,
                                scraped_at=now_iso(),
                            )
                    except Exception as e:
                        ctx.emit("source.error", source=name, keyword=kw, error=str(e))
                    await asyncio.sleep(pacing_ms / 1000)
    return list(seen.values())
