"""Japan-Dev source — English-first IT/software jobs in Japan."""

from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import make_client, fetch_html


name = "japandev"
description = "Japan-Dev — English-first IT/software jobs in Japan"
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

BASE = "https://japan-dev.com/jobs"


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    seen: dict[str, Job] = {}
    async with make_client() as client:
        for kw in keywords:
            url = BASE if not kw else f"{BASE}?search={kw}"
            html = await fetch_html(client, url)
            if not html:
                ctx.emit("source.error", source=name, keyword=kw, error="fetch failed")
                continue
            tree = HTMLParser(html)
            page_count = 0
            # Cards live in div.job-item__inner with title anchors at .job-item__title
            for card in tree.css(".job-item__inner"):
                title_a = card.css_first("a.job-item__title")
                if not title_a:
                    continue
                href = title_a.attributes.get("href") or ""
                m = re.match(r"^/jobs/([^/]+)/([^/?#]+)", href)
                if not m:
                    continue
                company_slug, job_slug = m.group(1), m.group(2)
                sid = f"{company_slug}/{job_slug}"
                if sid in seen:
                    continue
                title = title_a.text(strip=True)[:200]
                # Company: prefer the contract-type box text, fall back to logo alt or slug
                company = ""
                ct = card.css_first(".job-item__contract-type")
                if ct:
                    company = ct.text(strip=True)
                if not company:
                    logo = card.css_first("img.company-logo__inner")
                    if logo:
                        company = (logo.attributes.get("alt") or "").strip()
                if not company:
                    company = company_slug.replace("-", " ").title()
                card_text = card.text(separator=" ")
                loc_m = re.search(
                    r"(Tokyo|Osaka|Yokohama|Fukuoka|Sapporo|Nagoya|Kyoto|Sendai|Kobe|Remote)",
                    card_text,
                    re.I,
                )
                workplace = loc_m.group(1) if loc_m else "Japan"
                seen[sid] = Job(
                    id=make_job_id(name, sid),
                    source=name,
                    source_id=sid,
                    url=f"https://japan-dev.com{href.split('?')[0]}",
                    title=title,
                    company=company,
                    workplace=workplace,
                    language=["english"],
                    matched_keyword=kw or None,
                    scraped_at=now_iso(),
                )
                page_count += 1
            ctx.emit(
                "source.page", source=name, keyword=kw, rows=page_count, total=len(seen)
            )
    return list(seen.values())
