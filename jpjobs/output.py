"""Output formatters: json / csv / markdown / table / llm."""

from __future__ import annotations

import csv
import io
import json
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
        "title",
        "company",
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
                "title": j.title,
                "company": j.company,
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
                "matched_keyword": j.matched_keyword,
                "scraped_at": j.scraped_at,
            }
        )
    return buf.getvalue()


def format_markdown(result: ScanResult) -> str:
    lines = [
        f"# Scan results — {result.scanned_at}",
        f"**Total:** {result.total_kept} jobs across {len(result.per_source)} sources",
        "",
        "| # | Source | Title | Company | Location | Wage | URL |",
        "|---|--------|-------|---------|----------|------|-----|",
    ]
    for i, j in enumerate(result.jobs, 1):
        wage = j.wage.raw or "—"
        lines.append(
            f"| {i} | {j.source} | {j.title[:50]} | {j.company[:30]} | "
            f"{(j.prefecture_name or j.workplace)[:30]} | {wage} | {j.url} |"
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


def format_llm(result: ScanResult, max_jobs: int = 50) -> str:
    """Compact text block, 3-4 lines per job, AI-pasteable. Cap for context budget."""
    jobs = result.jobs[:max_jobs]
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
            f"    Wage: {wage_str}  ·  Posted: {j.date_posted or '?'}  ·  Source: {j.source}"
        )
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
