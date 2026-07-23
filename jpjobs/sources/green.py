"""Green Japan source — IT/startup jobs in Japan."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from jpjobs.pagination import PaginationController
from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import fetch_html, make_client


name = "green"
description = "Green Japan — IT/startup jobs in Japan"
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

BASE = "https://www.green-japan.com/search"


def _updated_dates(html: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for timestamp, url in re.findall(
        r'jobOfferUpdatedAtTimestamp":(\d+),"jobOfferUrl":"([^"]+)',
        html,
    ):
        try:
            result[url] = (
                datetime.fromtimestamp(int(timestamp), timezone.utc).date().isoformat()
            )
        except (OverflowError, OSError, ValueError):
            continue
    return result


def _parse_page(
    html: str, keyword: str, seen: dict[str, Job], *, page_num: int
) -> tuple[int, int, list[Job], list[str | None], bool]:
    tree = HTMLParser(html)
    anchors = tree.css('a[href^="/company/"]')
    updated_dates = _updated_dates(html)
    added = 0
    page_jobs: list[Job] = []
    page_dates: list[str | None] = []
    for anchor in anchors:
        href = anchor.attributes.get("href") or ""
        match = re.match(r"^/company/(\d+)/job/(\d+)", href)
        if not match:
            continue
        company_id, job_id = match.group(1), match.group(2)
        source_id = f"{company_id}/{job_id}"
        if source_id in seen:
            continue
        for style in anchor.css("style"):
            style.decompose()

        company = ""
        for image in anchor.css("img"):
            alt = (image.attributes.get("alt") or "").strip()
            if alt:
                company = re.sub(r"のイメージ画像\d+$", "", alt)
                company = re.sub(r"のロゴ$", "", company)
                break

        tokens = [
            text.strip()
            for text in anchor.text(separator="|").split("|")
            if text.strip()
        ]
        tokens = [
            token for token in tokens if not token.startswith(".") and "{" not in token
        ]
        title = ""
        for token in tokens:
            if token != company and 6 <= len(token) <= 120:
                title = token
                break
        if not title:
            candidates = [
                token for token in tokens if token != company and len(token) <= 200
            ]
            title = max(candidates, key=len) if candidates else ""
        if not title:
            continue

        workplace = next(
            (
                token[:120]
                for token in tokens
                if re.search(
                    r"東京都|大阪府|京都府|神奈川県|愛知県|福岡県|北海道|.+県",
                    token,
                )
            ),
            "Japan",
        )
        job = Job(
            id=make_job_id(name, source_id),
            source=name,
            source_id=source_id,
            url=f"https://www.green-japan.com{href}",
            title=title[:200],
            company=company[:120],
            workplace=workplace,
            matched_keyword=keyword or None,
            scraped_at=now_iso(),
        )
        seen[source_id] = job
        page_jobs.append(job)
        page_dates.append(updated_dates.get(href))
        added += 1
    has_next = any(
        re.search(
            rf"(?:[?&])page={page_num + 1}(?:&|$)",
            anchor.attributes.get("href") or "",
        )
        for anchor in tree.css("a")
    )
    return len(anchors), added, page_jobs, page_dates, has_next


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
                    "order_type": "new",
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
                rows, added, _page_jobs, page_dates, has_next = _parse_page(
                    html,
                    keyword,
                    seen,
                    page_num=page_num,
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
                    dates=page_dates,
                    has_next=has_next,
                    date_ordered=True,
                )
                if decision.stop:
                    break
                await asyncio.sleep(max(0, pacing_ms) / 1000)
    return list(seen.values())
