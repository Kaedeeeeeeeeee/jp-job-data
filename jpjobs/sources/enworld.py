"""en world Japan source — bilingual professional recruiter.

Status: experimental.

en world Japan's careers portal at `https://jobs.enworld.com/s/` is a
Salesforce Experience Cloud (Aura) SPA. The initial HTTP response is a thin
loading shell — actual job data is fetched after page load via signed Aura
RPC POSTs. Plain HTTP fetches return no listings.

To bring this to `active` we'd need either:
  * the Aura `service.apexremote` or `aura?r=...&aura.context=...` POST
    flow with valid CSRF + framework tokens, which are minted per session,
  * or a stealth-browser path that runs the SPA and reads the rendered DOM.

For now we fetch the shell, extract any anchors that happen to point at
`/s/job-details/<id>` (in case the SSR ever exposes a few), and otherwise
return [].
"""

from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import make_client, fetch_html


name = "enworld"
description = (
    "en world Japan — bilingual professional recruiter (SPA, listings not in HTML)"
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
default_rate_limit_ms = 2000

# The /en/jobs path 301s to jobs.enworld.com/s/?language=ja; we go straight
# to the portal and request English where possible.
BASE = "https://jobs.enworld.com/s/"


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    seen: dict[str, Job] = {}
    async with make_client() as client:
        for kw in keywords:
            qs = "language=en"
            if kw:
                qs += f"&searchKeyword={kw}"
            url = f"{BASE}?{qs}"
            html = await fetch_html(client, url)
            if not html:
                ctx.emit(
                    "source.error",
                    source=name,
                    keyword=kw,
                    error="fetch failed",
                )
                continue
            tree = HTMLParser(html)
            page_count = 0
            for a in tree.css('a[href*="/job-details/"], a[href*="/jobs/"]'):
                href = a.attributes.get("href") or ""
                m = re.search(r"/(?:job-details|jobs)/([A-Za-z0-9_-]+)", href)
                if not m:
                    continue
                sid = m.group(1)
                if sid in seen:
                    continue
                title = a.text(strip=True)[:200]
                if not title:
                    continue
                full_url = (
                    href
                    if href.startswith("http")
                    else f"https://jobs.enworld.com{href}"
                )
                seen[sid] = Job(
                    id=make_job_id(name, sid),
                    source=name,
                    source_id=sid,
                    url=full_url,
                    title=title,
                    company="",
                    workplace="Japan",
                    language=["english"],
                    matched_keyword=kw or None,
                    scraped_at=now_iso(),
                )
                page_count += 1
            if page_count == 0:
                ctx.emit(
                    "source.page",
                    source=name,
                    keyword=kw,
                    rows=0,
                    total=len(seen),
                    note="SPA shell — no listings in initial HTML",
                )
            else:
                ctx.emit(
                    "source.page",
                    source=name,
                    keyword=kw,
                    rows=page_count,
                    total=len(seen),
                )
    return list(seen.values())
