"""Tasks: auto-approve runs; unknown tasks and invalid/arbitrary args are rejected."""

from __future__ import annotations

from tests.conftest import agent_headers


def test_auto_approve_task_runs(broker):
    resp = broker.agent.post(
        "/tasks/echo_ok", json={"args": {"message": "world"}}, headers=agent_headers()
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "success"

    detail = broker.agent.get(
        f"/tasks/requests/{body['request_id']}", headers=agent_headers()
    ).json()
    assert detail["status"] == "success"
    assert "hello world" in detail["stdout"]


def test_unknown_task_rejected(broker):
    resp = broker.agent.post("/tasks/not_a_task", json={}, headers=agent_headers())
    assert resp.status_code == 404


def test_invalid_arg_rejected(broker):
    # Contains characters disallowed by the regex (shell metacharacters).
    resp = broker.agent.post(
        "/tasks/echo_ok", json={"args": {"message": "boom; rm -rf /"}}, headers=agent_headers()
    )
    assert resp.status_code == 400


def test_unknown_arg_rejected(broker):
    resp = broker.agent.post(
        "/tasks/echo_ok", json={"args": {"evil": "x"}}, headers=agent_headers()
    )
    assert resp.status_code == 400


def test_arbitrary_command_cannot_be_injected(broker):
    # enum rejects anything outside the fixed choices - no arbitrary command is possible.
    resp = broker.agent.post(
        "/tasks/deploy", json={"args": {"target": "staging; curl evil"}}, headers=agent_headers()
    )
    assert resp.status_code == 400


def test_missing_required_arg_rejected(broker):
    resp = broker.agent.post("/tasks/echo_ok", json={"args": {}}, headers=agent_headers())
    assert resp.status_code == 400
