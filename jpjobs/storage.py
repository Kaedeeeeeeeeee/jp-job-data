"""SQLite persistence for incremental job observations."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from jpjobs.schema import ScanResult


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    scanned_at TEXT PRIMARY KEY,
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
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sightings (
    job_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (job_id, source, source_id),
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX IF NOT EXISTS jobs_company_title
ON jobs(company, title);

CREATE INDEX IF NOT EXISTS sightings_source_id
ON sightings(source, source_id);
"""


class JobStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def save_scan(self, result: ScanResult) -> int:
        with self.connection:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO runs (
                    scanned_at, raw_total, total_kept, filtered_out,
                    duplicates_merged, warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    result.scanned_at,
                    result.raw_total,
                    result.total_kept,
                    result.filtered_out,
                    result.duplicates_merged,
                    json.dumps(result.warnings, ensure_ascii=False),
                ),
            )

            for job in result.jobs:
                existing = self.connection.execute(
                    "SELECT first_seen_at FROM jobs WHERE id = ?",
                    (job.id,),
                ).fetchone()
                first_seen_at = existing[0] if existing else result.scanned_at
                job.first_seen_at = first_seen_at
                job.last_seen_at = result.scanned_at
                payload = json.dumps(
                    asdict(job),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                self.connection.execute(
                    """
                    INSERT INTO jobs (
                        id, title, company, prefecture, date_posted,
                        first_seen_at, last_seen_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        company = excluded.company,
                        prefecture = excluded.prefecture,
                        date_posted = excluded.date_posted,
                        last_seen_at = excluded.last_seen_at,
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
                        payload,
                    ),
                )

                source_ids = job.source_ids or {job.source: job.source_id}
                source_urls = job.source_urls or {job.source: job.url}
                for source, source_id in source_ids.items():
                    url = source_urls.get(source, job.url)
                    sighting = self.connection.execute(
                        """
                        SELECT first_seen_at
                        FROM sightings
                        WHERE job_id = ? AND source = ? AND source_id = ?
                        """,
                        (job.id, source, source_id),
                    ).fetchone()
                    sighting_first_seen = sighting[0] if sighting else result.scanned_at
                    self.connection.execute(
                        """
                        INSERT INTO sightings (
                            job_id, source, source_id, url,
                            first_seen_at, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(job_id, source, source_id) DO UPDATE SET
                            url = excluded.url,
                            last_seen_at = excluded.last_seen_at
                        """,
                        (
                            job.id,
                            source,
                            source_id,
                            url,
                            sighting_first_seen,
                            result.scanned_at,
                        ),
                    )
        return len(result.jobs)
