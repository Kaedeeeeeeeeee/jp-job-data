"""Wellfound (formerly AngelList Talent) — global startups, Tokyo filter.

Status: experimental.

Wellfound's job pages are fronted by Datadome + Cloudflare bot protection.
A plain httpx GET to https://wellfound.com/jobs?l=tokyo returns HTTP 403 with
a `x-datadome: protected` header — no listings are served without solving a
client-side challenge. We therefore emit a fetch error and return [] from
this source until we either (a) get an API key, (b) add a stealth-browser
path, or (c) accept that wellfound is unreachable from this client.

The scaffolding below is left intact so that if/when the page becomes
fetchable, the parser keeps working: Wellfound ships its initial listings as
a JSON blob in the Next.js `__NEXT_DATA__` script tag.
"""

from __future__ import annotations

import json
import re
from typing import Any

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import make_client, fetch_html


name = "wellfound"
description = (
    "Wellfound (ex-AngelList) — global startups, Tokyo filter (anti-bot locked)"
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
default_rate_limit_ms = 3000

BASE = "https://wellfound.com/jobs"


def _extract_next_data(html: str) -> dict | None:
    m = re.search(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.+?)</script>',
        html,
        re.DOTALL,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _walk_for_jobs(node, out: list[dict]) -> None:
    """Walk the __NEXT_DATA__ tree and pull out anything that looks like a job listing."""
    if isinstance(node, dict):
        # Heuristic: a job has title + slug or id + company-ish field.
        has_title = "title" in node and isinstance(node["title"], str)
        has_id = "id" in node or "slug" in node
        if (
            has_title
            and has_id
            and ("startup" in node or "company" in node or "companyName" in node)
        ):
            out.append(node)
        for v in node.values():
            _walk_for_jobs(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_for_jobs(v, out)


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    seen: dict[str, Job] = {}
    async with make_client() as client:
        for kw in keywords:
            qs = "l=tokyo"
            if kw:
                qs += f"&keywords={kw}"
            url = f"{BASE}?{qs}"
            html = await fetch_html(client, url)
            if not html:
                ctx.emit(
                    "source.error",
                    source=name,
                    keyword=kw,
                    error="fetch failed (likely Datadome/Cloudflare bot block)",
                )
                continue
            data = _extract_next_data(html)
            if not data:
                ctx.emit(
                    "source.error",
                    source=name,
                    keyword=kw,
                    error="__NEXT_DATA__ missing",
                )
                continue
            raw_jobs: list[dict] = []
            _walk_for_jobs(data, raw_jobs)
            page_count = 0
            for jp in raw_jobs:
                sid = str(jp.get("id") or jp.get("slug") or "")
                if not sid or sid in seen:
                    continue
                title = (jp.get("title") or "").strip()[:200]
                if not title:
                    continue
                company_node = jp.get("startup") or jp.get("company") or {}
                if isinstance(company_node, dict):
                    company = company_node.get("name") or company_node.get(
                        "companyName", ""
                    )
                else:
                    company = jp.get("companyName") or ""
                slug = jp.get("slug") or sid
                seen[sid] = Job(
                    id=make_job_id(name, sid),
                    source=name,
                    source_id=sid,
                    url=f"https://wellfound.com/jobs/{slug}",
                    title=title,
                    company=str(company).strip(),
                    workplace="Tokyo",
                    language=["bilingual"],
                    matched_keyword=kw or None,
                    scraped_at=now_iso(),
                )
                page_count += 1
            ctx.emit(
                "source.page",
                source=name,
                keyword=kw,
                rows=page_count,
                total=len(seen),
            )
    return list(seen.values())
