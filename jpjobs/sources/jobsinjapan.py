"""JobsInJapan source — English-speaker general jobs in Japan."""

from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import make_client, fetch_html


name = "jobsinjapan"
description = "JobsInJapan — English-speaker general jobs in Japan"
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

BASE = "https://jobsinjapan.com/jobs/"


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
            for card in tree.css("article.noo_job"):
                href = card.attributes.get("data-href") or ""
                title_a = card.css_first("h3.loop-item-title a")
                if not href and title_a:
                    href = title_a.attributes.get("href") or ""
                m = re.search(r"/jobs/(\d+)/", href)
                if not m:
                    continue
                sid = m.group(1)
                if sid in seen:
                    continue
                title = title_a.text(strip=True)[:200] if title_a else ""
                if not title:
                    continue
                company_el = card.css_first(".company-name")
                company = company_el.text(strip=True) if company_el else ""
                loc_el = card.css_first(".job-location")
                workplace = loc_el.text(strip=True) if loc_el else "Japan"
                # Employment type
                emp = None
                jt = card.css_first(".loop-job-type a.job-type")
                if jt:
                    label = jt.text(strip=True).lower()
                    emp_map = {
                        "full time": "fulltime",
                        "full-time": "fulltime",
                        "part time": "parttime",
                        "part-time": "parttime",
                        "contract": "contract",
                        "dispatch": "dispatch",
                        "freelance": "freelance",
                        "intern": "intern",
                    }
                    emp = emp_map.get(label)
                seen[sid] = Job(
                    id=make_job_id(name, sid),
                    source=name,
                    source_id=sid,
                    url=href,
                    title=title,
                    company=company,
                    workplace=workplace,
                    employment_type=emp,
                    language=["english"],
                    matched_keyword=kw or None,
                    scraped_at=now_iso(),
                )
                page_count += 1
            ctx.emit(
                "source.page", source=name, keyword=kw, rows=page_count, total=len(seen)
            )
    return list(seen.values())
