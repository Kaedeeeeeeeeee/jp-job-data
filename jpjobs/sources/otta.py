"""otta source — startup careers via en-gage.net.

Status: experimental.

The task spec lists `https://otta.co.jp/jobs` but that path 404s. otta.co.jp
is not an aggregator — it's the corporate site for 株式会社otta (a Fukuoka
startup) — and its current openings live on en-gage.net at
`https://en-gage.net/otta_recruit/`. We scrape that page as a best-effort
single-company source. The keyword filter is applied client-side because
en-gage's recruit pages don't expose a search query parameter for individual
recruit boards.

If/when otta launches an actual aggregated board, swap BASE and selectors.
"""

from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import make_client, fetch_html


name = "otta"
description = "otta (via en-gage.net) — single-company recruit page"
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

BASE = "https://en-gage.net/otta_recruit/"
COMPANY = "株式会社otta"


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    seen: dict[str, Job] = {}
    async with make_client() as client:
        html = await fetch_html(client, BASE)
        if not html:
            ctx.emit("source.error", source=name, error="fetch failed")
            return []
        tree = HTMLParser(html)
        # Anchors look like /otta_recruit/work_4182574/?via_recruit_page=1
        cards: list[tuple[str, str, str]] = []  # (sid, href, raw_text)
        for a in tree.css('a[href*="work_"]'):
            href = a.attributes.get("href") or ""
            m = re.search(r"/(work_\d+)/", href)
            if not m:
                continue
            sid = m.group(1)
            if any(sid == c[0] for c in cards):
                continue
            raw = a.text(separator=" | ", strip=True)
            cards.append((sid, href, raw))

        for kw in keywords:
            kw_low = (kw or "").lower()
            page_count = 0
            for sid, href, raw in cards:
                if kw_low and kw_low not in raw.lower():
                    continue
                if sid in seen:
                    continue
                # Title is the leading phrase before the first salary/location marker.
                title = (
                    re.split(
                        r"月給|時給|年収|福岡|東京|大阪|最終更新", raw, maxsplit=1
                    )[0].strip(" |　")
                    or raw[:80]
                )
                title = title[:200]
                workplace = "Fukuoka" if "福岡" in raw else "Japan"
                wage_raw = ""
                m_wage = re.search(r"(月給|年収|時給)[\s\S]{0,40}円", raw)
                if m_wage:
                    wage_raw = m_wage.group(0)
                full_url = (
                    href
                    if href.startswith("http")
                    else f"https://en-gage.net{href if href.startswith('/') else '/' + href}"
                )
                seen[sid] = Job(
                    id=make_job_id(name, sid),
                    source=name,
                    source_id=sid,
                    url=full_url,
                    title=title,
                    company=COMPANY,
                    workplace=workplace,
                    description_snippet=raw[:400],
                    language=["bilingual"],
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
