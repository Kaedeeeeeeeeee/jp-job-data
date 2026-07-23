"""Optional detail-page enrichment using schema.org JobPosting data."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from selectolax.parser import HTMLParser

from jpjobs.normalize import clean_text, normalize_job
from jpjobs.schema import Job, Wage
from jpjobs.util.fetch import make_client


SKIP_DETAIL_SOURCES = {"hellowork", "linkedin", "wantedly"}


@dataclass
class DetailStats:
    attempted: int = 0
    enriched: int = 0
    unavailable: int = 0
    errors: int = 0


def _clean_json_blob(value: str) -> str:
    candidate = value.strip()
    candidate = re.sub(r"^\s*//\s*<!--", "", candidate)
    candidate = re.sub(r"^\s*<!--", "", candidate)
    candidate = re.sub(r"-->\s*;?\s*$", "", candidate)
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        return candidate[start : end + 1]
    return candidate


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _iter_dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_dicts(nested)


def _is_job_posting(value: dict[str, Any]) -> bool:
    value_type = value.get("@type")
    if isinstance(value_type, str) and value_type.lower() == "jobposting":
        return True
    if isinstance(value_type, list) and any(
        str(item).lower() == "jobposting" for item in value_type
    ):
        return True
    return bool(
        value.get("title")
        and value.get("description")
        and (value.get("datePosted") or value.get("hiringOrganization"))
    )


def extract_job_posting(html: str) -> dict[str, Any] | None:
    tree = HTMLParser(html)
    for script in tree.css('script[type="application/ld+json"]'):
        candidate = _clean_json_blob(script.text())
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        for value in _iter_dicts(payload):
            if _is_job_posting(value):
                return value
    return None


def _html_to_text(value: str | None) -> str:
    if not value:
        return ""
    return clean_text(HTMLParser(f"<div>{value}</div>").text(separator=" "))


def _organization_name(value: Any) -> str:
    if isinstance(value, dict):
        return clean_text(value.get("name"))
    if isinstance(value, str):
        return clean_text(value)
    return ""


def _location(value: Any) -> tuple[str, str | None]:
    locations = value if isinstance(value, list) else [value]
    parts: list[str] = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address") or {}
        if isinstance(address, str):
            parts.append(clean_text(address))
            continue
        if not isinstance(address, dict):
            continue
        for key in ("addressRegion", "addressLocality", "streetAddress"):
            text = clean_text(address.get(key))
            if text and text not in parts:
                parts.append(text)
    return ", ".join(parts), None


def _employment_type(value: Any) -> str | None:
    values = value if isinstance(value, list) else [value]
    mapping = {
        "FULL_TIME": "fulltime",
        "FULL-TIME": "fulltime",
        "PART_TIME": "parttime",
        "PART-TIME": "parttime",
        "CONTRACTOR": "contract",
        "CONTRACT": "contract",
        "TEMPORARY": "dispatch",
        "INTERN": "intern",
        "INTERNSHIP": "intern",
    }
    for item in values:
        normalized = clean_text(str(item)).upper().replace(" ", "_")
        if normalized in mapping:
            return mapping[normalized]
    return None


def _wage(value: Any) -> Wage | None:
    if not isinstance(value, dict):
        return None
    currency = clean_text(value.get("currency"))
    amount = value.get("value") or value
    if not isinstance(amount, dict):
        return None

    def number(key: str) -> int | None:
        raw = amount.get(key)
        try:
            return int(float(raw)) if raw is not None else None
        except (TypeError, ValueError):
            return None

    wage_min = number("minValue") or number("value")
    wage_max = number("maxValue") or wage_min
    unit_raw = clean_text(amount.get("unitText")).upper()
    unit_map = {
        "HOUR": "hourly",
        "HOURLY": "hourly",
        "MONTH": "monthly",
        "MONTHLY": "monthly",
        "YEAR": "annual",
        "YEARLY": "annual",
        "ANNUAL": "annual",
    }
    unit = unit_map.get(unit_raw)
    if not any((wage_min, wage_max, unit)):
        return None
    raw_parts = [currency, str(wage_min or ""), str(wage_max or ""), unit_raw]
    return Wage(
        min=wage_min,
        max=wage_max,
        unit=unit,
        raw=" ".join(part for part in raw_parts if part),
    )


def apply_job_posting(job: Job, posting: dict[str, Any]) -> bool:
    before = (
        job.company,
        job.description_snippet,
        job.workplace,
        job.date_posted,
        job.employment_type,
        job.wage.raw,
    )
    job.title = clean_text(posting.get("title")) or job.title
    job.company = _organization_name(posting.get("hiringOrganization")) or job.company

    description = _html_to_text(posting.get("description"))
    if len(description) > len(job.description):
        job.description = description
        job.description_snippet = description[:400]

    workplace, _ = _location(posting.get("jobLocation"))
    if workplace:
        job.workplace = workplace
    if clean_text(posting.get("jobLocationType")).upper() == "TELECOMMUTE":
        job.remote = True

    job.date_posted = clean_text(posting.get("datePosted")) or job.date_posted
    job.employment_type = (
        _employment_type(posting.get("employmentType")) or job.employment_type
    )
    parsed_wage = _wage(posting.get("baseSalary"))
    if parsed_wage and not (job.wage.raw or job.wage.min or job.wage.max):
        job.wage = parsed_wage

    normalize_job(job)
    after = (
        job.company,
        job.description_snippet,
        job.workplace,
        job.date_posted,
        job.employment_type,
        job.wage.raw,
    )
    return before != after


async def enrich_jobs(
    jobs: list[Job],
    *,
    pacing_ms: int = 700,
    on_progress: Callable[..., None] | None = None,
) -> tuple[list[Job], dict[str, DetailStats]]:
    """Enrich source groups sequentially while running different hosts in parallel."""
    emit = on_progress or (lambda **_: None)
    groups: dict[str, list[Job]] = {}
    for job in jobs:
        if job.source in SKIP_DETAIL_SOURCES:
            continue
        groups.setdefault(job.source, []).append(job)

    stats = {source: DetailStats() for source in groups}

    async def enrich_source(source: str, source_jobs: list[Job]) -> None:
        source_stats = stats[source]
        async with make_client() as client:
            for job in source_jobs:
                source_stats.attempted += 1
                try:
                    response = await client.get(job.url)
                    if response.status_code in (403, 429):
                        source_stats.errors += 1
                        job.detail_status = f"http_{response.status_code}"
                    else:
                        response.raise_for_status()
                        posting = extract_job_posting(response.text)
                        if not posting:
                            source_stats.unavailable += 1
                            job.detail_status = "structured_data_unavailable"
                        elif apply_job_posting(job, posting):
                            source_stats.enriched += 1
                            job.detail_status = "enriched"
                        else:
                            job.detail_status = "no_new_fields"
                except Exception as exc:
                    source_stats.errors += 1
                    job.detail_status = "fetch_error"
                    emit(
                        event="source.detail_error",
                        source=source,
                        source_id=job.source_id,
                        error=str(exc),
                    )
                await asyncio.sleep(max(0, pacing_ms) / 1000)
        emit(
            event="source.detail_done",
            source=source,
            attempted=source_stats.attempted,
            enriched=source_stats.enriched,
            unavailable=source_stats.unavailable,
            errors=source_stats.errors,
        )

    await asyncio.gather(
        *(enrich_source(source, source_jobs) for source, source_jobs in groups.items())
    )
    return jobs, stats
