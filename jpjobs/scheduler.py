"""Small non-privileged daily scheduler for the Docker deployment."""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")


def _marker_date(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return value or None


def _seconds_until_due(
    now: datetime,
    *,
    hour: int,
    minute: int,
    last_success: str | None,
    last_attempt_mtime: float | None,
    retry_seconds: int,
) -> float:
    today = now.date().isoformat()
    scheduled_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled_today:
        return (scheduled_today - now).total_seconds()
    if last_success == today:
        return (scheduled_today + timedelta(days=1) - now).total_seconds()
    if last_attempt_mtime is not None:
        elapsed = time.time() - last_attempt_mtime
        if elapsed < retry_seconds:
            return retry_seconds - elapsed
    return 0


def main() -> None:
    data_dir = Path(os.environ.get("JPJOBS_DATA_DIR", "/data"))
    state_dir = data_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    last_success_path = state_dir / "last-success"
    last_attempt_path = state_dir / "last-attempt"
    hour = int(os.environ.get("JPJOBS_SCHEDULE_HOUR", "3"))
    minute = int(os.environ.get("JPJOBS_SCHEDULE_MINUTE", "15"))
    retry_seconds = int(os.environ.get("JPJOBS_RETRY_SECONDS", "7200"))
    runner = os.environ.get("JPJOBS_RUNNER", "/app/deploy/run-daily.sh")

    print(
        f"[jpjobs] scheduler started schedule={hour:02d}:{minute:02d} "
        "timezone=Asia/Tokyo",
        flush=True,
    )
    while True:
        now = datetime.now(JST)
        try:
            attempt_mtime = last_attempt_path.stat().st_mtime
        except FileNotFoundError:
            attempt_mtime = None
        wait_seconds = _seconds_until_due(
            now,
            hour=hour,
            minute=minute,
            last_success=_marker_date(last_success_path),
            last_attempt_mtime=attempt_mtime,
            retry_seconds=retry_seconds,
        )
        if wait_seconds > 0:
            next_run = now + timedelta(seconds=wait_seconds)
            print(
                f"[jpjobs] next scheduled run={next_run.isoformat()}",
                flush=True,
            )
            time.sleep(wait_seconds)
            continue

        print(f"[jpjobs] starting daily sync at {now.isoformat()}", flush=True)
        completed = subprocess.run([runner], check=False)
        print(
            f"[jpjobs] daily sync exit_code={completed.returncode}",
            flush=True,
        )
        if completed.returncode == 0:
            time.sleep(60)
        else:
            time.sleep(min(300, retry_seconds))


if __name__ == "__main__":
    main()
