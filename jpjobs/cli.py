"""jpjobs CLI — zero deps, just stdlib argparse."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from jpjobs.aggregate import scan, list_sources
from jpjobs.location import slug_to_code
from jpjobs.output import format_result, FORMATTERS


def _make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jpjobs",
        description="Unified scraper for Japan's major job boards.",
    )
    p.add_argument(
        "--sources",
        default="all",
        help="Comma-separated source slugs or 'all'. See --list-sources.",
    )
    p.add_argument(
        "--keyword",
        action="append",
        dest="keywords",
        help="Keyword filter; can repeat (--keyword=X --keyword=Y).",
    )
    p.add_argument("--prefecture", help="Prefecture slug (e.g., 'tokyo', 'osaka').")
    p.add_argument("--location", default="Japan", help="Free-text location (LinkedIn).")
    p.add_argument("--pages", type=int, default=2)
    p.add_argument("--days", type=int, default=7, help="Posted within last N days.")
    p.add_argument(
        "--employment-type",
        action="append",
        dest="employment_types",
        choices=["fulltime", "parttime", "contract", "dispatch", "freelance", "intern"],
    )
    p.add_argument(
        "--language", choices=["english", "japanese", "bilingual"], default=None
    )
    p.add_argument(
        "--english-filter",
        action="store_true",
        help="Post-filter results to English-signal jobs.",
    )
    p.add_argument("--format", default="json", choices=list(FORMATTERS))
    p.add_argument("--output", help="Write to file instead of stdout.")
    p.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser in visible mode (debugging).",
    )
    p.add_argument(
        "--rate-limit", type=int, default=700, help="Inter-request pacing in ms."
    )
    p.add_argument(
        "--list-sources", action="store_true", help="List available sources and exit."
    )
    p.add_argument(
        "--quiet", action="store_true", help="Suppress progress events on stderr."
    )
    return p


def _emit_progress(quiet: bool):
    def cb(**event):
        if quiet:
            return
        ev = event.pop("event", "?")
        bits = " ".join(f"{k}={v}" for k, v in event.items() if v is not None)
        print(f"[jpjobs] {ev}  {bits}", file=sys.stderr)

    return cb


async def _run(args) -> int:
    if args.list_sources:
        for s in list_sources():
            flags = ",".join(k for k, v in s["supports"].items() if v)
            print(
                f"  {s['name']:12} [{s['status']}]  browser={s['requires_browser']}  supports={flags}"
            )
            print(f"    {s['description']}")
        return 0

    sources = (
        args.sources
        if args.sources == "all"
        else [s.strip() for s in args.sources.split(",")]
    )
    pref_code = slug_to_code(args.prefecture) if args.prefecture else None
    if args.prefecture and not pref_code:
        print(
            f"[jpjobs] Unknown prefecture '{args.prefecture}'. Use --list-sources for help.",
            file=sys.stderr,
        )
        return 2

    result = await scan(
        sources=sources,
        keywords=args.keywords,
        location=args.location,
        prefecture=args.prefecture,
        prefecture_code=pref_code,
        pages=args.pages,
        days=args.days,
        employment_types=args.employment_types,
        language=args.language,
        english_filter=args.english_filter or (args.language == "english"),
        headless=not args.no_headless,
        rate_limit_ms=args.rate_limit,
        on_progress=_emit_progress(args.quiet),
    )

    out = format_result(result, args.format)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(
            f"[jpjobs] wrote {result.total_kept} jobs to {args.output}", file=sys.stderr
        )
    else:
        sys.stdout.write(out)
        if not out.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def main() -> None:
    parser = _make_parser()
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(_run(args)))
    except KeyboardInterrupt:
        print("\n[jpjobs] interrupted", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
