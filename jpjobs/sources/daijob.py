"""Daijob source — bilingual professional jobs in Japan."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

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


def _parse_page(html: str, keyword: str, seen: dict[str, Job]) -> tuple[int, int]:
    tree = HTMLParser(html)
    cards = tree.css("article.job-card")
    added = 0
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
        for term in card.css(".job-card__detail dt"):
            if "Location" not in term.text(strip=True):
                continue
            definition = term.next
            while definition is not None and getattr(definition, "tag", "") != "dd":
                definition = definition.next
            if definition is not None:
                parts = [anchor.text(strip=True) for anchor in definition.css("a")]
                workplace = ", ".join(part for part in parts if part)[:200]
            break
        full_url = (
            href
            if href.startswith("http")
            else f"https://www.daijob.com{href.split('?')[0]}"
        )
        seen[source_id] = Job(
            id=make_job_id(name, source_id),
            source=name,
            source_id=source_id,
            url=full_url,
            title=title,
            company=company,
            workplace=workplace or "Japan",
            language=["bilingual"],
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
                params: dict[str, Any] = {
                    "job_post_language": 1,
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
