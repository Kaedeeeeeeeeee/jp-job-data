import sqlite3

from jpjobs.schema import Job, ScanResult, SourceStats
from jpjobs.storage import JobStore


def result(scanned_at):
    job = Job(
        id="job-id",
        source="green",
        source_id="123",
        url="https://example.com/job",
        found_on=["green"],
        title="Backend Engineer",
        company="Example",
        source_ids={"green": "123"},
        source_urls={"green": "https://example.com/job"},
    )
    return ScanResult(
        scanned_at=scanned_at,
        total_kept=1,
        jobs=[job],
        raw_total=1,
    )


def test_sqlite_store_preserves_first_seen_and_updates_last_seen(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    with JobStore(database) as store:
        first = result("2026-07-22T00:00:00Z")
        store.save_scan(first)
        second = result("2026-07-23T00:00:00Z")
        store.save_scan(second)
        row = store.connection.execute(
            "SELECT first_seen_at, last_seen_at FROM jobs WHERE id = 'job-id'"
        ).fetchone()
        sightings = store.connection.execute(
            "SELECT COUNT(*) FROM sightings"
        ).fetchone()[0]

    assert row == ("2026-07-22T00:00:00Z", "2026-07-23T00:00:00Z")
    assert sightings == 1


def maintenance_result(
    scanned_at,
    jobs,
    *,
    source="green",
    coverage_complete=True,
    discovery_status="success",
):
    return ScanResult(
        scanned_at=scanned_at,
        total_kept=len(jobs),
        jobs=jobs,
        window_start="2026-06-25",
        window_end=scanned_at[:10],
        raw_total=len(jobs),
        per_source=[
            SourceStats(
                name=source,
                status=discovery_status,
                discovery_status=discovery_status,
                kept=len(jobs),
                total=len(jobs),
                coverage_complete=coverage_complete,
            )
        ],
    )


def lifecycle_job(source_id, *, job_id=None, source="green", date_posted="2026-07-01"):
    return Job(
        id=job_id or f"job-{source_id}",
        source=source,
        source_id=source_id,
        url=f"https://example.com/{source}/{source_id}",
        found_on=[source],
        title=f"Engineer {source_id}",
        company="Example",
        date_posted=date_posted,
        source_ids={source: source_id},
        source_urls={source: f"https://example.com/{source}/{source_id}"},
    )


def test_complete_scans_require_three_misses_before_withdrawal(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    with JobStore(database) as store:
        jobs = [lifecycle_job("1"), lifecycle_job("2")]
        store.save_scan(
            maintenance_result("2026-07-25T00:00:00Z", jobs),
            maintenance=True,
        )

        for day in (26, 27):
            summary = store.save_scan(
                maintenance_result(
                    f"2026-07-{day}T00:00:00Z",
                    [lifecycle_job("2")],
                ),
                maintenance=True,
            )
            assert summary.withdrawn == 0

        summary = store.save_scan(
            maintenance_result(
                "2026-07-28T00:00:00Z",
                [lifecycle_job("2")],
            ),
            maintenance=True,
        )
        row = store.connection.execute(
            "SELECT status, missing_count, withdrawn_at FROM jobs WHERE id = 'job-1'"
        ).fetchone()

    assert summary.withdrawn == 1
    assert row == ("withdrawn", 3, "2026-07-28T00:00:00Z")


def test_incomplete_scan_never_marks_unseen_jobs_missing(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    with JobStore(database) as store:
        jobs = [lifecycle_job("1"), lifecycle_job("2")]
        store.save_scan(
            maintenance_result("2026-07-25T00:00:00Z", jobs),
            maintenance=True,
        )
        summary = store.save_scan(
            maintenance_result(
                "2026-07-26T00:00:00Z",
                [lifecycle_job("2")],
                coverage_complete=False,
            ),
            maintenance=True,
        )
        row = store.connection.execute(
            "SELECT status, missing_count FROM jobs WHERE id = 'job-1'"
        ).fetchone()

    assert summary.skipped_sources == {"green": "coverage_incomplete"}
    assert row == ("active", 0)


def test_sudden_source_drop_blocks_withdrawal_reconciliation(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    with JobStore(database) as store:
        jobs = [lifecycle_job(str(number)) for number in range(20)]
        store.save_scan(
            maintenance_result("2026-07-25T00:00:00Z", jobs),
            maintenance=True,
        )
        summary = store.save_scan(
            maintenance_result(
                "2026-07-26T00:00:00Z",
                [lifecycle_job("18"), lifecycle_job("19")],
            ),
            maintenance=True,
        )
        missing = store.connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE status = 'missing'"
        ).fetchone()[0]

    assert summary.skipped_sources["green"] == "sudden_drop_2_of_20"
    assert missing == 0


def test_other_active_sighting_keeps_cross_source_job_active(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    combined = lifecycle_job("green-1", job_id="shared")
    combined.source_ids = {"green": "green-1", "gaijinpot": "gaijin-1"}
    combined.source_urls = {
        "green": "https://example.com/green/green-1",
        "gaijinpot": "https://example.com/gaijinpot/gaijin-1",
    }
    combined.found_on = ["green", "gaijinpot"]
    gaijin = lifecycle_job("gaijin-1", job_id="shared", source="gaijinpot")

    with JobStore(database) as store:
        initial = ScanResult(
            scanned_at="2026-07-25T00:00:00Z",
            total_kept=1,
            jobs=[combined],
            window_start="2026-06-25",
            window_end="2026-07-25",
            raw_total=1,
            per_source=[
                SourceStats(
                    name=source,
                    status="success",
                    discovery_status="success",
                    kept=1,
                    total=1,
                    coverage_complete=True,
                )
                for source in ("green", "gaijinpot")
            ],
        )
        store.save_scan(initial, maintenance=True)

        for day in (26, 27, 28):
            daily = ScanResult(
                scanned_at=f"2026-07-{day}T00:00:00Z",
                total_kept=1,
                jobs=[gaijin],
                window_start="2026-06-25",
                window_end=f"2026-07-{day}",
                raw_total=1,
                per_source=[
                    SourceStats(
                        name="green",
                        status="success",
                        discovery_status="success",
                        kept=0,
                        total=0,
                        coverage_complete=True,
                    ),
                    SourceStats(
                        name="gaijinpot",
                        status="success",
                        discovery_status="success",
                        kept=1,
                        total=1,
                        coverage_complete=True,
                    ),
                ],
            )
            store.save_scan(daily, maintenance=True)

        job_status = store.connection.execute(
            "SELECT status FROM jobs WHERE id = 'shared'"
        ).fetchone()[0]
        green_status = store.connection.execute(
            """
            SELECT status FROM sightings
            WHERE source = 'green' AND source_id = 'green-1'
            """
        ).fetchone()[0]

    assert job_status == "active"
    assert green_status == "withdrawn"


def test_old_jobs_expire_then_purge_after_grace_period(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    old_job = lifecycle_job("old", date_posted="2026-01-01")
    with JobStore(database) as store:
        first = maintenance_result("2026-07-25T00:00:00Z", [old_job])
        first.window_start = "2025-12-01"
        summary = store.save_scan(
            first,
            maintenance=True,
            retention_days=90,
            purge_grace_days=30,
        )
        assert summary.expired == 1
        assert (
            store.connection.execute(
                "SELECT status FROM jobs WHERE id = 'job-old'"
            ).fetchone()[0]
            == "expired"
        )

        later = maintenance_result("2026-08-25T00:00:00Z", [])
        later.window_start = "2025-12-01"
        summary = store.save_scan(
            later,
            maintenance=True,
            retention_days=90,
            purge_grace_days=30,
        )
        count = store.connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE id = 'job-old'"
        ).fetchone()[0]

    assert summary.purged == 1
    assert count == 0


def test_existing_v1_database_is_migrated_in_place(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE runs (
            scanned_at TEXT PRIMARY KEY,
            raw_total INTEGER NOT NULL,
            total_kept INTEGER NOT NULL,
            filtered_out INTEGER NOT NULL,
            duplicates_merged INTEGER NOT NULL,
            warnings_json TEXT NOT NULL
        );
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            prefecture TEXT,
            date_posted TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE sightings (
            job_id TEXT NOT NULL,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            url TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY (job_id, source, source_id),
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );
        """
    )
    connection.close()

    with JobStore(database) as store:
        job_columns = {
            row[1] for row in store.connection.execute("PRAGMA table_info(jobs)")
        }
        sighting_columns = {
            row[1] for row in store.connection.execute("PRAGMA table_info(sightings)")
        }

    assert {"status", "missing_count", "withdrawn_at"} <= job_columns
    assert {"status", "missing_count", "withdrawn_at"} <= sighting_columns


def test_stored_dates_hydrate_cards_and_failed_details_retry_weekly(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    first = maintenance_result(
        "2026-07-25T00:00:00Z",
        [lifecycle_job("known", date_posted="2026-07-20")],
    )
    first.detail_attempts = [
        {
            "source": "green",
            "source_id": "filtered-out",
            "status": "fetch_error",
        }
    ]
    with JobStore(database) as store:
        store.save_scan(first)
        dates = store.known_job_dates()
        immediate_skip = store.detail_skip_keys(as_of="2026-07-25")
        later_skip = store.detail_skip_keys(as_of="2026-08-02")

    assert dates[("green", "known")] == "2026-07-20"
    assert ("green", "known") in immediate_skip
    assert ("green", "filtered-out") in immediate_skip
    assert ("green", "filtered-out") not in later_skip
