"""SQLite persistence and conservative lifecycle maintenance."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from statistics import median

from jpjobs.schema import ScanResult, SourceStats


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    scanned_at TEXT PRIMARY KEY,
    window_start TEXT,
    window_end TEXT,
    maintenance INTEGER NOT NULL DEFAULT 0,
    raw_total INTEGER NOT NULL,
    total_kept INTEGER NOT NULL,
    filtered_out INTEGER NOT NULL,
    duplicates_merged INTEGER NOT NULL,
    warnings_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    prefecture TEXT,
    date_posted TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    missing_count INTEGER NOT NULL DEFAULT 0,
    last_checked_at TEXT,
    withdrawn_at TEXT,
    expired_at TEXT,
    removal_reason TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sightings (
    job_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    missing_count INTEGER NOT NULL DEFAULT 0,
    last_checked_at TEXT,
    withdrawn_at TEXT,
    PRIMARY KEY (job_id, source, source_id),
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS source_runs (
    scanned_at TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    discovery_status TEXT NOT NULL,
    coverage_complete INTEGER,
    total INTEGER NOT NULL,
    kept INTEGER NOT NULL,
    pages_fetched INTEGER NOT NULL,
    reconciliation_applied INTEGER NOT NULL DEFAULT 0,
    reconciliation_skip_reason TEXT,
    PRIMARY KEY (scanned_at, source),
    FOREIGN KEY (scanned_at) REFERENCES runs(scanned_at)
);

CREATE TABLE IF NOT EXISTS detail_attempts (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    last_attempted_at TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE INDEX IF NOT EXISTS jobs_company_title
ON jobs(company, title);

CREATE INDEX IF NOT EXISTS sightings_source_id
ON sightings(source, source_id);

CREATE INDEX IF NOT EXISTS source_runs_source_scanned
ON source_runs(source, scanned_at);

CREATE INDEX IF NOT EXISTS detail_attempts_last_attempted
ON detail_attempts(last_attempted_at);
"""

LIFECYCLE_INDEXES = """
CREATE INDEX IF NOT EXISTS jobs_status_posted
ON jobs(status, date_posted);

CREATE INDEX IF NOT EXISTS sightings_source_status
ON sightings(source, status);
"""


@dataclass
class StoreStats:
    stored: int = 0
    new_jobs: int = 0
    reactivated: int = 0
    marked_missing: int = 0
    withdrawn: int = 0
    expired: int = 0
    purged: int = 0
    reconciled_sources: list[str] = field(default_factory=list)
    skipped_sources: dict[str, str] = field(default_factory=dict)


def _merge_payload(previous_json: str | None, current: dict) -> dict:
    """Keep richer stored detail fields when a discovery-only scan is saved."""
    if not previous_json:
        return current
    try:
        previous = json.loads(previous_json)
    except (TypeError, json.JSONDecodeError):
        return current
    if not isinstance(previous, dict):
        return current

    for key in (
        "company",
        "workplace",
        "prefecture",
        "prefecture_name",
        "city",
        "employment_type",
        "matched_keyword",
    ):
        if not current.get(key) and previous.get(key):
            current[key] = previous[key]

    for key in ("description", "description_snippet"):
        if len(str(previous.get(key) or "")) > len(str(current.get(key) or "")):
            current[key] = previous[key]

    current_wage = current.get("wage") or {}
    previous_wage = previous.get("wage") or {}
    if not any(
        current_wage.get(key) for key in ("min", "max", "unit", "raw")
    ) and isinstance(previous_wage, dict):
        current["wage"] = previous_wage

    for key in ("language", "quality_flags", "found_on"):
        current[key] = list(
            dict.fromkeys([*(previous.get(key) or []), *(current.get(key) or [])])
        )
    for key in ("source_ids", "source_urls"):
        merged = dict(previous.get(key) or {})
        merged.update(current.get(key) or {})
        current[key] = merged

    if not current.get("detail_status") and previous.get("detail_status"):
        current["detail_status"] = previous["detail_status"]
    return current


class JobStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 30000")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        run_columns = {
            "window_start": "TEXT",
            "window_end": "TEXT",
            "maintenance": "INTEGER NOT NULL DEFAULT 0",
        }
        job_columns = {
            "status": "TEXT NOT NULL DEFAULT 'active'",
            "missing_count": "INTEGER NOT NULL DEFAULT 0",
            "last_checked_at": "TEXT",
            "withdrawn_at": "TEXT",
            "expired_at": "TEXT",
            "removal_reason": "TEXT",
        }
        sighting_columns = {
            "status": "TEXT NOT NULL DEFAULT 'active'",
            "missing_count": "INTEGER NOT NULL DEFAULT 0",
            "last_checked_at": "TEXT",
            "withdrawn_at": "TEXT",
        }
        for table, columns in (
            ("runs", run_columns),
            ("jobs", job_columns),
            ("sightings", sighting_columns),
        ):
            existing = {
                row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")
            }
            for name, definition in columns.items():
                if name not in existing:
                    self.connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
                    )
        self.connection.executescript(LIFECYCLE_INDEXES)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def known_sighting_keys(self) -> set[tuple[str, str]]:
        """Return currently live source IDs so daily scans can skip old details."""
        return {
            (str(source), str(source_id))
            for source, source_id in self.connection.execute(
                """
                SELECT source, source_id
                FROM sightings
                WHERE status IN ('active', 'missing')
                """
            )
        }

    def known_job_dates(self) -> dict[tuple[str, str], str]:
        """Return stored dates to hydrate discovery cards that omit them."""
        return {
            (str(source), str(source_id)): str(date_posted)
            for source, source_id, date_posted in self.connection.execute(
                """
                SELECT s.source, s.source_id, j.date_posted
                FROM sightings AS s
                JOIN jobs AS j ON j.id = s.job_id
                WHERE s.status IN ('active', 'missing')
                  AND j.date_posted IS NOT NULL
                  AND j.date_posted != ''
                """
            )
        }

    def detail_skip_keys(
        self,
        *,
        retry_after_days: int = 7,
        as_of: str | None = None,
    ) -> set[tuple[str, str]]:
        """Skip live jobs and recently attempted filtered-out detail pages."""
        if retry_after_days < 1:
            raise ValueError("retry_after_days must be at least 1")
        reference = date.fromisoformat(as_of) if as_of else date.today()
        cutoff = (reference - timedelta(days=retry_after_days)).isoformat()
        keys = self.known_sighting_keys()
        keys.update(
            (str(source), str(source_id))
            for source, source_id in self.connection.execute(
                """
                SELECT source, source_id
                FROM detail_attempts
                WHERE date(last_attempted_at) >= date(?)
                """,
                (cutoff,),
            )
        )
        return keys

    def save_scan(
        self,
        result: ScanResult,
        *,
        maintenance: bool = False,
        missing_threshold: int = 3,
        retention_days: int = 90,
        purge_grace_days: int = 30,
        sudden_drop_ratio: float = 0.20,
    ) -> StoreStats:
        if maintenance and (not result.window_start or not result.window_end):
            raise ValueError("maintenance scans require a bounded date window")
        if missing_threshold < 1:
            raise ValueError("missing_threshold must be at least 1")
        if retention_days < 1 or purge_grace_days < 0:
            raise ValueError("retention values must be non-negative")

        summary = StoreStats(stored=len(result.jobs))
        current_keys: dict[str, set[str]] = defaultdict(set)
        reconciliation: dict[str, tuple[bool, str | None]] = {}

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO runs (
                    scanned_at, window_start, window_end, maintenance,
                    raw_total, total_kept, filtered_out,
                    duplicates_merged, warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scanned_at) DO UPDATE SET
                    window_start = excluded.window_start,
                    window_end = excluded.window_end,
                    maintenance = excluded.maintenance,
                    raw_total = excluded.raw_total,
                    total_kept = excluded.total_kept,
                    filtered_out = excluded.filtered_out,
                    duplicates_merged = excluded.duplicates_merged,
                    warnings_json = excluded.warnings_json
                """,
                (
                    result.scanned_at,
                    result.window_start,
                    result.window_end,
                    int(maintenance),
                    result.raw_total,
                    result.total_kept,
                    result.filtered_out,
                    result.duplicates_merged,
                    json.dumps(result.warnings, ensure_ascii=False),
                ),
            )

            for job in result.jobs:
                source_ids = job.source_ids or {job.source: job.source_id}
                source_urls = job.source_urls or {job.source: job.url}
                prior_sightings = []
                for source, source_id in source_ids.items():
                    current_keys[source].add(str(source_id))
                    sighting = self.connection.execute(
                        """
                        SELECT job_id, first_seen_at, status
                        FROM sightings
                        WHERE source = ? AND source_id = ?
                        ORDER BY last_seen_at DESC
                        LIMIT 1
                        """,
                        (source, str(source_id)),
                    ).fetchone()
                    if sighting:
                        prior_sightings.append(sighting)

                existing = self.connection.execute(
                    """
                    SELECT first_seen_at, status, payload_json
                    FROM jobs
                    WHERE id = ?
                    """,
                    (job.id,),
                ).fetchone()
                historical_first_seen = [row[1] for row in prior_sightings]
                if existing:
                    historical_first_seen.append(existing[0])
                first_seen_at = (
                    min(historical_first_seen)
                    if historical_first_seen
                    else result.scanned_at
                )
                was_known = existing is not None or bool(prior_sightings)
                if not was_known:
                    summary.new_jobs += 1
                elif (existing and existing[1] != "active") or any(
                    row[2] not in ("active", "missing") for row in prior_sightings
                ):
                    summary.reactivated += 1

                job.first_seen_at = first_seen_at
                job.last_seen_at = result.scanned_at
                payload_dict = _merge_payload(
                    existing[2] if existing else None,
                    asdict(job),
                )
                payload = json.dumps(
                    payload_dict,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                self.connection.execute(
                    """
                    INSERT INTO jobs (
                        id, title, company, prefecture, date_posted,
                        first_seen_at, last_seen_at, status, missing_count,
                        last_checked_at, withdrawn_at, expired_at,
                        removal_reason, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0, ?, NULL, NULL, NULL, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        company = excluded.company,
                        prefecture = excluded.prefecture,
                        date_posted = excluded.date_posted,
                        last_seen_at = excluded.last_seen_at,
                        status = 'active',
                        missing_count = 0,
                        last_checked_at = excluded.last_checked_at,
                        withdrawn_at = NULL,
                        expired_at = NULL,
                        removal_reason = NULL,
                        payload_json = excluded.payload_json
                    """,
                    (
                        job.id,
                        job.title,
                        job.company,
                        job.prefecture,
                        job.date_posted,
                        first_seen_at,
                        result.scanned_at,
                        result.scanned_at,
                        payload,
                    ),
                )

                for source, source_id in source_ids.items():
                    source_id = str(source_id)
                    url = source_urls.get(source, job.url)
                    previous = self.connection.execute(
                        """
                        SELECT job_id, first_seen_at
                        FROM sightings
                        WHERE source = ? AND source_id = ?
                        ORDER BY last_seen_at DESC
                        LIMIT 1
                        """,
                        (source, source_id),
                    ).fetchone()
                    sighting_first_seen = previous[1] if previous else result.scanned_at
                    if previous and previous[0] != job.id:
                        self.connection.execute(
                            """
                            DELETE FROM sightings
                            WHERE source = ? AND source_id = ?
                            """,
                            (source, source_id),
                        )
                    self.connection.execute(
                        """
                        INSERT INTO sightings (
                            job_id, source, source_id, url,
                            first_seen_at, last_seen_at, status,
                            missing_count, last_checked_at, withdrawn_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 'active', 0, ?, NULL)
                        ON CONFLICT(job_id, source, source_id) DO UPDATE SET
                            url = excluded.url,
                            last_seen_at = excluded.last_seen_at,
                            status = 'active',
                            missing_count = 0,
                            last_checked_at = excluded.last_checked_at,
                            withdrawn_at = NULL
                        """,
                        (
                            job.id,
                            source,
                            source_id,
                            url,
                            sighting_first_seen,
                            result.scanned_at,
                            result.scanned_at,
                        ),
                    )

            for attempt in result.detail_attempts:
                source = str(attempt.get("source") or "")
                source_id = str(attempt.get("source_id") or "")
                status = str(attempt.get("status") or "")
                if not source or not source_id or not status:
                    continue
                self.connection.execute(
                    """
                    INSERT INTO detail_attempts (
                        source, source_id, last_attempted_at, status
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(source, source_id) DO UPDATE SET
                        last_attempted_at = excluded.last_attempted_at,
                        status = excluded.status
                    """,
                    (source, source_id, result.scanned_at, status),
                )

            if maintenance:
                for source_stats in result.per_source:
                    source = source_stats.name
                    reason = self._reconciliation_skip_reason(
                        source_stats,
                        current_count=len(current_keys[source]),
                        window_start=str(result.window_start),
                        window_end=str(result.window_end),
                        sudden_drop_ratio=sudden_drop_ratio,
                    )
                    if reason:
                        summary.skipped_sources[source] = reason
                        reconciliation[source] = (False, reason)
                        continue
                    self._reconcile_source(
                        source=source,
                        current_ids=current_keys[source],
                        scanned_at=result.scanned_at,
                        window_start=str(result.window_start),
                        window_end=str(result.window_end),
                        missing_threshold=missing_threshold,
                        summary=summary,
                    )
                    summary.reconciled_sources.append(source)
                    reconciliation[source] = (True, None)

                self._refresh_job_states(result.scanned_at)
                summary.expired = self._expire_old_jobs(
                    scanned_at=result.scanned_at,
                    window_end=str(result.window_end),
                    retention_days=retention_days,
                )
                summary.purged = self._purge_old_tombstones(
                    window_end=str(result.window_end),
                    purge_grace_days=purge_grace_days,
                )
                self.connection.execute(
                    """
                    DELETE FROM jobs
                    WHERE NOT EXISTS (
                        SELECT 1 FROM sightings WHERE sightings.job_id = jobs.id
                    )
                    """
                )

            for source_stats in result.per_source:
                applied, reason = reconciliation.get(
                    source_stats.name,
                    (False, "maintenance_disabled"),
                )
                discovery_status = source_stats.discovery_status or source_stats.status
                coverage = (
                    None
                    if source_stats.coverage_complete is None
                    else int(source_stats.coverage_complete)
                )
                self.connection.execute(
                    """
                    INSERT INTO source_runs (
                        scanned_at, source, status, discovery_status,
                        coverage_complete, total, kept, pages_fetched,
                        reconciliation_applied, reconciliation_skip_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(scanned_at, source) DO UPDATE SET
                        status = excluded.status,
                        discovery_status = excluded.discovery_status,
                        coverage_complete = excluded.coverage_complete,
                        total = excluded.total,
                        kept = excluded.kept,
                        pages_fetched = excluded.pages_fetched,
                        reconciliation_applied = excluded.reconciliation_applied,
                        reconciliation_skip_reason =
                            excluded.reconciliation_skip_reason
                    """,
                    (
                        result.scanned_at,
                        source_stats.name,
                        source_stats.status,
                        discovery_status,
                        coverage,
                        source_stats.total,
                        source_stats.kept,
                        source_stats.pages_fetched,
                        int(applied),
                        reason,
                    ),
                )
        return summary

    def _reconciliation_skip_reason(
        self,
        source_stats: SourceStats,
        *,
        current_count: int,
        window_start: str,
        window_end: str,
        sudden_drop_ratio: float,
    ) -> str | None:
        discovery_status = source_stats.discovery_status or source_stats.status
        if discovery_status not in ("success", "no_results"):
            return f"discovery_status_{discovery_status}"
        if source_stats.coverage_complete is not True:
            return "coverage_incomplete"

        history = [
            int(row[0])
            for row in self.connection.execute(
                """
                SELECT kept
                FROM source_runs
                WHERE source = ?
                  AND reconciliation_applied = 1
                ORDER BY scanned_at DESC
                LIMIT 7
                """,
                (source_stats.name,),
            )
        ]
        if history:
            baseline = float(median(history))
        else:
            baseline = float(
                self.connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM sightings AS s
                    JOIN jobs AS j ON j.id = s.job_id
                    WHERE s.source = ?
                      AND date(j.date_posted) BETWEEN date(?) AND date(?)
                      AND s.status IN ('active', 'missing')
                    """,
                    (source_stats.name, window_start, window_end),
                ).fetchone()[0]
            )

        if baseline >= 10 and current_count < baseline * sudden_drop_ratio:
            return f"sudden_drop_{current_count}_of_{int(baseline)}"
        return None

    def _reconcile_source(
        self,
        *,
        source: str,
        current_ids: set[str],
        scanned_at: str,
        window_start: str,
        window_end: str,
        missing_threshold: int,
        summary: StoreStats,
    ) -> None:
        candidates = self.connection.execute(
            """
            SELECT s.job_id, s.source_id, s.status, s.missing_count
            FROM sightings AS s
            JOIN jobs AS j ON j.id = s.job_id
            WHERE s.source = ?
              AND date(j.date_posted) BETWEEN date(?) AND date(?)
              AND s.status IN ('active', 'missing')
            """,
            (source, window_start, window_end),
        ).fetchall()
        for job_id, source_id, old_status, old_missing_count in candidates:
            if str(source_id) in current_ids:
                continue
            missing_count = int(old_missing_count) + 1
            if missing_count >= missing_threshold:
                status = "withdrawn"
                withdrawn_at = scanned_at
                if old_status != "withdrawn":
                    summary.withdrawn += 1
            else:
                status = "missing"
                withdrawn_at = None
                summary.marked_missing += 1
            self.connection.execute(
                """
                UPDATE sightings
                SET status = ?, missing_count = ?, last_checked_at = ?,
                    withdrawn_at = ?
                WHERE job_id = ? AND source = ? AND source_id = ?
                """,
                (
                    status,
                    missing_count,
                    scanned_at,
                    withdrawn_at,
                    job_id,
                    source,
                    source_id,
                ),
            )

    def _refresh_job_states(self, scanned_at: str) -> None:
        rows = self.connection.execute(
            """
            SELECT
                job_id,
                MAX(CASE status
                    WHEN 'active' THEN 3
                    WHEN 'missing' THEN 2
                    WHEN 'withdrawn' THEN 1
                    ELSE 0
                END) AS state_rank,
                MAX(missing_count),
                MAX(last_checked_at)
            FROM sightings
            GROUP BY job_id
            """
        ).fetchall()
        for job_id, state_rank, missing_count, last_checked_at in rows:
            status = {
                3: "active",
                2: "missing",
                1: "withdrawn",
                0: "expired",
            }[int(state_rank)]
            self.connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    missing_count = ?,
                    last_checked_at = ?,
                    withdrawn_at = CASE
                        WHEN ? = 'withdrawn'
                        THEN COALESCE(withdrawn_at, ?)
                        ELSE NULL
                    END,
                    expired_at = CASE
                        WHEN ? = 'expired'
                        THEN COALESCE(expired_at, ?)
                        ELSE NULL
                    END,
                    removal_reason = CASE
                        WHEN ? = 'withdrawn' THEN 'all_sources_withdrawn'
                        WHEN ? = 'expired' THEN 'retention_window'
                        ELSE NULL
                    END
                WHERE id = ?
                """,
                (
                    status,
                    int(missing_count or 0),
                    last_checked_at,
                    status,
                    scanned_at,
                    status,
                    scanned_at,
                    status,
                    status,
                    job_id,
                ),
            )

    def _expire_old_jobs(
        self,
        *,
        scanned_at: str,
        window_end: str,
        retention_days: int,
    ) -> int:
        threshold = date.fromisoformat(window_end) - timedelta(days=retention_days)
        job_ids = [
            row[0]
            for row in self.connection.execute(
                """
                SELECT id
                FROM jobs
                WHERE date(date_posted) < date(?)
                  AND status NOT IN ('withdrawn', 'expired')
                """,
                (threshold.isoformat(),),
            )
        ]
        if not job_ids:
            return 0
        placeholders = ",".join("?" for _ in job_ids)
        self.connection.execute(
            f"""
            UPDATE jobs
            SET status = 'expired',
                expired_at = COALESCE(expired_at, ?),
                removal_reason = 'retention_window'
            WHERE id IN ({placeholders})
            """,
            (scanned_at, *job_ids),
        )
        self.connection.execute(
            f"""
            UPDATE sightings
            SET status = 'expired', last_checked_at = ?
            WHERE job_id IN ({placeholders})
            """,
            (scanned_at, *job_ids),
        )
        return len(job_ids)

    def _purge_old_tombstones(
        self,
        *,
        window_end: str,
        purge_grace_days: int,
    ) -> int:
        cutoff = (
            date.fromisoformat(window_end) - timedelta(days=purge_grace_days)
        ).isoformat()
        job_ids = [
            row[0]
            for row in self.connection.execute(
                """
                SELECT id
                FROM jobs
                WHERE (
                    status = 'withdrawn'
                    AND date(withdrawn_at) <= date(?)
                ) OR (
                    status = 'expired'
                    AND date(expired_at) <= date(?)
                )
                """,
                (cutoff, cutoff),
            )
        ]
        if not job_ids:
            return 0
        placeholders = ",".join("?" for _ in job_ids)
        self.connection.execute(
            f"DELETE FROM sightings WHERE job_id IN ({placeholders})",
            job_ids,
        )
        self.connection.execute(
            f"DELETE FROM jobs WHERE id IN ({placeholders})",
            job_ids,
        )
        return len(job_ids)
