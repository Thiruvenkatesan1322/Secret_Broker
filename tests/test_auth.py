"""Auth: unauthorized/missing/wrong tokens are rejected; admin token not usable on agent API."""

from __future__ import annotations

from tests.conftest import admin_headers, agent_headers


def test_missing_token_rejected(broker):
    assert broker.agent.get("/tasks").status_code == 401
    assert broker.agent.post("/tasks/echo_ok", json={"args": {"message": "x"}}).status_code == 401
    assert broker.agent.get("/proxy/openai/v1/models").status_code == 401


def test_wrong_token_rejected(broker):
    resp = broker.agent.get("/tasks", headers={"x-broker-token": "nope"})
    assert resp.status_code == 401


def test_correct_token_accepted(broker):
    resp = broker.agent.get("/tasks", headers=agent_headers())
    assert resp.status_code == 200
    assert "tasks" in resp.json()


def test_health_is_open(broker):
    assert broker.agent.get("/health").status_code == 200
    assert broker.admin.get("/health").status_code == 200


def test_admin_requires_admin_token(broker):
    assert broker.admin.get("/requests").status_code == 401
    # The agent token must NOT be accepted on the admin API.
    assert broker.admin.get("/requests", headers={"x-admin-token": broker.broker_token}).status_code == 401
    assert broker.admin.get("/requests", headers=admin_headers()).status_code == 200
