"""Append-only JSONL audit log. Every line is redacted before it is written."""

from __future__ import annotations

import datetime
import json
import threading
from pathlib import Path

from .redaction import Redactor


class AuditLog:
    def __init__(self, path: Path, redactor: Redactor) -> None:
        self._path = Path(path)
        self._redactor = redactor
        self._lock = threading.Lock()
        parent = self._path.parent
        if parent and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)

    def record(self, **event: object) -> None:
        entry = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            **event,
        }
        safe = self._redactor.redact_obj(entry)
        line = json.dumps(safe, ensure_ascii=False, sort_keys=True, default=str)
        # Belt and suspenders: redact the serialized line too.
        line = self._redactor.redact(line)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
