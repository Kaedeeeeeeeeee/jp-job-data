"""Output formatters: json / csv / markdown / table / llm."""

from __future__ import annotations

import csv
import io
import json
from collections import deque
from dataclasses import asdict

from jpjobs.schema import ScanResult


def format_json(result: ScanResult, indent: int = 2) -> str:
    return json.dumps(asdict(result), indent=indent, ensure_ascii=False, default=str)


def format_csv(result: ScanResult) -> str:
    buf = io.StringIO()
    fields = [
        "id",
        "source",
        "source_id",
        "url",
        "found_on",
        "source_urls",
        "title",
        "company",
        "description_snippet",
        "workplace",
        "prefecture",
        "prefecture_name",
        "remote",
        "wage_min",
        "wage_max",
        "wage_unit",
        "wage_raw",
        "employment_type",
        "date_posted",
        "language",
        "detail_status",
        "quality_flags",
        "matched_keyword",
        "scraped_at",
    ]
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for j in result.jobs:
        w.writerow(
            {
                "id": j.id,
                "source": j.source,
                "source_id": j.source_id,
                "url": j.url,
                "found_on": json.dumps(j.found_on, ensure_ascii=False),
                "source_urls": json.dumps(j.source_urls, ensure_ascii=False),
                "title": j.title,
                "company": j.company,
                "description_snippet": j.description_snippet,
                "workplace": j.workplace,
                "prefecture": j.prefecture,
                "prefecture_name": j.prefecture_name,
                "remote": j.remote,
                "wage_min": j.wage.min,
                "wage_max": j.wage.max,
                "wage_unit": j.wage.unit,
                "wage_raw": j.wage.raw,
                "employment_type": j.employment_type,
                "date_posted": j.date_posted,
                "language": json.dumps(j.language, ensure_ascii=False),
                "detail_status": j.detail_status,
                "quality_flags": json.dumps(j.quality_flags, ensure_ascii=False),
                "matched_keyword": j.matched_keyword,
                "scraped_at": j.scraped_at,
            }
        )
    return buf.getvalue()


def format_markdown(result: ScanResult) -> str:
    lines = [
        f"# Scan results — {result.scanned_at}",
        (
            f"**Total:** {result.total_kept} jobs across {len(result.per_source)} "
            f"sources · raw {result.raw_total} · filtered {result.filtered_out} · "
            f"duplicates merged {result.duplicates_merged}"
        ),
        "",
        "| # | Source | Title | Company | Location | Wage | URL |",
        "|---|--------|-------|---------|----------|------|-----|",
    ]

    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")

    for i, j in enumerate(result.jobs, 1):
        wage = j.wage.raw or "—"
        lines.append(
            f"| {i} | {cell(', '.join(j.found_on) or j.source)} | "
            f"{cell(j.title[:50])} | {cell(j.company[:30])} | "
            f"{cell((j.prefecture_name or j.workplace)[:30])} | "
            f"{cell(wage)} | {j.url} |"
        )
    return "\n".join(lines)


def format_table(result: ScanResult) -> str:
    """Terminal-pretty plain text table."""
    out = [f"\n{result.total_kept} jobs · {result.scanned_at}\n"]
    for j in result.jobs:
        out.append(f"  {j.title[:60]:60} | {j.company[:25]:25} | {j.source}")
        out.append(
            f"    📍 {(j.prefecture_name or j.workplace)[:50]}    💴 {j.wage.raw or '—':25}"
        )
        out.append(f"    🔗 {j.url[:120]}")
        out.append("")
    return "\n".join(out)


def _balanced_sample(result: ScanResult, max_jobs: int) -> list:
    """Round-robin sources so one large board cannot consume the full export."""
    buckets: dict[str, deque] = {}
    for job in result.jobs:
        buckets.setdefault(job.source, deque()).append(job)
    selected = []
    while buckets and len(selected) < max_jobs:
        for source in list(buckets):
            bucket = buckets[source]
            if bucket and len(selected) < max_jobs:
                selected.append(bucket.popleft())
            if not bucket:
                del buckets[source]
    return selected


def format_llm(result: ScanResult, max_jobs: int = 50) -> str:
    """Compact, source-balanced text block for downstream ranking."""
    jobs = _balanced_sample(result, max_jobs)
    out = [
        f"# Japan job listings — {len(jobs)} of {result.total_kept} jobs",
        f"# Scanned at: {result.scanned_at}",
        f"# Sources: {', '.join(s.name for s in result.per_source)}",
        "",
    ]
    for i, j in enumerate(jobs, 1):
        out.append(f"[{i}] {j.title}")
        out.append(
            f"    Company: {j.company}  ·  Location: {j.prefecture_name or j.workplace or 'unknown'}"
        )
        wage_str = j.wage.raw or "wage TBD"
        out.append(
            f"    Wage: {wage_str}  ·  Posted: {j.date_posted or '?'}  ·  "
            f"Sources: {', '.join(j.found_on) or j.source}"
        )
        if j.language:
            out.append(f"    Language signals: {', '.join(j.language)}")
        if j.description_snippet:
            out.append(f"    Summary: {j.description_snippet[:400]}")
        out.append(f"    URL: {j.url}")
        out.append("")
    if result.total_kept > max_jobs:
        out.append(
            f"# ({result.total_kept - max_jobs} more jobs not shown; use --format=json to see all)"
        )
    return "\n".join(out)


FORMATTERS = {
    "json": format_json,
    "csv": format_csv,
    "markdown": format_markdown,
    "table": format_table,
    "llm": format_llm,
}


def format_result(result: ScanResult, fmt: str = "json") -> str:
    fn = FORMATTERS.get(fmt)
    if not fn:
        raise ValueError(f"Unknown format '{fmt}'. Choose from: {list(FORMATTERS)}")
    return fn(result)
