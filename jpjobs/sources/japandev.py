"""Japan Dev source via the site's public Algolia search index."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, Wage, make_job_id, now_iso
from jpjobs.util.fetch import fetch_html, make_client


name = "japandev"
description = "Japan Dev — English-first IT/software jobs in Japan"
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
default_rate_limit_ms = 1000

ALGOLIA_INDEX = "Job_production"
LANDING_URL = "https://japan-dev.com/jobs"


def _search_config(html: str) -> tuple[str, str] | None:
    """Read the public Algolia search configuration exposed by the frontend."""
    application_id = re.search(r'applicationId:"([^"]+)"', html)
    api_key = re.search(r'apiKey:"([^"]+)"', html)
    if not application_id or not api_key:
        return None
    return application_id.group(1), api_key.group(1)


def _text(value: Any) -> str:
    if not value:
        return ""
    return HTMLParser(f"<div>{value}</div>").text(separator=" ", strip=True)


def _employment_type(hit: dict[str, Any]) -> str | None:
    value = str(hit.get("contract_type") or hit.get("employment_type") or "").lower()
    if "full" in value:
        return "fulltime"
    if "part" in value:
        return "parttime"
    if "contract" in value:
        return "contract"
    if "intern" in value:
        return "intern"
    if "freelance" in value:
        return "freelance"
    return None


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    pages = opts.get("pages", 2)
    pacing_ms = opts.get("rate_limit_ms", default_rate_limit_ms)
    seen: dict[str, Job] = {}

    async with make_client() as client:
        landing_html = await fetch_html(client, LANDING_URL)
        config = _search_config(landing_html or "")
        if not config:
            ctx.emit(
                "source.error",
                source=name,
                error="public Algolia search configuration missing",
            )
            return []
        application_id, search_key = config
        algolia_url = f"https://{application_id}-dsn.algolia.net/1/indexes/*/queries"
        headers = {
            "x-algolia-application-id": application_id,
            "x-algolia-api-key": search_key,
            "content-type": "application/json",
        }
        for keyword in keywords:
            for page_num in range(pages):
                params = urlencode(
                    {
                        "query": keyword,
                        "hitsPerPage": 30,
                        "page": page_num,
                    }
                )
                payload = {
                    "requests": [
                        {
                            "indexName": ALGOLIA_INDEX,
                            "params": params,
                        }
                    ]
                }
                try:
                    response = await client.post(
                        algolia_url,
                        headers=headers,
                        json=payload,
                    )
                    if response.status_code in (403, 429):
                        ctx.emit(
                            "source.error",
                            source=name,
                            keyword=keyword,
                            page=page_num + 1,
                            error=f"Algolia HTTP {response.status_code}",
                        )
                        break
                    response.raise_for_status()
                    result = response.json()["results"][0]
                except Exception as exc:
                    ctx.emit(
                        "source.error",
                        source=name,
                        keyword=keyword,
                        page=page_num + 1,
                        error=f"Algolia query failed: {exc}",
                    )
                    break

                added = 0
                for hit in result.get("hits") or []:
                    source_id = str(hit.get("objectID") or "")
                    title = str(hit.get("title") or "").strip()
                    slug = str(hit.get("slug") or "").strip()
                    company_payload = hit.get("company") or {}
                    company_slug = str(company_payload.get("slug") or "").strip()
                    if not source_id or not title or not slug or not company_slug:
                        continue
                    if source_id in seen:
                        continue

                    description_parts = [
                        _text(hit.get("intro")),
                        _text(hit.get("details")),
                        _text(hit.get("requirements")),
                    ]
                    description = " ".join(part for part in description_parts if part)
                    salary_min = hit.get("salary_min")
                    salary_max = hit.get("salary_max")
                    seen[source_id] = Job(
                        id=make_job_id(name, source_id),
                        source=name,
                        source_id=source_id,
                        url=f"https://japan-dev.com/jobs/{company_slug}/{slug}",
                        title=title[:200],
                        company=str(
                            hit.get("company_name") or company_payload.get("name") or ""
                        ).strip(),
                        description=description,
                        description_snippet=description[:400],
                        workplace=str(hit.get("location") or "Japan").strip(),
                        remote="remote" in str(hit.get("remote_level") or "").lower(),
                        wage=Wage(
                            min=int(salary_min) if salary_min else None,
                            max=int(salary_max) if salary_max else None,
                            unit="annual" if salary_min or salary_max else None,
                            raw=(
                                f"JPY {salary_min or ''}–{salary_max or ''} annual"
                                if salary_min or salary_max
                                else ""
                            ),
                        ),
                        employment_type=_employment_type(hit),
                        date_posted=hit.get("published_at") or hit.get("job_post_date"),
                        language=["english"],
                        matched_keyword=keyword or None,
                        scraped_at=now_iso(),
                    )
                    added += 1

                ctx.emit(
                    "source.page",
                    source=name,
                    keyword=keyword,
                    page=page_num + 1,
                    rows=len(result.get("hits") or []),
                    added=added,
                    total=len(seen),
                    available=result.get("nbHits"),
                )
                if page_num + 1 >= int(result.get("nbPages") or 0):
                    break

                import asyncio

                await asyncio.sleep(max(0, pacing_ms) / 1000)

    return list(seen.values())
