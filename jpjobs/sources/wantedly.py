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

import asyncio
import json
import re
from typing import Any
from urllib.parse import urlencode

from jpjobs.pagination import PaginationController
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
    "date": True,
    "pagination": True,
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


def _page_job_posts(
    apollo: dict, page_num: int
) -> tuple[list[tuple[str, dict, dict | None]], int, bool]:
    """Return only the requested result page, excluding cached recommendations."""
    root = apollo.get("ROOT_QUERY") or {}
    index = root.get("projectIndexPageJobPostIndex") or {}
    marker = f'"pageNumber":{page_num}'
    payload = next(
        (
            value
            for key, value in index.items()
            if key.startswith("searchedJobPostsUsingOffset") and marker in key
        ),
        None,
    )
    if not isinstance(payload, dict):
        return [], 0, False

    rows: list[tuple[str, dict, dict | None]] = []
    for item in payload.get("jobPosts") or []:
        job_ref = (item.get("jobPost") or {}).get("__ref")
        job_post = apollo.get(job_ref) if job_ref else item.get("jobPost")
        if not isinstance(job_post, dict):
            continue
        job_id = str(job_post.get("id") or "")
        if not job_id:
            continue
        company_ref = (job_post.get("company") or {}).get("__ref")
        company = apollo.get(company_ref) if company_ref else None
        rows.append((job_id, job_post, company))

    total = int(payload.get("totalCount") or len(rows))
    has_next = page_num * 10 < total
    return rows, total, has_next


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    pacing_ms = opts.get("rate_limit_ms", default_rate_limit_ms)
    seen: dict[str, Job] = {}
    async with make_client() as client:
        for kw in keywords:
            query_seen: set[str] = set()
            pagination = PaginationController(
                opts=opts,
                ctx=ctx,
                source=name,
                keyword=kw,
            )
            for page_num in pagination.page_numbers():
                params = {
                    "country_code": "JP",
                    "page": page_num,
                    "order": "recent",
                }
                if kw:
                    params["keywords"] = kw
                url = f"{BASE}?{urlencode(params)}"
                html = await fetch_html(client, url)
                if not html:
                    ctx.emit(
                        "source.error",
                        source=name,
                        keyword=kw,
                        page=page_num,
                        error="fetch failed",
                    )
                    break
                data = _extract_next_data(html)
                if not data:
                    ctx.emit(
                        "source.error",
                        source=name,
                        keyword=kw,
                        page=page_num,
                        error="__NEXT_DATA__ missing",
                    )
                    break
                try:
                    apollo = data["props"]["pageProps"]["__apollo"][
                        "graphqlGatewayInitialState"
                    ]
                except (KeyError, TypeError):
                    ctx.emit(
                        "source.error",
                        source=name,
                        keyword=kw,
                        page=page_num,
                        error="apollo state missing",
                    )
                    break

                page_rows, available, has_next = _page_job_posts(apollo, page_num)
                query_added = sum(
                    job_id not in query_seen for job_id, _, _ in page_rows
                )
                query_seen.update(job_id for job_id, _, _ in page_rows)
                page_dates = [
                    job_post.get("publishedAt") for _, job_post, _ in page_rows
                ]
                page_count = 0
                page_jobs: list[Job] = []
                for jid, jp, co in page_rows:
                    if jid in seen:
                        continue
                    title = (jp.get("title") or "").strip()[:200]
                    if not title:
                        continue
                    company_payload = jp.get("company") or co or {}
                    company = (company_payload.get("name") or "").strip()
                    # Wantedly doesn't expose workplace in the listing payload.
                    # country is sometimes a __ref; we default to Japan.
                    workplace = "Japan"
                    hiring_types = jp.get("hiringTypes") or []
                    emp = None
                    for ht in hiring_types:
                        hiring_type = (ht or {}).get("type")
                        if hiring_type in _HIRING_MAP:
                            emp = _HIRING_MAP[hiring_type]
                            break
                    published_at = jp.get("publishedAt") or None

                    desc = ""
                    detail_description = jp.get("detailDescription") or {}
                    if isinstance(detail_description, dict):
                        desc = (detail_description.get("plainBody") or "")[:400]

                    snippet = desc
                    if snippet:
                        snippet = (
                            snippet + " | NOTE: apply flow requires Wantedly login."
                        )[:400]
                    else:
                        snippet = "NOTE: apply flow requires Wantedly login."

                    job = Job(
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
                    seen[jid] = job
                    page_jobs.append(job)
                    page_count += 1
                ctx.emit(
                    "source.page",
                    source=name,
                    keyword=kw,
                    page=page_num,
                    rows=len(page_rows),
                    added=page_count,
                    total=len(seen),
                    available=available,
                )
                decision = pagination.decide(
                    page=page_num,
                    rows=len(page_rows),
                    added=query_added,
                    dates=page_dates,
                    has_next=has_next,
                    # Offset pages can contain promoted/reordered projects, so
                    # one all-old page cannot prove that later pages are old.
                    date_ordered=False,
                    stop_on_no_new=True,
                    no_new_tolerance=3,
                )
                if decision.stop:
                    break
                await asyncio.sleep(max(0, pacing_ms) / 1000)
    return list(seen.values())
