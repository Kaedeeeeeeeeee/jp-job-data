import gzip
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from jpjobs.backup import backup_database
from jpjobs.scheduler import _seconds_until_due


def test_backup_is_consistent_and_rotated(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE values_table (value TEXT)")
    connection.execute("INSERT INTO values_table VALUES ('kept')")
    connection.commit()
    connection.close()

    backup_dir = tmp_path / "backups"
    for number in range(3):
        stale = backup_dir / f"jobs-2026010{number + 1}T000000Z.sqlite3.gz"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_bytes(b"stale")

    backup = backup_database(database, backup_dir, keep=2)
    backups = sorted(backup_dir.glob("jobs-*.sqlite3.gz"))
    restored = tmp_path / "restored.sqlite3"
    with gzip.open(backup, "rb") as compressed:
        restored.write_bytes(compressed.read())
    restored_connection = sqlite3.connect(restored)
    value = restored_connection.execute("SELECT value FROM values_table").fetchone()[0]
    restored_connection.close()

    assert len(backups) == 2
    assert value == "kept"


def test_scheduler_runs_now_after_missed_schedule():
    timezone = ZoneInfo("Asia/Tokyo")
    now = datetime(2026, 7, 25, 4, 0, tzinfo=timezone)
    assert (
        _seconds_until_due(
            now,
            hour=3,
            minute=15,
            last_success=None,
            last_attempt_mtime=None,
            retry_seconds=7200,
        )
        == 0
    )


def test_scheduler_waits_until_tomorrow_after_success():
    timezone = ZoneInfo("Asia/Tokyo")
    now = datetime(2026, 7, 25, 4, 0, tzinfo=timezone)
    wait = _seconds_until_due(
        now,
        hour=3,
        minute=15,
        last_success="2026-07-25",
        last_attempt_mtime=None,
        retry_seconds=7200,
    )
    assert wait == 23.25 * 60 * 60
