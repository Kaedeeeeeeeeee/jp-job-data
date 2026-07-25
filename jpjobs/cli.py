"""jpjobs CLI — zero deps, just stdlib argparse."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from jpjobs.aggregate import scan, list_sources
from jpjobs.location import slug_to_code
from jpjobs.output import format_result, FORMATTERS


def _page_mode(value: str) -> int | None:
    if value.casefold() == "auto":
        return None
    try:
        pages = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use a positive integer or 'auto'") from exc
    if pages < 1:
        raise argparse.ArgumentTypeError("page count must be at least 1")
    return pages


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _source_page(value: str) -> tuple[str, int]:
    source, separator, raw_page = value.partition("=")
    source = source.strip()
    if not separator or not source:
        raise argparse.ArgumentTypeError("use SOURCE=PAGE, for example daijob=250")
    return source, _positive_int(raw_page)


def _make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jpjobs",
        description="Unified scraper for Japan's major job boards.",
    )
    p.add_argument(
        "--sources",
        default="all",
        help=(
            "Comma-separated source slugs, 'all' for active sources, or "
            "'all-including-experimental'. See --list-sources."
        ),
    )
    p.add_argument(
        "--keyword",
        action="append",
        dest="keywords",
        help="Keyword filter; can repeat (--keyword=X --keyword=Y).",
    )
    p.add_argument("--prefecture", help="Prefecture slug (e.g., 'tokyo', 'osaka').")
    p.add_argument("--location", default="Japan", help="Free-text location (LinkedIn).")
    p.add_argument(
        "--pages",
        type=_page_mode,
        default=2,
        metavar="N|auto",
        help=(
            "Maximum pages per source, or 'auto' to continue through the date "
            "window (default: 2)."
        ),
    )
    p.add_argument(
        "--max-pages",
        type=_positive_int,
        default=50,
        help="Safety cap per source/query when --pages=auto (default: 50).",
    )
    p.add_argument(
        "--source-max-pages",
        action="append",
        type=_source_page,
        default=[],
        metavar="SOURCE=N",
        help=(
            "Override the automatic safety cap for one source; can repeat "
            "(for example hellowork=250)."
        ),
    )
    p.add_argument(
        "--start-page",
        action="append",
        type=_source_page,
        default=[],
        metavar="SOURCE=N",
        help=(
            "Start or resume one source at this one-based page; can repeat. "
            "Browser sources may replay earlier pages to restore their session."
        ),
    )
    p.add_argument(
        "--checkpoint",
        help=(
            "Persist automatic-pagination progress to JSON and resume it on "
            "the next run with matching filters."
        ),
    )
    p.add_argument("--days", type=int, default=7, help="Posted within last N days.")
    p.add_argument(
        "--as-of",
        help="End date for the posted-date window (YYYY-MM-DD; default: today).",
    )
    p.add_argument(
        "--include-unknown-dates",
        action="store_true",
        help="Retain jobs with no posted date when --days is active.",
    )
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
        "--database",
        help="Upsert the filtered result into a SQLite database.",
    )
    p.add_argument(
        "--maintain-database",
        action="store_true",
        help=(
            "Reconcile missing jobs after complete source scans, expire old jobs, "
            "and purge aged tombstones. Requires --database and --pages=auto."
        ),
    )
    p.add_argument(
        "--missing-threshold",
        type=_positive_int,
        default=3,
        help="Complete scans a listing may miss before withdrawal (default: 3).",
    )
    p.add_argument(
        "--retention-days",
        type=_positive_int,
        default=90,
        help="Expire jobs older than this many posted days (default: 90).",
    )
    p.add_argument(
        "--purge-grace-days",
        type=int,
        default=30,
        help="Keep withdrawn/expired tombstones this many days (default: 30).",
    )
    p.add_argument(
        "--fetch-details-new-only",
        action="store_true",
        help=(
            "With --fetch-details and --database, fetch detail pages only for "
            "previously unseen or reactivated source listings."
        ),
    )
    p.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser in visible mode (debugging).",
    )
    p.add_argument(
        "--rate-limit", type=int, default=700, help="Inter-request pacing in ms."
    )
    p.add_argument(
        "--fetch-details",
        action="store_true",
        help="Fetch detail pages and parse schema.org JobPosting fields.",
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
    if (
        args.source_max_pages or args.start_page or args.checkpoint
    ) and args.pages is not None:
        print(
            "[jpjobs] --source-max-pages, --start-page, and --checkpoint "
            "require --pages=auto.",
            file=sys.stderr,
        )
        return 2
    if args.maintain_database:
        if not args.database:
            print(
                "[jpjobs] --maintain-database requires --database.",
                file=sys.stderr,
            )
            return 2
        if args.pages is not None:
            print(
                "[jpjobs] --maintain-database requires --pages=auto.",
                file=sys.stderr,
            )
            return 2
        if any(
            (
                args.keywords,
                args.prefecture,
                args.employment_types,
                args.language,
                args.english_filter,
            )
        ):
            print(
                "[jpjobs] database maintenance requires an unfiltered source "
                "inventory; remove keyword, location, employment, and language "
                "filters.",
                file=sys.stderr,
            )
            return 2
    if args.purge_grace_days < 0:
        print(
            "[jpjobs] --purge-grace-days cannot be negative.",
            file=sys.stderr,
        )
        return 2
    if args.fetch_details_new_only and (not args.database or not args.fetch_details):
        print(
            "[jpjobs] --fetch-details-new-only requires both --database and "
            "--fetch-details.",
            file=sys.stderr,
        )
        return 2
    source_max_pages = dict(args.source_max_pages)
    start_pages = dict(args.start_page)
    for source, start_page in start_pages.items():
        limit = source_max_pages.get(source, args.max_pages)
        if start_page > limit:
            print(
                f"[jpjobs] start page {start_page} exceeds the {source} "
                f"maximum page {limit}.",
                file=sys.stderr,
            )
            return 2
    pref_code = slug_to_code(args.prefecture) if args.prefecture else None
    if args.prefecture and not pref_code:
        print(
            f"[jpjobs] Unknown prefecture '{args.prefecture}'. Use --list-sources for help.",
            file=sys.stderr,
        )
        return 2

    skip_detail_keys = None
    known_job_dates = None
    if args.database:
        from jpjobs.storage import JobStore

        with JobStore(args.database) as store:
            known_job_dates = store.known_job_dates()
            if args.fetch_details_new_only:
                skip_detail_keys = store.detail_skip_keys(as_of=args.as_of)

    result = await scan(
        sources=sources,
        keywords=args.keywords,
        location=args.location,
        prefecture=args.prefecture,
        prefecture_code=pref_code,
        pages=args.pages,
        max_pages=args.max_pages,
        source_max_pages=source_max_pages,
        start_pages=start_pages,
        checkpoint_path=args.checkpoint,
        days=args.days,
        employment_types=args.employment_types,
        language=args.language,
        english_filter=args.english_filter or (args.language == "english"),
        headless=not args.no_headless,
        rate_limit_ms=args.rate_limit,
        include_unknown_dates=args.include_unknown_dates,
        fetch_details=args.fetch_details,
        skip_detail_keys=skip_detail_keys,
        known_job_dates=known_job_dates,
        as_of=args.as_of,
        on_progress=_emit_progress(args.quiet),
    )

    if args.database:
        from jpjobs.storage import JobStore

        with JobStore(args.database) as store:
            stored = store.save_scan(
                result,
                maintenance=args.maintain_database,
                missing_threshold=args.missing_threshold,
                retention_days=args.retention_days,
                purge_grace_days=args.purge_grace_days,
            )
        if not args.quiet:
            print(
                f"[jpjobs] stored={stored.stored} new={stored.new_jobs} "
                f"reactivated={stored.reactivated} "
                f"missing={stored.marked_missing} "
                f"withdrawn={stored.withdrawn} expired={stored.expired} "
                f"purged={stored.purged} database={args.database}",
                file=sys.stderr,
            )
            if stored.reconciled_sources:
                print(
                    "[jpjobs] reconciled sources: "
                    + ", ".join(stored.reconciled_sources),
                    file=sys.stderr,
                )
            for source, reason in stored.skipped_sources.items():
                print(
                    f"[jpjobs] skipped withdrawal reconciliation for "
                    f"{source}: {reason}",
                    file=sys.stderr,
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
