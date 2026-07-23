"""GaijinPot Jobs source — English-speaker general jobs in Japan.

Listings live at /en/job and accept ?q= for keywords.

Limitation: GaijinPot's listing cards expose title + company + location + salary
+ employment type, but not a job description summary. `description_snippet`
stays empty. Full descriptions live on detail pages, which this source
doesn't fetch.
"""

from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, Wage, make_job_id, now_iso
from jpjobs.util.fetch import make_client, fetch_html


name = "gaijinpot"
description = "GaijinPot Jobs — English-speaker general jobs in Japan"
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

BASE = "https://jobs.gaijinpot.com/en/job"


def _dl_lookup(card, label: str) -> str:
    for dt in card.css("dt"):
        if dt.text(strip=True).lower() == label.lower():
            dd = dt.next
            while dd is not None and getattr(dd, "tag", "") != "dd":
                dd = dd.next
            if dd is not None:
                return dd.text(strip=True)
    return ""


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
            # Cards: div.card[data-href="/en/job/<id>"]
            for card in tree.css("div.card[data-href^='/en/job/']"):
                href = card.attributes.get("data-href") or ""
                m = re.match(r"^/en/job/(\d+)", href)
                if not m:
                    continue
                sid = m.group(1)
                if sid in seen:
                    continue
                title_a = card.css_first("h3.card-heading a")
                title = title_a.text(strip=True)[:200] if title_a else ""
                if not title:
                    continue
                company = _dl_lookup(card, "Company")
                workplace = _dl_lookup(card, "Location") or "Japan"
                salary_raw = _dl_lookup(card, "Salary")
                date_posted = _dl_lookup(card, "Date") or None
                # Parse salary like "¥236,000 ~ ¥330,000 / Month"
                wage_min = wage_max = None
                wage_unit = None
                if salary_raw:
                    nums = re.findall(r"[\d,]+", salary_raw)
                    if nums:
                        try:
                            wage_min = int(nums[0].replace(",", ""))
                            wage_max = int(nums[-1].replace(",", ""))
                        except ValueError:
                            pass
                    if "/ Month" in salary_raw or "/Month" in salary_raw:
                        wage_unit = "monthly"
                    elif "/ Hour" in salary_raw or "/Hour" in salary_raw:
                        wage_unit = "hourly"
                    elif "/ Year" in salary_raw or "/Year" in salary_raw:
                        wage_unit = "annual"
                # Snippet from any visible card body text
                body = card.css_first(".card-body, .job-description, .card-content")
                snippet = body.text(separator=" ", strip=True)[:400] if body else ""
                emp_label_el = card.css_first(".card-label .label")
                emp_label = (
                    emp_label_el.text(strip=True).lower() if emp_label_el else ""
                )
                emp_map = {
                    "full time": "fulltime",
                    "part time": "parttime",
                    "contract": "contract",
                    "dispatch": "dispatch",
                    "freelance": "freelance",
                    "intern": "intern",
                }
                emp = emp_map.get(emp_label)
                seen[sid] = Job(
                    id=make_job_id(name, sid),
                    source=name,
                    source_id=sid,
                    url=f"https://jobs.gaijinpot.com{href}",
                    title=title,
                    company=company,
                    workplace=workplace,
                    employment_type=emp,
                    wage=Wage(
                        min=wage_min, max=wage_max, unit=wage_unit, raw=salary_raw
                    ),
                    description_snippet=snippet,
                    date_posted=date_posted,
                    language=["english"],
                    matched_keyword=kw or None,
                    scraped_at=now_iso(),
                )
                page_count += 1
            ctx.emit(
                "source.page", source=name, keyword=kw, rows=page_count, total=len(seen)
            )
    return list(seen.values())
