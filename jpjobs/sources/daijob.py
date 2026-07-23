"""Daijob source — bilingual professional jobs (English UI)."""

from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import make_client, fetch_html


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
}
default_rate_limit_ms = 1500

# /en/jobs (the landing) redirects to filter widgets; the actual results live on
# /en/jobs/search (which redirects to /en/jobs/search_result).
BASE = "https://www.daijob.com/en/jobs/search"


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    seen: dict[str, Job] = {}
    async with make_client() as client:
        for kw in keywords:
            url = BASE if not kw else f"{BASE}?keyword={kw}"
            html = await fetch_html(client, url)
            if not html:
                ctx.emit("source.error", source=name, keyword=kw, error="fetch failed")
                continue
            tree = HTMLParser(html)
            page_count = 0
            for card in tree.css("article.job-card"):
                title_a = card.css_first("h2.job-card__title a") or card.css_first(
                    'a[href*="/en/jobs/detail/"]'
                )
                if not title_a:
                    continue
                href = title_a.attributes.get("href") or ""
                m = re.search(r"/en/jobs/detail/(\d+)", href)
                if not m:
                    continue
                sid = m.group(1)
                if sid in seen:
                    continue
                title = title_a.text(strip=True)[:200]
                # Company: first non-title detail link in header-info
                company = ""
                header_info = card.css_first(".job-card__header-info")
                if header_info:
                    for a in header_info.css("a"):
                        if "/en/jobs/detail/" in (a.attributes.get("href") or ""):
                            t = a.text(strip=True)
                            if t and t != title:
                                company = t
                                break
                if not company:
                    logo_img = card.css_first(".job-card__logo-wrap img")
                    if logo_img:
                        company = (logo_img.attributes.get("alt") or "").strip()

                workplace = ""
                # Location is inside <dt>Location</dt><dd>...</dd>
                dts = card.css(".job-card__detail dt")
                for dt in dts:
                    if "Location" in dt.text(strip=True):
                        dd = dt.next
                        # next sibling dd
                        while dd is not None and getattr(dd, "tag", "") != "dd":
                            dd = dd.next
                        if dd is not None:
                            parts = [a.text(strip=True) for a in dd.css("a")]
                            workplace = ", ".join(p for p in parts if p)[:200]
                        break
                if not workplace:
                    workplace = "Japan"

                full_url = (
                    href
                    if href.startswith("http")
                    else f"https://www.daijob.com{href.split('?')[0]}"
                )
                seen[sid] = Job(
                    id=make_job_id(name, sid),
                    source=name,
                    source_id=sid,
                    url=full_url,
                    title=title,
                    company=company,
                    workplace=workplace,
                    language=["bilingual"],
                    matched_keyword=kw or None,
                    scraped_at=now_iso(),
                )
                page_count += 1
            ctx.emit(
                "source.page", source=name, keyword=kw, rows=page_count, total=len(seen)
            )
    return list(seen.values())
