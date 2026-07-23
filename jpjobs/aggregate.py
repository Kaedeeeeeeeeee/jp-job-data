"""Top-level scan orchestrator. Loads source modules, runs them in parallel, dedupes."""

from __future__ import annotations

import asyncio
import importlib
import sys
from typing import Callable, Optional, Any

from jpjobs.schema import Job, ScanResult, SourceStats, now_iso
from jpjobs.util.browser import get_browser, close_browser


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
    """Register a 3rd-party source module."""
    _EXTRA_SOURCES[module.name] = module


def _all_sources() -> dict[str, Any]:
    out = {}
    for sn in _BUILTIN_SOURCES:
        try:
            out[sn] = importlib.import_module(f"jpjobs.sources.{sn}")
        except Exception as e:
            print(f"[jpjobs] failed to load source {sn}: {e}", file=sys.stderr)
    out.update(_EXTRA_SOURCES)
    return out


def list_sources() -> list[dict]:
    return [
        {
            "name": getattr(m, "name", k),
            "description": getattr(m, "description", ""),
            "status": getattr(m, "status", "active"),
            "requires_browser": getattr(m, "requires_browser", False),
            "supports": getattr(m, "supports", {}),
        }
        for k, m in _all_sources().items()
    ]


class Ctx:
    """Runtime context passed to source.scan()."""

    def __init__(self, on_progress: Optional[Callable] = None, headless: bool = True):
        self._on_progress = on_progress or (lambda **_: None)
        self._headless = headless

    async def get_browser(self):
        return await get_browser(headless=self._headless)

    def emit(self, event: str, **data) -> None:
        self._on_progress(event=event, **data)


async def _run_source(
    module, opts: dict, ctx: Ctx
) -> tuple[str, list[Job], Optional[str]]:
    try:
        ctx.emit("source.start", source=module.name)
        jobs = await module.scan(opts, ctx)
        ctx.emit("source.done", source=module.name, count=len(jobs))
        return module.name, jobs, None
    except Exception as e:
        ctx.emit("source.error", source=module.name, error=str(e))
        return module.name, [], str(e)


async def scan(
    *,
    sources: list[str] | str = "all",
    keywords: list[str] | None = None,
    location: str | None = None,
    prefecture: str | None = None,
    prefecture_code: str | None = None,
    pages: int = 2,
    days: int = 7,
    employment_types: list[str] | None = None,
    language: str | None = None,
    english_filter: bool = False,
    concurrency: int = 2,
    headless: bool = True,
    on_progress: Optional[Callable] = None,
    rate_limit_ms: int = 700,
    dedup: bool = True,
) -> ScanResult:
    """Run a scan across one or more sources."""
    all_src = _all_sources()
    if sources == "all":
        selected = all_src
    else:
        if isinstance(sources, str):
            sources = [sources]
        selected = {k: m for k, m in all_src.items() if k in sources}
    if not selected:
        return ScanResult(
            scanned_at=now_iso(),
            total_kept=0,
            jobs=[],
            warnings=[f"No sources matched: {sources}"],
        )

    opts = {
        "keywords": keywords,
        "location": location,
        "prefecture": prefecture,
        "prefecture_code": prefecture_code,
        "pages": pages,
        "days": days,
        "employment_types": employment_types,
        "language": language,
        "english_filter": english_filter,
        "rate_limit_ms": rate_limit_ms,
    }
    ctx = Ctx(on_progress=on_progress, headless=headless)
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(m):
        async with sem:
            return await _run_source(m, opts, ctx)

    results = await asyncio.gather(*(_bounded(m) for m in selected.values()))

    # Cleanup browser if any source used it
    await close_browser()

    # Aggregate + dedup
    by_id: dict[str, Job] = {}
    per_source: list[SourceStats] = []
    warnings: list[str] = []
    for src_name, jobs, err in results:
        kept = 0
        for j in jobs:
            if dedup and j.id in by_id:
                if src_name not in by_id[j.id].found_on:
                    by_id[j.id].found_on.append(src_name)
                continue
            if src_name not in j.found_on:
                j.found_on.append(src_name)
            by_id[j.id] = j
            kept += 1
        per_source.append(
            SourceStats(name=src_name, kept=kept, total=len(jobs), error=err)
        )
        if err:
            warnings.append(f"{src_name}: {err}")

    final = list(by_id.values())
    return ScanResult(
        scanned_at=now_iso(),
        total_kept=len(final),
        jobs=final,
        per_source=per_source,
        warnings=warnings,
    )
