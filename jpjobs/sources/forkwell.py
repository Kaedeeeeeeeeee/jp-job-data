"""Forkwell Jobs source — engineer-focused jobs in Japan (Japanese site)."""

from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import make_client, fetch_html


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
}
default_rate_limit_ms = 1500

BASE = "https://jobs.forkwell.com/jobs/search"


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    seen: dict[str, Job] = {}
    async with make_client() as client:
        for kw in keywords:
            url = BASE if not kw else f"{BASE}?q={kw}"
            html = await fetch_html(client, url)
            if not html:
                ctx.emit("source.error", source=name, keyword=kw, error="fetch failed")
                continue
            tree = HTMLParser(html)
            page_count = 0
            # Each card is a div.row with a title anchor .job-list__link
            for link in tree.css("a.job-list__link"):
                href = link.attributes.get("href") or ""
                m = re.match(r"^/([A-Za-z0-9_-]+)/jobs/(\d+)", href)
                if not m:
                    continue
                company_slug, job_id = m.group(1), m.group(2)
                sid = f"{company_slug}/{job_id}"
                if sid in seen:
                    continue
                title_span = link.css_first("span")
                title = (
                    title_span.text(strip=True) if title_span else link.text(strip=True)
                )[:200]
                if not title:
                    continue
                # Walk up to the surrounding .row
                row = link.parent
                while row is not None and "row" not in (
                    row.attributes.get("class") or ""
                ):
                    row = row.parent
                company = ""
                workplace = "Japan"
                if row is not None:
                    detail = row.css_first(".avatar__detail")
                    if detail:
                        company = detail.text(strip=True)
                    # Location follows an <i class="fas fa-map-marker-alt">
                    for li in row.css("li.list-inline-item"):
                        icon = li.css_first("i.fa-map-marker-alt")
                        if icon:
                            workplace = li.text(strip=True) or workplace
                            break
                if not company:
                    company = company_slug.replace("-", " ").title()
                seen[sid] = Job(
                    id=make_job_id(name, sid),
                    source=name,
                    source_id=sid,
                    url=f"https://jobs.forkwell.com{href}",
                    title=title,
                    company=company,
                    workplace=workplace,
                    matched_keyword=kw or None,
                    scraped_at=now_iso(),
                )
                page_count += 1
            ctx.emit(
                "source.page", source=name, keyword=kw, rows=page_count, total=len(seen)
            )
    return list(seen.values())
