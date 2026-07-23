"""GaijinPot Jobs source — English-speaker general jobs in Japan."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, Wage, make_job_id, now_iso
from jpjobs.util.fetch import fetch_html, make_client


name = "gaijinpot"
description = "GaijinPot Jobs — English-speaker general jobs in Japan"
status = "active"
requires_browser = False
supports = {
    "prefecture": False,
    "keywords": True,
    "category": False,
    "employment_type": True,
    "language": True,
    "date": True,
    "pagination": True,
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


def _parse_cards(html: str, keyword: str, seen: dict[str, Job]) -> tuple[int, int]:
    tree = HTMLParser(html)
    cards = tree.css("div.card[data-href^='/en/job/']")
    added = 0
    for card in cards:
        href = card.attributes.get("data-href") or ""
        match = re.match(r"^/en/job/(\d+)", href)
        if not match:
            continue
        source_id = match.group(1)
        if source_id in seen:
            continue
        title_anchor = card.css_first("h3.card-heading a")
        title = title_anchor.text(strip=True)[:200] if title_anchor else ""
        if not title:
            continue
        company = _dl_lookup(card, "Company")
        workplace = _dl_lookup(card, "Location") or "Japan"
        salary_raw = _dl_lookup(card, "Salary")
        date_posted = _dl_lookup(card, "Date") or None

        wage_min = wage_max = None
        wage_unit = None
        if salary_raw:
            numbers = re.findall(r"[\d,]+", salary_raw)
            if numbers:
                try:
                    wage_min = int(numbers[0].replace(",", ""))
                    wage_max = int(numbers[-1].replace(",", ""))
                except ValueError:
                    pass
            lowered = salary_raw.lower()
            if "/ month" in lowered:
                wage_unit = "monthly"
            elif "/ hour" in lowered:
                wage_unit = "hourly"
            elif "/ year" in lowered:
                wage_unit = "annual"

        employment_label = _dl_lookup(card, "Job Type").lower()
        if not employment_label:
            employment_element = card.css_first(".card-label .label")
            employment_label = (
                employment_element.text(strip=True).lower()
                if employment_element
                else ""
            )
        employment_map = {
            "full time": "fulltime",
            "part time": "parttime",
            "contract": "contract",
            "dispatch": "dispatch",
            "freelance": "freelance",
            "intern": "intern",
        }

        seen[source_id] = Job(
            id=make_job_id(name, source_id),
            source=name,
            source_id=source_id,
            url=f"https://jobs.gaijinpot.com{href}",
            title=title,
            company=company,
            workplace=workplace,
            employment_type=employment_map.get(employment_label),
            wage=Wage(
                min=wage_min,
                max=wage_max,
                unit=wage_unit,
                raw=salary_raw,
            ),
            date_posted=date_posted,
            language=["english"],
            matched_keyword=keyword or None,
            scraped_at=now_iso(),
        )
        added += 1
    return len(cards), added


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    pages = opts.get("pages", 2)
    pacing_ms = opts.get("rate_limit_ms", default_rate_limit_ms)
    seen: dict[str, Job] = {}

    async with make_client() as client:
        for keyword in keywords:
            for page_num in range(1, pages + 1):
                params: dict[str, Any] = {"page": page_num}
                if keyword:
                    params["keywords"] = keyword
                url = f"{BASE}?{urlencode(params)}"
                html = await fetch_html(client, url)
                if not html:
                    ctx.emit(
                        "source.error",
                        source=name,
                        keyword=keyword,
                        page=page_num,
                        error="fetch failed",
                    )
                    break
                rows, added = _parse_cards(html, keyword, seen)
                ctx.emit(
                    "source.page",
                    source=name,
                    keyword=keyword,
                    page=page_num,
                    rows=rows,
                    added=added,
                    total=len(seen),
                )
                if rows == 0:
                    break
                await asyncio.sleep(max(0, pacing_ms) / 1000)
    return list(seen.values())
