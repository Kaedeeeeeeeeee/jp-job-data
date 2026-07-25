"""Persistent page checkpoints for resumable automatic pagination."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


CHECKPOINT_VERSION = 1


def _fingerprint(parameters: dict[str, Any]) -> str:
    encoded = json.dumps(
        parameters,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class PageCheckpoint:
    """Track the last durable page for each source/query combination."""

    def __init__(self, path: str | Path, *, parameters: dict[str, Any]):
        self.path = Path(path)
        self.parameters = parameters
        self.fingerprint = _fingerprint(parameters)
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "version": CHECKPOINT_VERSION,
                "fingerprint": self.fingerprint,
                "parameters": self.parameters,
                "entries": {},
            }
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read checkpoint {self.path}: {exc}") from exc
        if data.get("version") != CHECKPOINT_VERSION:
            raise ValueError(
                f"unsupported checkpoint version in {self.path}: "
                f"{data.get('version')!r}"
            )
        if data.get("fingerprint") != self.fingerprint:
            raise ValueError(
                "checkpoint parameters do not match this scan; use a different "
                "checkpoint path or the same filters and --as-of date"
            )
        data.setdefault("entries", {})
        return data

    @staticmethod
    def _key(
        source: str,
        keyword: str,
        context: dict[str, Any] | None,
    ) -> str:
        return json.dumps(
            {
                "source": source,
                "keyword": keyword,
                "context": context or {},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    def entry(
        self,
        source: str,
        keyword: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return self.data["entries"].get(self._key(source, keyword, context))

    def resume_state(
        self,
        source: str,
        keyword: str = "",
        context: dict[str, Any] | None = None,
    ) -> tuple[int, bool]:
        entry = self.entry(source, keyword, context)
        if not entry:
            return 1, False
        return int(entry.get("last_page") or 0) + 1, bool(entry.get("complete"))

    def record(
        self,
        *,
        source: str,
        keyword: str,
        context: dict[str, Any] | None,
        page: int,
        reason: str | None,
        coverage_complete: bool | None,
    ) -> None:
        key = self._key(source, keyword, context)
        existing = self.data["entries"].get(key) or {}
        existing_page = int(existing.get("last_page") or 0)
        if page < existing_page or existing.get("complete") is True:
            return
        self.data["entries"][key] = {
            "source": source,
            "keyword": keyword,
            "context": context or {},
            "last_page": page,
            "next_page": page + 1,
            "complete": coverage_complete is True,
            "stop_reason": reason,
        }
        self._write()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
