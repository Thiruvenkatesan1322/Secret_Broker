#!/usr/bin/env python3
"""secret-broker (minimal) - a single-file local secrets proxy for AI agents.

The agent gets a localhost endpoint + a throwaway token. It may call ONLY the allow-listed
APIs in SERVICES below; the broker injects your REAL key server-side and scrubs secrets from
every response. Your real keys never reach the agent.

This is the trimmed version: PROXY ONLY - no task runner, no approvals. One file, no
third-party dependencies (uses the Python standard library; `keyring` is optional).

Run:
    # Put your real key where the agent can't read it - an env var or the OS keychain:
    #   PowerShell:  $env:OPENAI_API_KEY = "sk-..."
    #   or keychain: pip install keyring; python -c "import keyring;keyring.set_password('secret-broker','OPENAI_API_KEY','sk-...')"
    python broker_min.py

    # The broker prints a BROKER_TOKEN on startup. The agent calls:
    #   curl http://127.0.0.1:8787/proxy/openai/v1/models -H "X-Broker-Token: <token>"

Edit SERVICES to add your own allow-listed endpoints. Default deny: anything not listed is 403.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

# --- 1) WHAT THE AGENT MAY CALL (default deny; edit me) ------------------------------
SERVICES: dict[str, dict] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",   # Groq's OpenAI-compatible API
        "secret": "GROQ_API_KEY",             # name of the env var / keychain entry
        "auth_header": "Authorization",
        "auth_format": "Bearer {secret}",
        "allow": [                            # (method, exact path regex) pairs
            ("GET", r"models"),
            ("POST", r"chat/completions"),
        ],
    },
    # "openai": {"base_url": "https://api.openai.com", "secret": "OPENAI_API_KEY",
    #   "auth_header": "Authorization", "auth_format": "Bearer {secret}",
    #   "allow": [("GET", r"v1/models"), ("POST", r"v1/chat/completions")]},
    # "github": {"base_url": "https://api.github.com", "secret": "GITHUB_TOKEN",
    #   "auth_header": "Authorization", "auth_format": "Bearer {secret}",
    #   "allow": [("GET", r"repos/[^/]+/[^/]+/issues")]},
}

HOST, PORT = "127.0.0.1", 8787
MAX_BYTES = 5 * 1024 * 1024

# Globals filled in by main().
TOKEN: str = ""
SECRETS: dict[str, str] = {}
REDACT = lambda s: s  # noqa: E731 - replaced in main()


# --- 2) secrets: env var first, then the OS keychain (optional) -----------------------
def load_secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    try:
        import keyring

        return keyring.get_password("secret-broker", name) or None
    except Exception:
        return None


# --- 3) redaction: scrub secret values + common credential shapes ---------------------
_PATTERNS = [
    (re.compile(r"""Bearer\s+[^\s"']+"""), "Bearer ***REDACTED***"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "***REDACTED***"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "***REDACTED***"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), "***REDACTED***"),
]


def make_redactor(values):
    vals = sorted({v for v in values if v and len(v) >= 4}, key=len, reverse=True)

    def redact(text: str) -> str:
        for value in vals:
            text = text.replace(value, "***REDACTED***")
        for pattern, repl in _PATTERNS:
            text = pattern.sub(repl, text)
        return text

    return redact


# --- 4) request safety: block traversal, absolute URLs, SSRF --------------------------
def clean_path(raw: str) -> str | None:
    """Return the safe sub-path (no leading slash), or None if it looks malicious."""
    path = raw.lstrip("/")
    decoded = unquote(unquote(path))
    low = decoded.lower()
    if "://" in low or decoded.startswith("//") or "\\" in decoded or "\x00" in decoded:
        return None
    if any(segment == ".." for segment in decoded.split("/")):
        return None
    return path


def route_allowed(cfg: dict, method: str, path: str) -> bool:
    return any(m == method and re.fullmatch(rx, path) for m, rx in cfg["allow"])


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # never follow redirects (SSRF guard)
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


# --- 5) the server --------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "secret-broker-min"

    def _json(self, code: int, obj: dict) -> None:
        body = REDACT(json.dumps(obj)).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self) -> None:
        parts = urlsplit(self.path)
        if parts.path == "/health":
            return self._json(200, {"status": "ok"})

        supplied = self.headers.get("X-Broker-Token")
        if not supplied or not hmac.compare_digest(supplied, TOKEN):
            return self._json(401, {"error": "invalid or missing X-Broker-Token"})

        segments = parts.path.split("/")  # ['', 'proxy', service, ...sub]
        if len(segments) < 3 or segments[1] != "proxy":
            return self._json(404, {"error": "not found"})
        cfg = SERVICES.get(segments[2])
        if not cfg:
            return self._json(403, {"error": "service not allowed"})

        cleaned = clean_path("/".join(segments[3:]))
        if cleaned is None:
            return self._json(400, {"error": "invalid path"})
        if not route_allowed(cfg, self.command, cleaned):
            return self._json(403, {"error": "endpoint not allowed"})

        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None

        url = f'{cfg["base_url"].rstrip("/")}/{cleaned}'
        if parts.query:
            url += "?" + parts.query
        # The agent's own Authorization is never forwarded; we inject the real key here.
        req = urllib.request.Request(url, data=body, method=self.command)
        req.add_header(cfg["auth_header"], cfg["auth_format"].format(secret=SECRETS[segments[2]]))
        content_type = self.headers.get("Content-Type")
        if content_type:
            req.add_header("Content-Type", content_type)

        try:
            resp = _OPENER.open(req, timeout=30)
            status, data = resp.status, resp.read(MAX_BYTES + 1)
            ctype = resp.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                return self._json(502, {"error": "upstream redirect blocked"})
            status, data = exc.code, exc.read(MAX_BYTES + 1)
            ctype = exc.headers.get("Content-Type", "application/json")
        except Exception:
            return self._json(502, {"error": "upstream request failed"})

        if len(data) > MAX_BYTES:
            return self._json(502, {"error": "upstream response too large"})

        out = REDACT(data.decode("utf-8", "replace")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", REDACT(ctype))
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

    def log_message(self, *args: object) -> None:  # quiet by default
        pass


def main() -> None:
    global TOKEN, SECRETS, REDACT

    TOKEN = load_secret("BROKER_TOKEN") or ""
    generated = not TOKEN
    if generated:
        TOKEN = "tok_" + secrets.token_urlsafe(24)

    missing: list[str] = []
    for name, cfg in SERVICES.items():
        value = load_secret(cfg["secret"])
        if not value:
            missing.append(cfg["secret"])
        else:
            SECRETS[name] = value
    if missing:
        print(
            f"ERROR: missing secret(s): {sorted(set(missing))}. "
            "Set them as env vars or in the OS keychain (service 'secret-broker').",
            file=sys.stderr,
        )
        sys.exit(1)

    REDACT = make_redactor(list(SECRETS.values()) + [TOKEN])

    print(f"secret-broker (minimal) listening on http://{HOST}:{PORT}")
    print(f"allow-listed services: {', '.join(SERVICES)}")
    if generated:
        print(f"BROKER_TOKEN (give this to the agent): {TOKEN}")
    else:
        print("BROKER_TOKEN: loaded from env/keychain")
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
