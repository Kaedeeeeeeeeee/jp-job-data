"""Daijob source — bilingual professional jobs in Japan."""

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


name = "daijob"
description = "Daijob — bilingual professional jobs in Japan"
status = "active"
requires_browser = False
supports = {
    "prefecture": False,
    "keywords": True,
    "category": False,
    "employment_type": False,
    "language": True,
    "date": False,
    "pagination": True,
}
default_rate_limit_ms = 1500

BASE = "https://www.daijob.com/en/jobs/search_result"


def _parse_page(
    html: str, keyword: str, seen: dict[str, Job]
) -> tuple[int, int, list[Job]]:
    tree = HTMLParser(html)
    cards = tree.css("article.job-card")
    added = 0
    page_jobs: list[Job] = []
    for card in cards:
        title_anchor = card.css_first("h2.job-card__title a") or card.css_first(
            'a[href*="/en/jobs/detail/"]'
        )
        if not title_anchor:
            continue
        href = title_anchor.attributes.get("href") or ""
        match = re.search(r"/en/jobs/detail/(\d+)", href)
        if not match:
            continue
        source_id = match.group(1)
        if source_id in seen:
            continue
        title = title_anchor.text(strip=True)[:200]
        company = ""
        header_info = card.css_first(".job-card__header-info")
        if header_info:
            for anchor in header_info.css("a"):
                if "/en/jobs/detail/" in (anchor.attributes.get("href") or ""):
                    text = anchor.text(strip=True)
                    if text and text != title:
                        company = text
                        break
        if not company:
            logo = card.css_first(".job-card__logo-wrap img")
            company = (logo.attributes.get("alt") or "").strip() if logo else ""

        workplace = ""
        description = ""
        for term in card.css(".job-card__detail dt"):
            label = term.text(strip=True)
            definition = term.next
            while definition is not None and getattr(definition, "tag", "") != "dd":
                definition = definition.next
            if definition is None:
                continue
            if "Location" in label:
                parts = [anchor.text(strip=True) for anchor in definition.css("a")]
                workplace = ", ".join(part for part in parts if part)[:200]
                if not workplace:
                    workplace = definition.text(separator=" ", strip=True)[:200]
            elif "Job Description" in label:
                description = definition.text(separator=" ", strip=True)[:400]
        activated = None
        activated_node = card.css_first("p.text-end.text-secondary")
        if activated_node:
            activated_match = re.search(
                r"\bActivated\s*:\s*(\d{4}-\d{2}-\d{2})\b",
                activated_node.text(separator=" ", strip=True),
                re.I,
            )
            activated = activated_match.group(1) if activated_match else None
        full_url = (
            href
            if href.startswith("http")
            else f"https://www.daijob.com{href.split('?')[0]}"
        )
        job = Job(
            id=make_job_id(name, source_id),
            source=name,
            source_id=source_id,
            url=full_url,
            title=title,
            company=company,
            description=description,
            description_snippet=description,
            workplace=workplace or "Japan",
            date_posted=activated,
            language=["bilingual"],
            matched_keyword=keyword or None,
            scraped_at=now_iso(),
        )
        seen[source_id] = job
        page_jobs.append(job)
        added += 1
    return len(cards), added, page_jobs


async def _probe_activated_date(client, job: Job) -> str | None:
    """Read the oldest row's activation date for newest-first auto paging."""
    try:
        response = await client.get(job.url)
        response.raise_for_status()
    except Exception:
        return None
    posting = extract_job_posting(response.text)
    if posting and posting.get("datePosted"):
        return str(posting["datePosted"])
    text = HTMLParser(response.text).text(separator=" ", strip=True)
    match = re.search(r"\bActivated\s+(\d{4}-\d{2}-\d{2})\b", text, re.I)
    return match.group(1) if match else None


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
            for page_num in pagination.page_numbers():
                params: dict[str, Any] = {
                    "job_post_language": 1,
                    "sort_order": 2,
                    "page": page_num,
                }
                if keyword:
                    params["keyword"] = keyword
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
                rows, added, page_jobs = _parse_page(html, keyword, seen)
                oldest_date = (
                    page_jobs[-1].date_posted if page_jobs else None
                )
                if pagination.auto and pagination.cutoff and page_jobs:
                    oldest_date = oldest_date or await _probe_activated_date(
                        client, page_jobs[-1]
                    )
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
                    # sort_order=2 is Daijob's "Activated date" order.
                    date_ordered=True,
                )
                if decision.stop:
                    break
                await asyncio.sleep(max(0, pacing_ms) / 1000)
    return list(seen.values())
