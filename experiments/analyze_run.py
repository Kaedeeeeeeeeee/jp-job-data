#!/usr/bin/env python3
"""Produce reproducible data-quality metrics for a jpjobs JSON run."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


DATE_FORMATS = (
    "%Y-%m-%d",
    "%B %d, %Y",
    "%b %d, %Y",
)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    candidate = value.strip()
    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(candidate, date_format).date()
        except ValueError:
            continue
    return None


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = re.sub(
        r"株式会社|合同会社|有限会社|inc\.?|ltd\.?|co\.?\s*,?\s*ltd\.?",
        "",
        text,
    )
    return re.sub(r"[^0-9a-zぁ-んァ-ン一-龥]+", "", text)


def has_wage(job: dict[str, Any]) -> bool:
    wage = job.get("wage") or {}
    return bool(wage.get("raw") or wage.get("min") or wage.get("max"))


def completeness(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    fields = (
        "title",
        "company",
        "description_snippet",
        "workplace",
        "prefecture",
        "employment_type",
        "date_posted",
        "language",
    )
    total = len(rows)
    result: dict[str, dict[str, float | int]] = {}
    for field in fields:
        present = sum(bool(row.get(field)) for row in rows)
        result[field] = {
            "present": present,
            "rate": round(present / total, 4) if total else 0.0,
        }
    wage_present = sum(has_wage(row) for row in rows)
    result["wage"] = {
        "present": wage_present,
        "rate": round(wage_present / total, 4) if total else 0.0,
    }
    return result


def date_metrics(rows: list[dict[str, Any]], start: date, end: date) -> dict[str, int]:
    metrics = Counter(
        {
            "known": 0,
            "unknown": 0,
            "invalid": 0,
            "in_window": 0,
            "before_window": 0,
            "after_window": 0,
        }
    )
    for row in rows:
        raw = row.get("date_posted")
        parsed = parse_date(raw)
        if parsed is None:
            metrics["invalid" if raw else "unknown"] += 1
        elif parsed < start:
            metrics["known"] += 1
            metrics["before_window"] += 1
        elif parsed > end:
            metrics["known"] += 1
            metrics["after_window"] += 1
        else:
            metrics["known"] += 1
            metrics["in_window"] += 1
    return dict(metrics)


def duplicate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    native_ids: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    fingerprints: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        native_ids[(row.get("source", ""), row.get("source_id", ""))].append(row)
        fingerprint = (
            normalize_text(row.get("company")),
            normalize_text(row.get("title")),
        )
        if all(fingerprint):
            fingerprints[fingerprint].append(row)

    native_duplicate_groups = [group for group in native_ids.values() if len(group) > 1]
    cross_source_groups = [
        group
        for group in fingerprints.values()
        if len({row.get("source") for row in group}) > 1
    ]
    examples = [
        [
            {
                "source": row.get("source"),
                "company": row.get("company"),
                "title": row.get("title"),
            }
            for row in group
        ]
        for group in cross_source_groups[:10]
    ]
    return {
        "native_duplicate_groups": len(native_duplicate_groups),
        "native_duplicate_rows": sum(len(group) for group in native_duplicate_groups),
        "cross_source_exact_groups": len(cross_source_groups),
        "cross_source_exact_rows": sum(len(group) for group in cross_source_groups),
        "cross_source_examples": examples,
    }


def analyze(payload: dict[str, Any], start: date, end: date) -> dict[str, Any]:
    rows = payload.get("jobs") or []
    by_source: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_source[row.get("source") or "unknown"].append(row)

    source_metrics = {}
    for source, source_rows in sorted(by_source.items()):
        source_metrics[source] = {
            "rows": len(source_rows),
            "completeness": completeness(source_rows),
            "dates": date_metrics(source_rows, start, end),
        }

    matched_keywords = Counter(
        row.get("matched_keyword")
        for row in rows
        if row.get("matched_keyword") is not None
    )

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "reported_total_kept": payload.get("total_kept"),
        "rows": len(rows),
        "source_count": len(by_source),
        "warnings": payload.get("warnings") or [],
        "pipeline": {
            "raw_total": payload.get("raw_total", len(rows)),
            "filtered_out": payload.get("filtered_out", 0),
            "duplicates_merged": payload.get("duplicates_merged", 0),
            "filter_reasons": payload.get("filter_reasons") or {},
        },
        "overall": {
            "completeness": completeness(rows),
            "dates": date_metrics(rows, start, end),
            "duplicates": duplicate_metrics(rows),
            "implicit_matched_keywords": dict(matched_keywords.most_common()),
            "jobs_with_implicit_keywords": sum(matched_keywords.values()),
        },
        "per_source": source_metrics,
        "reported_per_source": payload.get("per_source") or [],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = analyze(payload, args.start, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
