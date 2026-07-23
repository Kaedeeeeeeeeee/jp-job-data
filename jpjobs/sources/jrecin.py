"""JREC-IN — Japan's government academic/research job portal (jrecin.jst.go.jp).

Bilingual board run by JST (Japan Science and Technology Agency). Jobs span
universities, national research institutes, and corporate R&D.

⚠️ EXPERIMENTAL: JREC-IN's search form requires POST submission with CSRF token,
not a simple GET. This stub uses a best-effort GET that may return 0 results
depending on session state. Contributors welcome to implement the proper
form-submit flow (see issue tracker).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import make_client, fetch_html


name = "jrecin"
description = (
    "JREC-IN — Japanese government academic/research positions (jrecin.jst.go.jp)"
)
status = "experimental"
requires_browser = False
supports = {
    "prefecture": False,
    "keywords": True,
    "category": False,
    "employment_type": False,
    "language": False,
}
default_rate_limit_ms = 2000

# JREC-IN's English search endpoint
BASE = "https://jrecin.jst.go.jp/seek/SeekJorSearch"


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    seen: dict[str, Job] = {}
    async with make_client() as client:
        for kw in keywords:
            url = f"{BASE}?fn=0&q={quote_plus(kw)}" if kw else f"{BASE}?fn=0"
            html = await fetch_html(client, url)
            if not html:
                ctx.emit("source.error", source=name, keyword=kw, error="fetch failed")
                continue
            tree = HTMLParser(html)
            cards = tree.css('a[href*="SeekJorDetail"]') or tree.css(".result-list a")
            page_count = 0
            for a in cards:
                href = a.attributes.get("href") or ""
                m = re.search(r"id=([A-Z0-9]+)", href)
                if not m:
                    continue
                sid = m.group(1)
                if sid in seen:
                    continue
                title = a.text(strip=True)[:200]
                if not title:
                    continue
                # Walk to a parent row for company / location text
                row = a.parent
                row_text = (row.text(separator=" ") if row else "")[:600]
                company_match = re.search(
                    r"(機関名|Institution)\s*[:：]\s*([^\n|]+)", row_text
                )
                company = company_match.group(2).strip()[:200] if company_match else ""
                full_url = (
                    href
                    if href.startswith("http")
                    else f"https://jrecin.jst.go.jp{href}"
                )
                seen[sid] = Job(
                    id=make_job_id(name, sid),
                    source=name,
                    source_id=sid,
                    url=full_url,
                    title=title,
                    company=company,
                    workplace="Japan",
                    language=["bilingual"],
                    matched_keyword=kw or None,
                    scraped_at=now_iso(),
                )
                page_count += 1
            ctx.emit(
                "source.page", source=name, keyword=kw, rows=page_count, total=len(seen)
            )
    return list(seen.values())
