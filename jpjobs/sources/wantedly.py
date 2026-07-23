"""Wantedly Projects source — Japan startup/mid-career job posts.

Wantedly's public /projects index ships its current page of postings as Apollo
client state inside the page's __NEXT_DATA__ blob. We parse that JSON directly
rather than scraping DOM cards — it's stable, gives us company name + slug,
hiring type, occupation, published date, and entry counts.

The public list is enough for discovery; the full apply flow on a project
requires a Wantedly login, which we don't attempt. We note that in
description_snippet so downstream callers know.
"""

from __future__ import annotations

import json
import re
from typing import Any

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import make_client, fetch_html


name = "wantedly"
description = (
    "Wantedly — Japan startup / mid-career project listings (login required to apply)"
)
status = "active"
requires_browser = False
supports = {
    "prefecture": False,
    "keywords": True,
    "category": False,
    "employment_type": False,
    "language": True,
}
default_rate_limit_ms = 2000

BASE = "https://www.wantedly.com/projects"

# hiring_types from Wantedly's GraphQL -> our EmploymentType
_HIRING_MAP = {
    "MID_CAREER": "fulltime",
    "NEW_GRADUATE": "fulltime",
    "INTERNSHIP": "intern",
    "SIDE_JOB": "parttime",
    "PART_TIME": "parttime",
    "CONTRACT": "contract",
    "OUTSOURCING": "freelance",
    "FREELANCE": "freelance",
}


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


def _iter_job_posts(apollo: dict):
    """Yield (job_id, jobpost_dict, company_dict_or_none) from Apollo cache."""
    for key, val in apollo.items():
        if not key.startswith("JobPost:") or not isinstance(val, dict):
            continue
        jid = val.get("id") or ""
        if not jid:
            # key looks like 'JobPost:{"id":"1671536"}'
            m = re.search(r'"id":"(\d+)"', key)
            if m:
                jid = m.group(1)
        if not jid:
            continue
        company_ref = (val.get("company") or {}).get("__ref")
        company = apollo.get(company_ref) if company_ref else None
        yield jid, val, company


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    seen: dict[str, Job] = {}
    async with make_client() as client:
        for kw in keywords:
            qs = "country_code=JP"
            if kw:
                qs += f"&q={kw}"
            url = f"{BASE}?{qs}"
            html = await fetch_html(client, url)
            if not html:
                ctx.emit("source.error", source=name, keyword=kw, error="fetch failed")
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
            try:
                apollo = data["props"]["pageProps"]["__apollo"][
                    "graphqlGatewayInitialState"
                ]
            except (KeyError, TypeError):
                ctx.emit(
                    "source.error",
                    source=name,
                    keyword=kw,
                    error="apollo state missing",
                )
                continue

            page_count = 0
            for jid, jp, co in _iter_job_posts(apollo):
                if jid in seen:
                    continue
                title = (jp.get("title") or "").strip()[:200]
                if not title:
                    continue
                company = (co or {}).get("name", "").strip() if co else ""
                # Wantedly doesn't expose workplace in the listing payload.
                # country is sometimes a __ref; we default to Japan.
                workplace = "Japan"
                hiring_types = jp.get("hiringTypes") or []
                emp = None
                for ht in hiring_types:
                    t = (ht or {}).get("type")
                    if t in _HIRING_MAP:
                        emp = _HIRING_MAP[t]
                        break
                published_at = jp.get("publishedAt") or None

                desc = ""
                dd = jp.get("detailDescription") or {}
                if isinstance(dd, dict):
                    desc = (dd.get("plainBody") or "")[:400]

                snippet = desc
                if snippet:
                    snippet = (
                        snippet + " | NOTE: apply flow requires Wantedly login."
                    )[:400]
                else:
                    snippet = "NOTE: apply flow requires Wantedly login."

                seen[jid] = Job(
                    id=make_job_id(name, jid),
                    source=name,
                    source_id=jid,
                    url=f"https://www.wantedly.com/projects/{jid}",
                    title=title,
                    company=company,
                    workplace=workplace,
                    employment_type=emp,
                    description_snippet=snippet,
                    date_posted=published_at,
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
