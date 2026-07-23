"""DODA source — largest JP mid-career job board (Japanese-language).

Status: experimental.

Two reasons this lands as experimental rather than active:

1. doda.jp times out on every request from our test client (likely a
   combination of geo / UA / bot heuristics — DODA is reachable from inside
   Japan from a real browser, but our async httpx GETs hang past 30s with
   no headers returned). We don't ship `active` on a source we can't smoke
   test.
2. The DOM is JS-augmented; even a successful fetch returns a heavy SSR
   page where keyword + pagination state is encoded in the URL path
   (`-ka-<keyword>` / `-pa-<page>`) rather than query params. We parse the
   path-style URL but selectors may need a revisit once the site is
   reachable from the runner.

When/if the fetch path opens up, set status="active" and re-run the smoke
test from the README.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import make_client, fetch_html


name = "doda"
description = (
    "DODA — largest JP mid-career board (Japanese, currently unreachable from runner)"
)
status = "experimental"
requires_browser = False
supports = {
    "prefecture": False,
    "keywords": True,
    "category": False,
    "employment_type": False,
    "language": True,
}
default_rate_limit_ms = 3000

BASE = "https://doda.jp/DodaFront/View/JobSearchList/"


def _build_url(kw: str) -> str:
    if not kw:
        return BASE
    return f"{BASE}?searchWord={quote(kw)}"


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    seen: dict[str, Job] = {}
    async with make_client() as client:
        for kw in keywords:
            url = _build_url(kw)
            html = await fetch_html(client, url)
            if not html:
                ctx.emit(
                    "source.error",
                    source=name,
                    keyword=kw,
                    error="fetch failed (doda.jp unreachable / timeout)",
                )
                continue
            tree = HTMLParser(html)
            page_count = 0
            # DODA's listing cards have id="jobListItem-<n>" / class includes
            # "jobListItem". Each contains an h3.jobListHead with the job link
            # to /DodaFront/View/JobSearchDetail/jobId-<id>/.
            cards = tree.css(
                "div.jobListItem, li.jobListItem, article.jobListItem, "
                "div[id^='jobListItem'], div.j-jobList"
            )
            for card in cards:
                link = card.css_first("a[href*='JobSearchDetail'], a[href*='jobId-']")
                if not link:
                    continue
                href = link.attributes.get("href") or ""
                m = re.search(r"jobId-(\d+)", href)
                if not m:
                    continue
                sid = m.group(1)
                if sid in seen:
                    continue
                title = link.text(strip=True)[:200]
                if not title:
                    h3 = card.css_first("h3, .jobListHead")
                    title = h3.text(strip=True)[:200] if h3 else ""
                if not title:
                    continue
                # Company is usually in a sibling element.
                company_el = card.css_first(
                    ".companyName, .corpName, .jobListCorpName, dd.companyName"
                )
                company = company_el.text(strip=True) if company_el else ""
                loc_el = card.css_first(".workplace, .area, .jobListArea, dd.area")
                workplace = loc_el.text(strip=True) if loc_el else "Japan"
                wage_el = card.css_first(".salary, .income, .jobListIncome, dd.income")
                wage_raw = wage_el.text(strip=True) if wage_el else ""
                full_url = href if href.startswith("http") else f"https://doda.jp{href}"
                seen[sid] = Job(
                    id=make_job_id(name, sid),
                    source=name,
                    source_id=sid,
                    url=full_url,
                    title=title,
                    company=company,
                    workplace=workplace,
                    language=[],
                    matched_keyword=kw or None,
                    scraped_at=now_iso(),
                )
                if wage_raw:
                    seen[sid].wage.raw = wage_raw
                page_count += 1
            ctx.emit(
                "source.page",
                source=name,
                keyword=kw,
                rows=page_count,
                total=len(seen),
            )
    return list(seen.values())
