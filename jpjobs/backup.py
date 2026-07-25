"""Create compressed, transactionally consistent SQLite backups."""

from __future__ import annotations

import argparse
import gzip
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def backup_database(
    database: str | Path,
    output_dir: str | Path,
    *,
    keep: int = 14,
) -> Path:
    source_path = Path(database)
    destination_dir = Path(output_dir)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if keep < 1:
        raise ValueError("keep must be at least 1")

    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final_path = destination_dir / f"jobs-{timestamp}.sqlite3.gz"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".jobs-backup-",
        suffix=".sqlite3",
        dir=destination_dir,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    compressed_temporary = final_path.with_suffix(final_path.suffix + ".tmp")

    try:
        source = sqlite3.connect(
            f"file:{source_path.resolve()}?mode=ro",
            uri=True,
            timeout=30,
        )
        destination = sqlite3.connect(temporary_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

        with (
            temporary_path.open("rb") as raw,
            gzip.open(
                compressed_temporary,
                "wb",
                compresslevel=6,
            ) as compressed,
        ):
            while chunk := raw.read(1024 * 1024):
                compressed.write(chunk)
        compressed_temporary.replace(final_path)
    finally:
        temporary_path.unlink(missing_ok=True)
        compressed_temporary.unlink(missing_ok=True)

    backups = sorted(destination_dir.glob("jobs-*.sqlite3.gz"), reverse=True)
    for stale_backup in backups[keep:]:
        stale_backup.unlink()
    return final_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--keep", type=int, default=14)
    args = parser.parse_args()
    path = backup_database(args.database, args.output_dir, keep=args.keep)
    print(f"[jpjobs] backup={path}")


if __name__ == "__main__":
    main()
