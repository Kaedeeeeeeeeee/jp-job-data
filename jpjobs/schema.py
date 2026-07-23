"""Unified Job schema. Every source normalizes into this."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from hashlib import sha1
from typing import Optional, List, Literal


EmploymentType = Literal[
    "fulltime", "parttime", "contract", "dispatch", "freelance", "intern"
]
WageUnit = Literal["monthly", "hourly", "annual"]


@dataclass
class Wage:
    min: Optional[int] = None  # JPY
    max: Optional[int] = None
    unit: Optional[WageUnit] = None
    raw: str = ""


@dataclass
class Job:
    # Identity
    id: str  # stable cross-source hash
    source: str  # 'hellowork' | 'linkedin' | ...
    source_id: str  # native ID from the source
    url: str
    found_on: List[str] = field(
        default_factory=list
    )  # sources that surfaced this job (post-dedup)

    # Content
    title: str = ""
    company: str = ""
    description: str = ""
    description_snippet: str = ""  # <=400 chars, LLM-safe

    # Location
    workplace: str = ""
    prefecture: Optional[str] = None  # 'tokyo', 'osaka', ...
    prefecture_name: Optional[str] = None  # 'Tokyo' / '東京'
    city: Optional[str] = None
    remote: Optional[bool] = None

    # Compensation
    wage: Wage = field(default_factory=Wage)

    # Employment
    employment_type: Optional[EmploymentType] = None
    date_posted: Optional[str] = None  # ISO8601
    language: List[str] = field(
        default_factory=list
    )  # ['english', 'japanese', 'bilingual']

    # Provenance
    matched_keyword: Optional[str] = None
    scraped_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class SourceStats:
    name: str
    kept: int = 0
    total: int = 0
    error: Optional[str] = None


@dataclass
class ScanResult:
    scanned_at: str
    total_kept: int
    jobs: List[Job]
    per_source: List[SourceStats] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def make_job_id(source: str, source_id: str) -> str:
    """Stable hash for cross-source dedup."""
    return sha1(f"{source}:{source_id}".encode()).hexdigest()[:16]


def now_iso() -> str:
    """ISO8601 UTC timestamp with 'Z' suffix, second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
