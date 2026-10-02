import gzip
import hashlib
import json
import sqlite3

from jpjobs.cloudflare_sync import (
    canonical_json,
    create_outbox_run,
    extract_explicit_signals,
    read_snapshot,
)
from jpjobs.storage import JobStore


def _database(path):
    with JobStore(path) as store:
        payload = {
            "id": "job-1",
            "source": "tokyodev",
            "source_id": "native-1",
            "url": "https://example.test/jobs/1",
            "title": "Backend Engineer",
            "company": "Example K.K.",
            "description": (
                "Business English is accepted. Overseas applicants are welcome "
                "and visa sponsorship is available."
            ),
            "description_snippet": "Build APIs in Tokyo.",
            "workplace": "Tokyo",
            "prefecture": "tokyo",
            "prefecture_name": "Tokyo",
            "city": "Tokyo",
            "remote": False,
            "wage": {
                "min": 7_000_000,
                "max": 10_000_000,
                "unit": "annual",
                "raw": "¥7M-¥10M",
            },
            "employment_type": "fulltime",
            "date_posted": "2026-07-28",
            "language": ["english"],
            "source_urls": {"tokyodev": "https://example.test/jobs/1"},
            "source_ids": {"tokyodev": "native-1"},
            "quality_flags": [],
        }
        store.connection.execute(
            """
            INSERT INTO runs (
              scanned_at, window_start, window_end, maintenance, raw_total,
              total_kept, filtered_out, duplicates_merged, warnings_json
            ) VALUES (?, ?, ?, 1, 1, 1, 0, 0, '[]')
            """,
            (
                "2026-07-29T00:00:00Z",
                "2026-06-29",
                "2026-07-29",
            ),
        )
        store.connection.execute(
            """
            INSERT INTO jobs (
              id, title, company, prefecture, date_posted, first_seen_at,
              last_seen_at, status, missing_count, last_checked_at,
              payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0, ?, ?)
            """,
            (
                "job-1",
                "Backend Engineer",
                "Example K.K.",
                "tokyo",
                "2026-07-28",
                "2026-07-28T00:00:00Z",
                "2026-07-29T00:00:00Z",
                "2026-07-29T00:00:00Z",
                json.dumps(payload),
            ),
        )
        store.connection.execute(
            """
            INSERT INTO source_runs (
              scanned_at, source, status, discovery_status,
              coverage_complete, total, kept, pages_fetched,
              reconciliation_applied, reconciliation_skip_reason
            ) VALUES (?, 'tokyodev', 'success', 'success', 1, 1, 1, 1, 1, NULL)
            """,
            ("2026-07-29T00:00:00Z",),
        )
        store.connection.commit()


def test_explicit_signals_never_infer_from_absence():
    assert extract_explicit_signals({"description": "Build reliable APIs."}) == []
    signals = extract_explicit_signals(
        {"description": "Overseas applicants are welcome. Visa sponsorship available."}
    )
    assert {(signal["kind"], signal["value"]) for signal in signals} == {
        ("overseas", "supported"),
        ("visa", "possible_support"),
    }
    assert all(signal["evidence"] for signal in signals)


def test_snapshot_marks_unknown_company_instead_of_rejecting_job(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    _database(database)
    connection = sqlite3.connect(database)
    payload = json.loads(
        connection.execute(
            "SELECT payload_json FROM jobs WHERE id = 'job-1'"
        ).fetchone()[0]
    )
    payload["company"] = ""
    connection.execute(
        "UPDATE jobs SET company = '', payload_json = ? WHERE id = 'job-1'",
        (json.dumps(payload),),
    )
    connection.commit()
    connection.close()

    job = read_snapshot(database)["jobs"][0]

    assert job["company"] == "Unknown company"
    assert "missing_company" in job["qualityFlags"]


def test_snapshot_and_outbox_contract(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    _database(database)
    snapshot = read_snapshot(database)

    assert len(snapshot["jobs"]) == 1
    assert snapshot["jobs"][0]["sourceId"] == "native-1"
    assert snapshot["sourceHealth"][0]["coverageComplete"] is True

    run_dir = create_outbox_run(snapshot, {}, tmp_path / "outbox")
    chunk = json.loads(gzip.decompress(next(run_dir.glob("*.json.gz")).read_bytes()))
    envelope = {
        "jobs": chunk["jobs"],
        "run": chunk["run"],
        "sourceHealth": chunk["sourceHealth"],
    }
    checksum = hashlib.sha256(canonical_json(envelope).encode()).hexdigest()

    assert chunk["schemaVersion"] == 1
    assert chunk["chunkIndex"] == 0
    assert chunk["chunkCount"] == 1
    assert chunk["checksum"] == checksum
    assert chunk["jobs"][0]["status"] == "active"
    assert (
        json.loads((run_dir / "state.json").read_text())["manifestChecksum"]
        == snapshot["run"]["manifestChecksum"]
    )


def test_unchanged_snapshot_emits_empty_health_chunk(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    _database(database)
    snapshot = read_snapshot(database)
    run_dir = create_outbox_run(
        snapshot,
        {"hashes": snapshot["hashes"]},
        tmp_path / "outbox",
    )
    chunk = json.loads(gzip.decompress(next(run_dir.glob("*.json.gz")).read_bytes()))

    assert chunk["jobs"] == []
    assert chunk["sourceHealth"][0]["source"] == "tokyodev"


def test_snapshot_leaves_database_count_unchanged(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    _database(database)
    before = sqlite3.connect(database).execute("SELECT COUNT(*) FROM jobs").fetchone()
    read_snapshot(database)
    after = sqlite3.connect(database).execute("SELECT COUNT(*) FROM jobs").fetchone()
    assert before == after == (1,)
