"""Shared pytest fixtures: a hermetic broker wired to a mock upstream via httpx.MockTransport."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from broker.app import create_agent_app, create_admin_app
from broker.config import Settings
from broker.state import build_state

BROKER_TOKEN = "test-broker-token-xyz-123456"
ADMIN_TOKEN = "test-admin-token-abc-654321"
# Deliberately not sk-/AKIA/JWT shaped, so redaction here must rely on literal value match.
REAL_SECRET = "REALSECRET-supersecret-value-0001"

PY = sys.executable

_POLICY = {
    "services": {
        "openai": {
            "base_url": "https://api.openai.test",
            "auth": {
                "header": "Authorization",
                "format": "Bearer {secret}",
                "secret": "OPENAI_API_KEY",
            },
            "rate_limit_per_minute": 3,
            "forward_headers": ["content-type", "accept"],
            "routes": [
                {"methods": ["GET", "POST"], "path": "^v1/models$"},
                {"methods": ["GET"], "path": "^v1/redirect$"},
            ],
        }
    }
}

_TASKS = {
    "tasks": {
        "echo_ok": {
            "command": [PY, "-c", "import sys;print('hello ' + sys.argv[1])", "{message}"],
            "cwd": ".",
            "timeout": 30,
            "auto_approve": True,
            "args": {"message": {"type": "string", "regex": r"^[A-Za-z0-9 _.-]{1,50}$"}},
        },
        "needs_approval": {
            "command": [PY, "-c", "print('approved task ran')"],
            "cwd": ".",
            "timeout": 30,
            "auto_approve": False,
        },
        "deploy": {
            "command": [PY, "-c", "import sys;print('deploy ' + sys.argv[1])", "{target}"],
            "cwd": ".",
            "timeout": 30,
            "auto_approve": False,
            "args": {"target": {"type": "enum", "choices": ["staging", "preview"]}},
        },
    }
}


def _upstream(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/v1/models":
        return httpx.Response(
            200,
            json={
                "path": path,
                "auth_seen": request.headers.get("authorization", ""),
                "leak": REAL_SECRET,
                "models": ["gpt-x"],
            },
        )
    if path == "/v1/redirect":
        return httpx.Response(302, headers={"location": "https://evil.example/pwned"})
    return httpx.Response(404, json={"error": "not found", "path": path})


@pytest.fixture
def broker(tmp_path: Path):
    policy_path = tmp_path / "policy.yaml"
    tasks_path = tmp_path / "tasks.yaml"
    audit_path = tmp_path / "audit.jsonl"
    secrets_dir = tmp_path / "secrets"
    workspace = tmp_path / "workspace"
    secrets_dir.mkdir()
    workspace.mkdir()
    (secrets_dir / "OPENAI_API_KEY").write_text(REAL_SECRET, encoding="utf-8")

    with policy_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(_POLICY, handle)
    with tasks_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(_TASKS, handle)

    settings = Settings(
        broker_token=BROKER_TOKEN,
        admin_token=ADMIN_TOKEN,
        policy_path=policy_path,
        tasks_path=tasks_path,
        audit_path=audit_path,
        secrets_dir=secrets_dir,
        workspace_dir=workspace,
    )
    state = build_state(settings)
    # Swap the real upstream client for a deterministic mock.
    state.http = httpx.AsyncClient(
        transport=httpx.MockTransport(_upstream), follow_redirects=False
    )

    agent = TestClient(create_agent_app(state))
    admin = TestClient(create_admin_app(state))
    return SimpleNamespace(
        agent=agent,
        admin=admin,
        state=state,
        secret=REAL_SECRET,
        audit_path=audit_path,
        broker_token=BROKER_TOKEN,
        admin_token=ADMIN_TOKEN,
    )


def agent_headers() -> dict:
    return {"x-broker-token": BROKER_TOKEN}


def admin_headers() -> dict:
    return {"x-admin-token": ADMIN_TOKEN}
