"""Redaction of secret values and common credential patterns from any outbound text.

Applied to every proxy response body/headers, every task stdout/stderr, and every
audit log line before it leaves the process or is written to disk.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

PLACEHOLDER = "***REDACTED***"

# Pattern-based redaction for well-known credential shapes. Order matters: the
# Authorization-line rule is greedy to end-of-line so it also swallows a Bearer token.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]+"), f"Bearer {PLACEHOLDER}"),
    (re.compile(r"(?im)^(.*authorization\s*[:=]\s*).+$"), r"\1" + PLACEHOLDER),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), PLACEHOLDER),           # OpenAI / Stripe style
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), PLACEHOLDER),             # AWS access key id
    (re.compile(r"\bASIA[0-9A-Z]{16}\b"), PLACEHOLDER),             # AWS temporary key id
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), PLACEHOLDER),           # GitHub PAT
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), PLACEHOLDER),   # Slack token
    (re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), PLACEHOLDER),  # JWT
]


class Redactor:
    """Scrubs literal secret values first, then known credential patterns."""

    def __init__(self, secret_values: Iterable[str] = ()) -> None:
        # Only redact values long enough to be a real secret, longest first so that
        # overlapping values do not leave fragments behind.
        vals = {v for v in secret_values if isinstance(v, str) and len(v) >= 4}
        self._values: list[str] = sorted(vals, key=len, reverse=True)

    def redact(self, text: str | None) -> str:
        if not text:
            return text or ""
        for value in self._values:
            if value:
                text = text.replace(value, PLACEHOLDER)
        for pattern, repl in _PATTERNS:
            text = pattern.sub(repl, text)
        return text

    def redact_obj(self, obj: Any) -> Any:
        """Recursively redact strings inside dicts/lists (used for audit events)."""
        if isinstance(obj, str):
            return self.redact(obj)
        if isinstance(obj, dict):
            return {k: self.redact_obj(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self.redact_obj(v) for v in obj]
        return obj
