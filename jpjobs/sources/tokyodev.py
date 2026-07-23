"""TokyoDev source — English-first IT jobs in Japan."""

from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import make_client, fetch_html


name = "tokyodev"
description = "TokyoDev — English-first IT/software jobs in Japan"
status = "active"
requires_browser = False
supports = {
    "prefecture": False,
    "keywords": True,
    "category": False,
    "employment_type": False,
    "language": False,  # all listings are English-friendly by design
}
default_rate_limit_ms = 1500

BASE = "https://www.tokyodev.com/jobs"


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    seen: dict[str, Job] = {}
    async with make_client() as client:
        for kw in keywords:
            url = BASE if not kw else f"{BASE}?query={kw}"
            html = await fetch_html(client, url)
            if not html:
                ctx.emit("source.error", source=name, keyword=kw, error="fetch failed")
                continue
            tree = HTMLParser(html)
            cards = tree.css('a[href^="/companies/"]')
            page_count = 0
            for a in cards:
                href = a.attributes.get("href") or ""
                if "/jobs/" not in href:
                    continue
                # /companies/{co}/jobs/{slug}
                m = re.search(r"/companies/([^/]+)/jobs/([^/?#]+)", href)
                if not m:
                    continue
                company_slug, job_slug = m.group(1), m.group(2)
                sid = f"{company_slug}/{job_slug}"
                if sid in seen:
                    continue
                title_el = a.css_first("h3") or a.css_first(".job-title") or a
                title = title_el.text(strip=True)[:200] if title_el else ""
                company = company_slug.replace("-", " ").title()
                # Try to find location text in surrounding context
                parent_text = (a.parent.text(separator=" ") if a.parent else "")[:400]
                loc_m = re.search(
                    r"(Tokyo|Osaka|Yokohama|Fukuoka|Sapporo|Nagoya|Kyoto|Remote)",
                    parent_text,
                    re.I,
                )
                workplace = loc_m.group(1) if loc_m else "Japan"
                seen[sid] = Job(
                    id=make_job_id(name, sid),
                    source=name,
                    source_id=sid,
                    url=f"https://www.tokyodev.com{href.split('?')[0]}",
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
