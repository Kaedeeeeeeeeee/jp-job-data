"""Global post-fetch filters with consistent semantics across sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from jpjobs.normalize import canonical_text, parse_date
from jpjobs.schema import Job


@dataclass(frozen=True)
class FilterDecision:
    keep: bool
    reason: str | None = None


def _matches_keywords(job: Job, keywords: list[str]) -> bool:
    haystack = canonical_text(
        " ".join(
            (
                job.title,
                job.company,
                job.description_snippet,
                job.workplace,
            )
        )
    )
    return any(canonical_text(keyword) in haystack for keyword in keywords)


def evaluate_job(
    job: Job,
    *,
    keywords: list[str] | None,
    prefecture: str | None,
    days: int | None,
    as_of: date,
    employment_types: list[str] | None,
    language: str | None,
    include_unknown_dates: bool,
) -> FilterDecision:
    if keywords and not _matches_keywords(job, keywords):
        return FilterDecision(False, "keyword_mismatch")

    if prefecture and job.prefecture != prefecture:
        return FilterDecision(
            False,
            "unknown_prefecture" if not job.prefecture else "prefecture_mismatch",
        )

    if employment_types and job.employment_type not in employment_types:
        return FilterDecision(
            False,
            "unknown_employment_type"
            if not job.employment_type
            else "employment_type_mismatch",
        )

    if language:
        accepted_languages = {language}
        if language == "english":
            accepted_languages.add("bilingual")
        if not accepted_languages.intersection(job.language):
            return FilterDecision(False, "language_mismatch")

    if days is not None:
        posted = parse_date(job.date_posted)
        if not posted:
            if not include_unknown_dates:
                return FilterDecision(False, "unknown_date")
        else:
            cutoff = as_of - timedelta(days=days)
            if posted < cutoff:
                return FilterDecision(False, "before_date_window")
            if posted > as_of:
                return FilterDecision(False, "after_date_window")

    return FilterDecision(True)
