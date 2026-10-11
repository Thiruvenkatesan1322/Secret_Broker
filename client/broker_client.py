"""Tiny agent-side helper for talking to the broker.

The agent only ever holds BROKER_TOKEN (a throwaway local token). This client has
NO ability to approve tasks or read secrets - approvals happen out-of-band in a
human's terminal via `broker-approve`.
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx

TERMINAL_STATES = {"success", "failed", "denied", "error"}


class BrokerClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url or os.environ.get("BROKER_URL", "http://127.0.0.1:8787")
        token = token or os.environ.get("BROKER_TOKEN")
        if not token:
            raise RuntimeError("BROKER_TOKEN is not set; the agent cannot call the broker")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"x-broker-token": token},
            timeout=timeout,
        )

    def proxy(
        self, service: str, path: str, method: str = "GET", **kwargs: Any
    ) -> httpx.Response:
        """Call an allow-listed upstream endpoint. Never pass Authorization yourself."""
        return self._client.request(
            method, f"/proxy/{service}/{path.lstrip('/')}", **kwargs
        )

    def run_task(self, name: str, args: Optional[dict] = None) -> dict:
        """Submit a named task. Returns {request_id, status}. May be 'pending'."""
        response = self._client.post(f"/tasks/{name}", json={"args": args or {}})
        response.raise_for_status()
        return response.json()

    def get_request(self, request_id: str) -> dict:
        response = self._client.get(f"/tasks/requests/{request_id}")
        response.raise_for_status()
        return response.json()

    def wait(self, request_id: str, timeout: float = 120.0, interval: float = 1.0) -> dict:
        """Poll a request until it reaches a terminal state or the timeout elapses."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = self.get_request(request_id)
            if data["status"] in TERMINAL_STATES:
                return data
            time.sleep(interval)
        raise TimeoutError(f"request {request_id} did not finish within {timeout}s")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BrokerClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
