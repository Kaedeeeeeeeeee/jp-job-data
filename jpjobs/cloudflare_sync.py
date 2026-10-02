"""Push an idempotent, signed SQLite delta to KIKKAKE Cloudflare Workers."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import httpx

from jpjobs.storage import JobStore


SCHEMA_VERSION = 1
CHUNK_SIZE = 200


def canonical_json(value: Any) -> str:
    """Match the Worker's recursive stableStringify implementation."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _sentence_with(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    start = max(
        text.rfind(".", 0, match.start()),
        text.rfind("。", 0, match.start()),
        text.rfind("\n", 0, match.start()),
    )
    end_candidates = [
        position
        for position in (
            text.find(".", match.end()),
            text.find("。", match.end()),
            text.find("\n", match.end()),
        )
        if position >= 0
    ]
    end = (
        min(end_candidates) + 1 if end_candidates else min(len(text), match.end() + 160)
    )
    return " ".join(text[start + 1 : end].split())[:500]


def extract_explicit_signals(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract only literal, defensible signals; absence remains Unknown."""
    text = " ".join(
        str(payload.get(key) or "")
        for key in ("title", "description", "description_snippet")
    )
    rules = [
        (
            "visa",
            "possible_support",
            r"\bvisa sponsorship\b|ビザ(?:サポート|支援)|就労ビザ",
            0.92,
        ),
        (
            "overseas",
            "supported",
            r"overseas applicants?|apply from overseas|海外(?:在住|応募)",
            0.94,
        ),
        (
            "language",
            "n1_required",
            r"(?:JLPT\s*)?N1\s+(?:is\s+)?required|日本語能力試験\s*N1",
            0.98,
        ),
        (
            "language",
            "n2_required",
            r"(?:JLPT\s*)?N2\s+(?:is\s+)?required|日本語能力試験\s*N2",
            0.98,
        ),
        (
            "remote",
            "available",
            r"\bfully remote\b|\bremote work (?:is )?available\b|フルリモート",
            0.93,
        ),
    ]
    signals = []
    for kind, value, pattern, confidence in rules:
        evidence = _sentence_with(text, pattern)
        if evidence:
            signals.append(
                {
                    "kind": kind,
                    "value": value,
                    "confidence": confidence,
                    "evidence": evidence,
                    "extractorVersion": "jpjobs-rules-v1",
                }
            )
    return signals


def _job_from_row(row: sqlite3.Row) -> tuple[dict[str, Any], str]:
    payload = json.loads(row["payload_json"])
    source = str(payload.get("source") or "")
    source_id = str(payload.get("source_id") or "")
    source_urls = dict(payload.get("source_urls") or {})
    source_ids = {
        str(key): str(value)
        for key, value in dict(payload.get("source_ids") or {}).items()
    }
    if source and source_id:
        source_ids.setdefault(source, source_id)
    url = str(payload.get("url") or source_urls.get(source) or "")
    if source and url:
        source_urls.setdefault(source, url)
    wage = dict(payload.get("wage") or {})
    languages = payload.get("language") or payload.get("languages") or []
    company = str(payload.get("company") or row["company"] or "").strip()
    quality_flags = [str(value) for value in payload.get("quality_flags") or []]
    if not company:
        company = "Unknown company"
        if "missing_company" not in quality_flags:
            quality_flags.append("missing_company")
    job = {
        "id": str(row["id"]),
        "source": source,
        "sourceId": source_id,
        "url": url,
        "title": str(payload.get("title") or row["title"] or ""),
        "company": company,
        "description": str(payload.get("description") or ""),
        "descriptionSnippet": str(payload.get("description_snippet") or "")[:2000],
        "workplace": str(payload.get("workplace") or ""),
        "prefecture": payload.get("prefecture") or row["prefecture"],
        "prefectureName": payload.get("prefecture_name"),
        "city": payload.get("city"),
        "remote": payload.get("remote"),
        "wage": {
            "min": wage.get("min"),
            "max": wage.get("max"),
            "unit": wage.get("unit"),
            "raw": str(wage.get("raw") or ""),
        },
        "employmentType": payload.get("employment_type"),
        "datePosted": payload.get("date_posted") or row["date_posted"],
        "languages": [str(value) for value in languages],
        "sourceUrls": source_urls,
        "sourceIds": source_ids,
        "qualityFlags": quality_flags,
        "status": str(row["status"] or "active"),
        "firstSeenAt": str(row["first_seen_at"]),
        "lastSeenAt": str(row["last_seen_at"]),
        "lastCheckedAt": row["last_checked_at"],
        "withdrawnAt": row["withdrawn_at"],
        "expiredAt": row["expired_at"],
        "removalReason": row["removal_reason"],
        "signals": extract_explicit_signals(payload),
    }
    return job, sha256(canonical_json(job).encode("utf-8"))


def read_snapshot(database: Path) -> dict[str, Any]:
    """Read the current authority snapshot after applying forward migrations."""
    with JobStore(database):
        pass
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        run = connection.execute(
            """
            SELECT scanned_at, window_start, window_end, raw_total,
                   total_kept, filtered_out, duplicates_merged
            FROM runs ORDER BY scanned_at DESC LIMIT 1
            """
        ).fetchone()
        if not run:
            raise RuntimeError("The crawler database has no completed scan")
        rows = connection.execute(
            """
            SELECT id, title, company, prefecture, date_posted,
                   first_seen_at, last_seen_at, status, last_checked_at,
                   withdrawn_at, expired_at, removal_reason, payload_json
            FROM jobs ORDER BY id
            """
        ).fetchall()
        jobs_and_hashes = [_job_from_row(row) for row in rows]
        source_rows = connection.execute(
            """
            SELECT source, status, discovery_status, coverage_complete,
                   total, kept, pages_fetched, reconciliation_applied,
                   reconciliation_skip_reason
            FROM source_runs WHERE scanned_at = ? ORDER BY source
            """,
            (run["scanned_at"],),
        ).fetchall()
    finally:
        connection.close()
    jobs = [value[0] for value in jobs_and_hashes]
    hashes = {job["id"]: value[1] for job, value in zip(jobs, jobs_and_hashes)}
    manifest_checksum = sha256(canonical_json(hashes).encode("utf-8"))
    return {
        "jobs": jobs,
        "hashes": hashes,
        "run": {
            "scannedAt": str(run["scanned_at"]),
            "windowStart": run["window_start"],
            "windowEnd": run["window_end"],
            "rawTotal": int(run["raw_total"]),
            "totalKept": int(run["total_kept"]),
            "filteredOut": int(run["filtered_out"]),
            "duplicatesMerged": int(run["duplicates_merged"]),
            "manifestChecksum": manifest_checksum,
        },
        "sourceHealth": [
            {
                "source": str(row["source"]),
                "status": str(row["status"]),
                "discoveryStatus": str(row["discovery_status"] or row["status"]),
                "coverageComplete": (
                    None
                    if row["coverage_complete"] is None
                    else bool(row["coverage_complete"])
                ),
                "total": int(row["total"]),
                "kept": int(row["kept"]),
                "pagesFetched": int(row["pages_fetched"]),
                "reconciliationApplied": bool(row["reconciliation_applied"]),
                "reconciliationSkipReason": row["reconciliation_skip_reason"],
            }
            for row in source_rows
        ],
    }


def _batches(values: list[Any], size: int) -> Iterable[list[Any]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def create_outbox_run(
    snapshot: dict[str, Any],
    state: dict[str, Any],
    outbox: Path,
) -> Path:
    previous_hashes = dict(state.get("hashes") or {})
    changed = [
        job
        for job in snapshot["jobs"]
        if previous_hashes.get(job["id"]) != snapshot["hashes"][job["id"]]
    ]
    manifest = snapshot["run"]["manifestChecksum"]
    scanned = re.sub(r"[^0-9A-Za-z]+", "-", snapshot["run"]["scannedAt"]).strip("-")
    run_id = f"jpjobs-{scanned}-{manifest[:12]}"
    run_dir = outbox / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    chunks = list(_batches(changed, CHUNK_SIZE)) or [[]]
    for index, jobs in enumerate(chunks):
        envelope = {
            "jobs": jobs,
            "run": snapshot["run"] if index == 0 else None,
            "sourceHealth": snapshot["sourceHealth"] if index == 0 else [],
        }
        chunk = {
            "schemaVersion": SCHEMA_VERSION,
            "runId": run_id,
            "chunkIndex": index,
            "chunkCount": len(chunks),
            "checksum": sha256(canonical_json(envelope).encode("utf-8")),
            **envelope,
        }
        target = run_dir / f"{index:06d}.json.gz"
        if not target.exists():
            target.write_bytes(
                gzip.compress(
                    canonical_json(chunk).encode("utf-8"),
                    compresslevel=6,
                    mtime=0,
                )
            )
            os.chmod(target, 0o600)
    _atomic_json(
        run_dir / "state.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "runId": run_id,
            "scannedAt": snapshot["run"]["scannedAt"],
            "manifestChecksum": manifest,
            "hashes": snapshot["hashes"],
            "jobCount": len(snapshot["jobs"]),
            "changedCount": len(changed),
            "chunkCount": len(chunks),
        },
    )
    return run_dir


def send_outbox_run(
    run_dir: Path,
    endpoint: str,
    secret: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    run_id = str(state["runId"])
    last_response: dict[str, Any] = {}
    with httpx.Client(timeout=timeout) as client:
        for chunk_path in sorted(run_dir.glob("*.json.gz")):
            body = chunk_path.read_bytes()
            timestamp = str(int(time.time()))
            body_digest = sha256(body)
            signed = f"{timestamp}.{body_digest}".encode("utf-8")
            signature = hmac.new(
                secret.encode("utf-8"), signed, hashlib.sha256
            ).hexdigest()
            response = client.post(
                f"{endpoint.rstrip('/')}/internal/ingest/runs/{run_id}/chunks",
                content=body,
                headers={
                    "content-type": "application/json",
                    "content-encoding": "gzip",
                    "x-kikkake-timestamp": timestamp,
                    "x-kikkake-signature": signature,
                },
            )
            response.raise_for_status()
            last_response = response.json()
    if not last_response.get("complete"):
        raise RuntimeError(f"Ingest run {run_id} was not acknowledged as complete")
    return state


def sync(
    database: Path,
    endpoint: str,
    secret: str,
    state_path: Path,
    outbox: Path,
) -> dict[str, Any]:
    if len(secret) < 32:
        raise ValueError("KIKKAKE_INGEST_SECRET must be at least 32 characters")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    outbox.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))

    for pending in sorted(path for path in outbox.iterdir() if path.is_dir()):
        completed = send_outbox_run(pending, endpoint, secret)
        _atomic_json(state_path, completed)
        state = completed
        for child in pending.iterdir():
            child.unlink()
        pending.rmdir()

    snapshot = read_snapshot(database)
    if (
        state.get("scannedAt") == snapshot["run"]["scannedAt"]
        and state.get("manifestChecksum") == snapshot["run"]["manifestChecksum"]
    ):
        return state
    run_dir = create_outbox_run(snapshot, state, outbox)
    completed = send_outbox_run(run_dir, endpoint, secret)
    _atomic_json(state_path, completed)
    for child in run_dir.iterdir():
        child.unlink()
    run_dir.rmdir()
    return completed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--endpoint", default=os.getenv("KIKKAKE_INGEST_URL", ""))
    parser.add_argument("--secret", default=os.getenv("KIKKAKE_INGEST_SECRET", ""))
    parser.add_argument("--state", type=Path)
    parser.add_argument("--outbox", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = args.database.parent
    state = args.state or data_dir / "state" / "kikkake-sync.json"
    outbox = args.outbox or data_dir / "outbox" / "kikkake"
    if not args.endpoint or not args.secret:
        print("KIKKAKE ingest endpoint or secret is not configured", file=sys.stderr)
        return 2
    result = sync(args.database, args.endpoint, args.secret, state, outbox)
    print(
        json.dumps(
            {
                "runId": result["runId"],
                "jobCount": result["jobCount"],
                "changedCount": result["changedCount"],
                "chunkCount": result["chunkCount"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
