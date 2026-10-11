"""Low-level security primitives: constant-time compare, header filtering, path cleaning."""

from __future__ import annotations

import hmac
import urllib.parse

from .errors import SecurityError

# Headers we never forward to an upstream, regardless of allowlist. Covers client-supplied
# credentials and hop-by-hop headers.
STRIP_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-broker-token",
        "x-admin-token",
        "host",
        "content-length",
        "connection",
        "keep-alive",
        "proxy-connection",
        "transfer-encoding",
        "te",
        "trailer",
        "upgrade",
    }
)


def constant_time_compare(supplied: str | None, expected: str | None) -> bool:
    """Timing-safe string comparison. Returns False on any error or None input."""
    if not supplied or not expected:
        return False
    try:
        return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
    except (UnicodeError, TypeError):
        return False


def clean_proxy_path(raw: str) -> str:
    """Validate and normalise a proxy sub-path. Fails closed on anything suspicious.

    Returns the path with any leading slash removed, still percent-encoded as received
    (so query-safe characters survive), after rejecting absolute URLs, traversal, and
    control characters. Raises SecurityError when the path is not safe.
    """
    path = raw or ""
    while path.startswith("/"):
        path = path[1:]

    # Decode twice to catch single and double percent-encoded traversal attempts.
    decoded = path
    for _ in range(2):
        decoded = urllib.parse.unquote(decoded)

    lowered = decoded.lower()
    if "://" in lowered or decoded.startswith("//"):
        raise SecurityError("absolute URLs are not allowed")
    if "\\" in decoded or "\x00" in decoded:
        raise SecurityError("illegal characters in path")
    if any(ord(ch) < 0x20 for ch in decoded):
        raise SecurityError("control characters in path")
    for segment in decoded.split("/"):
        if segment == "..":
            raise SecurityError("path traversal is not allowed")
    return path


def build_forward_headers(incoming: dict[str, str], allowed: list[str]) -> dict[str, str]:
    """Default-deny header filter: forward only allow-listed, non-stripped headers."""
    allow = {h.lower() for h in allowed}
    out: dict[str, str] = {}
    for key, value in incoming.items():
        low = key.lower()
        if low in STRIP_HEADERS:
            continue
        if low in allow:
            out[key] = value
    return out
