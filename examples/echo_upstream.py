"""Tiny local upstream for trying the broker without real APIs or secrets.

Echoes the method, path, headers, and body it received as JSON, so you can see
exactly what the broker forwarded (and what it stripped/injected). Run:

    python examples/echo_upstream.py      # listens on 127.0.0.1:9999
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def _echo(self) -> None:
        length = int(self.headers.get("content-length", 0) or 0)
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        payload = {
            "upstream_received": {
                "method": self.command,
                "path": self.path,
                "headers": {k: v for k, v in self.headers.items()},
                "body": body,
            }
        }
        data = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = _echo
    do_POST = _echo

    def log_message(self, *args: object) -> None:  # keep the demo output quiet
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 9999), Handler).serve_forever()
