"""Indeed Japan source via Playwright.

Indeed actively blocks naive HTTP scrapers (jp.indeed.com requires JS rendering
and Cloudflare-style challenges). We use Playwright with a real Chromium UA
to get past basic anti-bot. Even so, expect intermittent 0-result runs when
Indeed rotates challenges. Mark as 'experimental'.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote_plus

from jpjobs.schema import Job, make_job_id, now_iso


name = "indeed"
description = "Indeed Japan (jp.indeed.com) — best effort, anti-bot prone"
status = "experimental"
requires_browser = True
supports = {
    "prefecture": True,
    "keywords": True,
    "category": False,
    "employment_type": True,
    "language": False,
}
default_rate_limit_ms = 3000

BASE = "https://jp.indeed.com/jobs"


def _build_url(keyword: str, location: str | None) -> str:
    parts = []
    if keyword:
        parts.append(f"q={quote_plus(keyword)}")
    if location:
        parts.append(f"l={quote_plus(location)}")
    parts.append("sort=date")
    return f"{BASE}?" + "&".join(parts)


async def _extract(page) -> list[dict]:
    return await page.evaluate("""
        () => {
            // JK lives on <a class="jcs-JobTitle"> — walk up to the card container
            const anchors = document.querySelectorAll('a[data-jk]');
            const out = [];
            const seenJk = new Set();
            for (const a of anchors) {
                const jk = a.getAttribute('data-jk');
                if (!jk || seenJk.has(jk)) continue;
                seenJk.add(jk);
                // Walk up to find the card (job_seen_beacon or its parent li)
                let card = a.closest('div.job_seen_beacon') || a.closest('li') || a.parentElement;
                const title = a.innerText.trim();
                const companyEl = card?.querySelector('[data-testid="company-name"], span.companyName, [class*="company"]');
                const company = companyEl ? companyEl.innerText.trim() : '';
                const locEl = card?.querySelector('[data-testid="text-location"], div.companyLocation, [class*="location"]');
                const location = locEl ? locEl.innerText.trim() : '';
                const snippetEl = card?.querySelector('.job-snippet, [class*="snippet"]');
                const snippet = snippetEl ? snippetEl.innerText.replace(/\\s+/g, ' ').slice(0, 400) : '';
                const wageEl = card?.querySelector('[data-testid="attribute_snippet_testid"], .salary-snippet-container, [class*="metadata"]');
                const wage = wageEl ? wageEl.innerText.trim() : '';
                out.push({ jk, title, company, location, snippet, wage });
            }
            return out;
        }
    """)


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    location = opts.get("location") or ""
    pages = opts.get("pages", 2)

    browser = await ctx.get_browser()
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="ja-JP",
    )
    page = await context.new_page()

    seen: dict[str, Job] = {}
    try:
        for kw in keywords:
            url = _build_url(kw, location)
            for page_num in range(pages):
                paged = f"{url}&start={page_num * 10}" if page_num else url
                try:
                    await page.goto(paged, wait_until="domcontentloaded", timeout=20000)
                    await page.wait_for_timeout(2500)
                    rows = await _extract(page)
                    added = 0
                    for r in rows:
                        sid = r["jk"]
                        if sid in seen:
                            continue
                        # Wage parsing
                        wage_raw = r["wage"]
                        wage_min = wage_max = None
                        wage_unit = None
                        nums = re.findall(r"[\d,]+", wage_raw)
                        if nums:
                            try:
                                wage_min = int(nums[0].replace(",", ""))
                                wage_max = int(nums[-1].replace(",", ""))
                            except ValueError:
                                pass
                        if "時給" in wage_raw or "/hr" in wage_raw.lower():
                            wage_unit = "hourly"
                        elif "月給" in wage_raw:
                            wage_unit = "monthly"
                        elif "年俸" in wage_raw or "/year" in wage_raw.lower():
                            wage_unit = "annual"
                        from jpjobs.schema import Wage

                        seen[sid] = Job(
                            id=make_job_id(name, sid),
                            source=name,
                            source_id=sid,
                            url=f"https://jp.indeed.com/viewjob?jk={sid}",
                            title=r["title"],
                            company=r["company"],
                            workplace=r["location"],
                            description_snippet=r["snippet"],
                            wage=Wage(
                                min=wage_min, max=wage_max, unit=wage_unit, raw=wage_raw
                            ),
                            matched_keyword=kw or None,
                            scraped_at=now_iso(),
                        )
                        added += 1
                    ctx.emit(
                        "source.page",
                        source=name,
                        keyword=kw,
                        page=page_num + 1,
                        rows=len(rows),
                        added=added,
                        total=len(seen),
                    )
                    if not rows:
                        break
                except Exception as e:
                    ctx.emit(
                        "source.error",
                        source=name,
                        keyword=kw,
                        page=page_num + 1,
                        error=str(e),
                    )
                    break
                await asyncio.sleep(3)
    finally:
        await context.close()
    return list(seen.values())
