"""Runnable demo: how the BROKER TOKEN gates access and hides the real secret.

Run it (standard library only, no pip install needed):

    python examples/token_demo.py

It starts a tiny local broker on 127.0.0.1, then fires three requests at it so you
can see exactly what happens with and without the token.
"""

from __future__ import annotations

import hmac
import json
import re
import secrets
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- Values that live ONLY inside the broker process ---------------------------------
# The throwaway local token we hand to the agent. It is NOT a real credential.
BROKER_TOKEN = "tok_" + secrets.token_urlsafe(18)
# The real upstream API key. The agent never sees this; it never leaves the broker.
REAL_API_KEY = "sk-REAL-" + secrets.token_hex(8)


def redact(text: str) -> str:
    """Scrub the real secret (and any Bearer token) from anything we return."""
    text = text.replace(REAL_API_KEY, "***REDACTED***")
    # Stop at the closing quote so we don't mangle surrounding JSON.
    return re.sub(r"""Bearer\s+[^\s"']+""", "Bearer ***REDACTED***", text)


def fake_upstream(headers: dict) -> dict:
    """Stand-in for the real API. Echoes what it received so the demo is visible."""
    return {
        "ok": True,
        "models": ["gpt-4", "gpt-4o"],
        "authorization_seen_by_upstream": headers.get("Authorization", ""),
    }


class Broker(BaseHTTPRequestHandler):
    def _reply(self, code: int, obj: dict) -> None:
        body = redact(json.dumps(obj, indent=2)).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        supplied = self.headers.get("X-Broker-Token")
        # Constant-time comparison: no early-exit, so an attacker can't time-guess the token.
        if not supplied or not hmac.compare_digest(supplied, BROKER_TOKEN):
            self._reply(401, {"error": "invalid or missing X-Broker-Token"})
            return
        # Token is valid. Ignore anything the client sent in Authorization and inject the
        # REAL key ourselves, server-side. The agent's own auth header is never used.
        upstream_headers = {"Authorization": f"Bearer {REAL_API_KEY}"}
        self._reply(200, fake_upstream(upstream_headers))

    def log_message(self, *args: object) -> None:  # silence default request logging
        pass


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), Broker)  # port 0 -> OS picks a free port
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    line = "=" * 68
    print(line)
    print("secret-broker . token demo")
    print(line)
    print(f"Broker is listening on         : {base}")
    print(f"Token handed to the AI agent   : {BROKER_TOKEN}")
    print(f"REAL key (stays in broker only): {REAL_API_KEY}")
    print("-" * 68)

    def call(label: str, token: str | None, extra: dict | None = None) -> None:
        req = urllib.request.Request(f"{base}/proxy/openai/v1/models")
        if token is not None:
            req.add_header("X-Broker-Token", token)
        for key, value in (extra or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req) as resp:
                code, body = resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            code, body = exc.code, exc.read().decode("utf-8")
        print(f"\n[{label}]")
        print(f"  -> HTTP {code}")
        for row in body.splitlines():
            print(f"     {row}")

    call("1. No token (what any random caller has)", None)
    call("2. Wrong token", "tok_not-the-real-one")
    call(
        "3. Correct token, and the agent even tries to sneak in its own key",
        BROKER_TOKEN,
        {"Authorization": "Bearer sk-FAKE-from-agent"},
    )

    print("\n" + "-" * 68)
    print("What this shows:")
    print("  - No token / wrong token -> 401. Nothing is reachable without the token.")
    print("  - Correct token -> 200, but the broker injected the REAL key itself;")
    print("    the agent's fake Authorization was ignored, and the key comes back REDACTED.")
    print(line)

    server.shutdown()


if __name__ == "__main__":
    main()
