from jpjobs.schema import Job, ScanResult
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
