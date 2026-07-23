"""Source template — copy this when adding a new board.

Every source module exposes:
    name: str
    description: str
    requires_browser: bool
    supports: dict[str, bool]
    async def scan(opts: dict, ctx) -> list[Job]
"""

from __future__ import annotations

from typing import Any
from jpjobs.schema import Job


name = "example"
description = "Human-readable one-liner"
status = "active"  # 'active' | 'experimental' | 'unsupported'
requires_browser = False
supports = {
    "prefecture": True,
    "keywords": True,
    "category": False,
    "employment_type": False,
    "language": False,
}
default_rate_limit_ms = 3000


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    """
    Args:
        opts: scan options (keywords, prefecture, pages, etc.)
        ctx:  runtime context — provides .logger, .fetch, .get_browser(), .emit()

    Returns:
        list[Job] — raw, unfiltered. aggregate.py applies cross-source dedup.
    """
    jobs: list[Job] = []
    # ... fetch + parse ...
    # for each raw row:
    #     j = Job(
    #         id=make_job_id(name, source_id),
    #         source=name,
    #         source_id=source_id,
    #         url=...,
    #         title=...,
    #         company=...,
    #         scraped_at=now_iso(),
    #     )
    #     jobs.append(j)
    return jobs
