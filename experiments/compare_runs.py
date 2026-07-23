#!/usr/bin/env python3
"""Compare two analyze_run.py metric files."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def percentage_points(before: float, after: float) -> float:
    return round((after - before) * 100, 2)


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_completeness = before["overall"]["completeness"]
    after_completeness = after["overall"]["completeness"]
    completeness = {}
    for field in before_completeness:
        before_value = before_completeness[field]
        after_value = after_completeness[field]
        completeness[field] = {
            "before_present": before_value["present"],
            "before_rate": before_value["rate"],
            "after_present": after_value["present"],
            "after_rate": after_value["rate"],
            "delta_percentage_points": percentage_points(
                before_value["rate"], after_value["rate"]
            ),
        }

    before_dates = before["overall"]["dates"]
    after_dates = after["overall"]["dates"]
    before_rows = before["rows"]
    after_rows = after["rows"]
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": after["window"],
        "rows": {
            "before": before_rows,
            "after": after_rows,
            "delta": after_rows - before_rows,
        },
        "verified_in_window": {
            "before": before_dates["in_window"],
            "before_rate": round(before_dates["in_window"] / before_rows, 4)
            if before_rows
            else 0.0,
            "after": after_dates["in_window"],
            "after_rate": round(after_dates["in_window"] / after_rows, 4)
            if after_rows
            else 0.0,
        },
        "unknown_dates": {
            "before": before_dates["unknown"],
            "after": after_dates["unknown"],
        },
        "out_of_window": {
            "before": before_dates["before_window"] + before_dates["after_window"],
            "after": after_dates["before_window"] + after_dates["after_window"],
        },
        "completeness": completeness,
        "duplicates": {
            "before_cross_source_exact_groups": before["overall"]["duplicates"][
                "cross_source_exact_groups"
            ],
            "after_cross_source_exact_groups": after["overall"]["duplicates"][
                "cross_source_exact_groups"
            ],
            "merged_by_optimized_pipeline": after["pipeline"]["duplicates_merged"],
        },
        "implicit_keyword_jobs": {
            "before": before["overall"]["jobs_with_implicit_keywords"],
            "after": after["overall"]["jobs_with_implicit_keywords"],
        },
        "optimized_pipeline": after["pipeline"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    result = compare(before, after)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
