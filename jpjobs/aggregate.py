"""Top-level scan orchestration, normalization, filtering, and deduplication."""

from __future__ import annotations

import asyncio
import importlib
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from jpjobs.checkpoint import PageCheckpoint
from jpjobs.enrich import DetailStats, enrich_jobs
from jpjobs.filtering import evaluate_job
from jpjobs.normalize import job_fingerprint, normalize_job, parse_date
from jpjobs.schema import (
    Job,
    ScanResult,
    SourceStats,
    SourceStatus,
    make_canonical_job_id,
    now_iso,
)
from jpjobs.util.browser import close_browser, get_browser


_BUILTIN_SOURCES = [
    "hellowork",
    "linkedin",
    "tokyodev",
    "indeed",
    "japandev",
    "daijob",
    "careercross",
    "gaijinpot",
    "jobsinjapan",
    "green",
    "forkwell",
    "jrecin",
    "otta",
    "wellfound",
    "wantedly",
    "doda",
    "enworld",
]
_EXTRA_SOURCES: dict[str, Any] = {}


def register_source(module) -> None:
    """Register a third-party source module."""
    _EXTRA_SOURCES[module.name] = module


def _all_sources() -> dict[str, Any]:
    out = {}
    for source_name in _BUILTIN_SOURCES:
        try:
            out[source_name] = importlib.import_module(f"jpjobs.sources.{source_name}")
        except Exception as exc:
            print(
                f"[jpjobs] failed to load source {source_name}: {exc}",
                file=sys.stderr,
            )
    out.update(_EXTRA_SOURCES)
    return out


def list_sources() -> list[dict]:
    return [
        {
            "name": getattr(module, "name", key),
            "description": getattr(module, "description", ""),
            "status": getattr(module, "status", "active"),
            "requires_browser": getattr(module, "requires_browser", False),
            "supports": getattr(module, "supports", {}),
        }
        for key, module in _all_sources().items()
    ]


class Ctx:
    """Runtime context passed to source.scan()."""

    def __init__(self, on_progress: Optional[Callable] = None, headless: bool = True):
        self._on_progress = on_progress or (lambda **_: None)
        self._headless = headless
        self.events: list[dict[str, Any]] = []

    async def get_browser(self):
        return await get_browser(headless=self._headless)

    def emit(self, event: str, **data) -> None:
        payload = {"event": event, **data}
        self.events.append(payload)
        self._on_progress(**payload)

    def source_errors(self, source: str, start: int = 0) -> list[str]:
        return [
            str(event.get("error"))
            for event in self.events[start:]
            if event.get("source") == source
            and event.get("error")
            and str(event.get("event", "")).endswith("error")
        ]


@dataclass
class SourceOutcome:
    name: str
    jobs: list[Job]
    status: SourceStatus
    error: str | None = None
    pages_fetched: int = 0
    pagination_stop_reasons: list[str] | None = None
    coverage_complete: bool | None = None


def _status_for_error(error: str) -> SourceStatus:
    lowered = error.casefold()
    if any(
        signal in lowered
        for signal in ("403", "429", "blocked", "datadome", "cloudflare", "captcha")
    ):
        return "blocked"
    if any(signal in lowered for signal in ("parse", "selector", "missing")):
        return "parse_error"
    return "error"


async def _run_source(module, opts: dict, ctx: Ctx) -> SourceOutcome:
    event_start = len(ctx.events)
    try:
        ctx.emit("source.start", source=module.name)
        jobs = await module.scan(opts, ctx)
        source_events = [
            event
            for event in ctx.events[event_start:]
            if event.get("source") == module.name
        ]
        pages_fetched = sum(
            event.get("event") == "source.page" for event in source_events
        )
        pagination_events = [
            event
            for event in source_events
            if event.get("event") == "source.pagination_stop"
        ]
        pagination_stop_reasons = list(
            dict.fromkeys(
                str(event.get("reason"))
                for event in pagination_events
                if event.get("reason")
            )
        )
        coverage_complete = (
            all(event.get("coverage_complete") is True for event in pagination_events)
            if pagination_events
            else None
        )
        errors = ctx.source_errors(module.name, event_start)
        if errors:
            status: SourceStatus = "partial" if jobs else _status_for_error(errors[-1])
            error = "; ".join(dict.fromkeys(errors))
        elif jobs:
            status = "success"
            error = None
        else:
            status = "no_results"
            error = None
        ctx.emit(
            "source.done",
            source=module.name,
            count=len(jobs),
            status=status,
        )
        return SourceOutcome(
            module.name,
            jobs,
            status,
            error,
            pages_fetched=pages_fetched,
            pagination_stop_reasons=pagination_stop_reasons,
            coverage_complete=coverage_complete,
        )
    except Exception as exc:
        error = str(exc)
        status = _status_for_error(error)
        ctx.emit("source.error", source=module.name, error=error)
        return SourceOutcome(
            module.name,
            [],
            status,
            error,
            pagination_stop_reasons=[],
        )


def _compatible_location(left: Job, right: Job) -> bool:
    if left.prefecture and right.prefecture:
        return left.prefecture == right.prefecture
    return True


def _merge_job(primary: Job, incoming: Job, fingerprint: str) -> None:
    primary.id = make_canonical_job_id(fingerprint)
    primary.found_on = list(
        dict.fromkeys(
            [
                *primary.found_on,
                primary.source,
                *incoming.found_on,
                incoming.source,
            ]
        )
    )
    primary.source_urls.update(incoming.source_urls or {incoming.source: incoming.url})
    primary.source_ids.update(
        incoming.source_ids or {incoming.source: incoming.source_id}
    )

    for field_name in (
        "company",
        "workplace",
        "prefecture",
        "prefecture_name",
        "city",
        "employment_type",
        "matched_keyword",
    ):
        if not getattr(primary, field_name) and getattr(incoming, field_name):
            setattr(primary, field_name, getattr(incoming, field_name))

    if len(incoming.description) > len(primary.description):
        primary.description = incoming.description
    if len(incoming.description_snippet) > len(primary.description_snippet):
        primary.description_snippet = incoming.description_snippet
    if not (primary.wage.raw or primary.wage.min or primary.wage.max) and (
        incoming.wage.raw or incoming.wage.min or incoming.wage.max
    ):
        primary.wage = incoming.wage
    if incoming.date_posted and (
        not primary.date_posted or incoming.date_posted > primary.date_posted
    ):
        primary.date_posted = incoming.date_posted
    if incoming.remote is True:
        primary.remote = True
    primary.language = list(dict.fromkeys([*primary.language, *incoming.language]))
    primary.quality_flags = list(
        dict.fromkeys([*primary.quality_flags, *incoming.quality_flags])
    )
    normalize_job(primary)


def _deduplicate(jobs: list[Job]) -> tuple[list[Job], int]:
    """Deduplicate source IDs first, then exact normalized cross-source matches."""
    native_seen: set[tuple[str, str]] = set()
    fingerprint_candidates: dict[str, list[Job]] = {}
    final: list[Job] = []
    merged = 0

    for job in jobs:
        native_key = (job.source, job.source_id)
        if native_key in native_seen:
            merged += 1
            continue
        native_seen.add(native_key)

        fingerprint = job_fingerprint(job)
        match = None
        if fingerprint:
            for candidate in fingerprint_candidates.get(fingerprint, []):
                if (
                    job.source not in candidate.found_on
                    and candidate.source != job.source
                    and _compatible_location(candidate, job)
                ):
                    match = candidate
                    break

        if match and fingerprint:
            _merge_job(match, job, fingerprint)
            merged += 1
            continue

        if job.source not in job.found_on:
            job.found_on.append(job.source)
        final.append(job)
        if fingerprint:
            fingerprint_candidates.setdefault(fingerprint, []).append(job)

    return final, merged


def _sort_jobs(jobs: list[Job]) -> list[Job]:
    def key(job: Job):
        posted = parse_date(job.date_posted)
        return (
            posted is None,
            -(posted.toordinal() if posted else 0),
            job.source,
            job.title.casefold(),
        )

    return sorted(jobs, key=key)


async def scan(
    *,
    sources: list[str] | str = "all",
    keywords: list[str] | None = None,
    location: str | None = None,
    prefecture: str | None = None,
    prefecture_code: str | None = None,
    pages: int | None = 2,
    max_pages: int = 50,
    source_max_pages: dict[str, int] | None = None,
    start_pages: dict[str, int] | None = None,
    checkpoint_path: str | Path | None = None,
    days: int | None = 7,
    employment_types: list[str] | None = None,
    language: str | None = None,
    english_filter: bool = False,
    concurrency: int = 2,
    headless: bool = True,
    on_progress: Optional[Callable] = None,
    rate_limit_ms: int = 700,
    dedup: bool = True,
    include_unknown_dates: bool = False,
    fetch_details: bool = False,
    skip_detail_keys: set[tuple[str, str]] | None = None,
    known_job_dates: dict[tuple[str, str], str] | None = None,
    as_of: date | str | None = None,
) -> ScanResult:
    """Run a scan with consistent normalization and post-fetch filtering."""
    all_sources = _all_sources()
    if sources == "all":
        selected = {
            key: module
            for key, module in all_sources.items()
            if getattr(module, "status", "active") == "active"
        }
    elif sources == "all-including-experimental":
        selected = all_sources
    else:
        if isinstance(sources, str):
            sources = [sources]
        selected = {
            key: module for key, module in all_sources.items() if key in sources
        }

    scanned_at = now_iso()
    if not selected:
        return ScanResult(
            scanned_at=scanned_at,
            total_kept=0,
            jobs=[],
            warnings=[f"No sources matched: {sources}"],
        )

    if isinstance(as_of, str):
        as_of_date = date.fromisoformat(as_of)
    else:
        as_of_date = as_of or date.today()

    opts = {
        "keywords": keywords,
        "location": location,
        "prefecture": prefecture,
        "prefecture_code": prefecture_code,
        "pages": pages if pages is not None else 2,
        "auto_pages": pages is None,
        "max_pages": max_pages,
        "source_max_pages": source_max_pages or {},
        "start_pages": start_pages or {},
        "days": days,
        "as_of": as_of_date.isoformat(),
        "cutoff_date": (
            (as_of_date - timedelta(days=days)).isoformat()
            if days is not None
            else None
        ),
        "employment_types": employment_types,
        "language": language,
        "english_filter": english_filter,
        "rate_limit_ms": rate_limit_ms,
    }
    if checkpoint_path:
        checkpoint_parameters = {
            "keywords": keywords or [],
            "location": location,
            "prefecture": prefecture,
            "prefecture_code": prefecture_code,
            "auto_pages": pages is None,
            "days": days,
            "as_of": as_of_date.isoformat(),
            "employment_types": employment_types or [],
            "language": language,
            "english_filter": english_filter,
            "include_unknown_dates": include_unknown_dates,
            "fetch_details": fetch_details,
        }
        opts["_checkpoint"] = PageCheckpoint(
            checkpoint_path,
            parameters=checkpoint_parameters,
        )
    ctx = Ctx(on_progress=on_progress, headless=headless)
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded(module):
        async with semaphore:
            return await _run_source(module, opts, ctx)

    try:
        outcomes = await asyncio.gather(
            *(bounded(module) for module in selected.values())
        )
    finally:
        await close_browser()

    raw_jobs = [job for outcome in outcomes for job in outcome.jobs]
    for job in raw_jobs:
        normalize_job(job)
        if not job.date_posted and known_job_dates:
            job.date_posted = known_job_dates.get((job.source, job.source_id))

    detail_stats: dict[str, DetailStats] = {}
    detail_attempts: list[dict[str, str]] = []
    if fetch_details:
        detail_jobs = raw_jobs
        if skip_detail_keys:
            detail_jobs = [
                job
                for job in raw_jobs
                if (job.source, job.source_id) not in skip_detail_keys
            ]
        if days is not None:
            detail_cutoff = as_of_date - timedelta(days=days)
            detail_jobs = [
                job
                for job in detail_jobs
                if (posted := parse_date(job.date_posted)) is None
                or detail_cutoff <= posted <= as_of_date
            ]
        _, detail_stats = await enrich_jobs(
            detail_jobs,
            pacing_ms=rate_limit_ms,
            on_progress=ctx.emit,
        )
        detail_attempts = [
            {
                "source": job.source,
                "source_id": job.source_id,
                "status": job.detail_status,
            }
            for job in detail_jobs
            if job.detail_status
        ]

    requested_language = language or ("english" if english_filter else None)
    kept: list[Job] = []
    filter_reasons: Counter[str] = Counter()
    filtered_by_source: Counter[str] = Counter()
    for job in raw_jobs:
        normalize_job(job)
        decision = evaluate_job(
            job,
            keywords=keywords,
            prefecture=prefecture,
            days=days,
            as_of=as_of_date,
            employment_types=employment_types,
            language=requested_language,
            include_unknown_dates=include_unknown_dates,
        )
        if decision.keep:
            kept.append(job)
        else:
            reason = decision.reason or "unspecified"
            filter_reasons[reason] += 1
            filtered_by_source[job.source] += 1

    duplicates_merged = 0
    if dedup:
        kept, duplicates_merged = _deduplicate(kept)
    else:
        for job in kept:
            if job.source not in job.found_on:
                job.found_on.append(job.source)

    kept = _sort_jobs(kept)
    warnings: list[str] = []
    for outcome in outcomes:
        if outcome.error:
            warnings.append(f"{outcome.name}: {outcome.error}")
        if outcome.coverage_complete is False and pages is None:
            reasons = ", ".join(outcome.pagination_stop_reasons or ["unknown"])
            warnings.append(
                f"{outcome.name}: automatic pagination stopped at {reasons}; "
                "recent-window coverage may be incomplete"
            )

    if filter_reasons.get("unknown_date"):
        warnings.append(
            f"{filter_reasons['unknown_date']} jobs excluded because date_posted "
            "was unavailable; use include_unknown_dates=True to retain them"
        )

    final_source_counts: Counter[str] = Counter()
    for job in kept:
        for source in job.found_on or [job.source]:
            final_source_counts[source] += 1

    per_source: list[SourceStats] = []
    for outcome in outcomes:
        details = detail_stats.get(outcome.name, DetailStats())
        status = outcome.status
        error = outcome.error
        if details.errors and outcome.jobs:
            status = "partial"
            detail_error = f"{details.errors} detail-page fetch errors"
            error = f"{error}; {detail_error}" if error else detail_error
            warnings.append(f"{outcome.name}: {detail_error}")
        per_source.append(
            SourceStats(
                name=outcome.name,
                status=status,
                discovery_status=outcome.status,
                kept=final_source_counts[outcome.name],
                total=len(outcome.jobs),
                raw_total=len(outcome.jobs),
                filtered=filtered_by_source[outcome.name],
                enriched=details.enriched,
                error=error,
                pages_fetched=outcome.pages_fetched,
                pagination_stop_reasons=outcome.pagination_stop_reasons or [],
                coverage_complete=outcome.coverage_complete,
            )
        )

    return ScanResult(
        scanned_at=scanned_at,
        total_kept=len(kept),
        jobs=kept,
        window_start=opts["cutoff_date"],
        window_end=as_of_date.isoformat(),
        raw_total=len(raw_jobs),
        filtered_out=sum(filter_reasons.values()),
        duplicates_merged=duplicates_merged,
        filter_reasons=dict(filter_reasons),
        per_source=per_source,
        warnings=list(dict.fromkeys(warnings)),
        detail_attempts=detail_attempts,
    )
