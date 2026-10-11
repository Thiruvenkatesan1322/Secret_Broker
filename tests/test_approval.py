"""Approval: unapproved tasks never run; approval only works via the admin channel."""

from __future__ import annotations

from tests.conftest import admin_headers, agent_headers


def _submit_needs_approval(broker) -> str:
    resp = broker.agent.post("/tasks/needs_approval", json={}, headers=agent_headers())
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    return body["request_id"]


def test_unapproved_task_never_executes(broker):
    request_id = _submit_needs_approval(broker)
    detail = broker.agent.get(
        f"/tasks/requests/{request_id}", headers=agent_headers()
    ).json()
    assert detail["status"] == "pending"
    assert detail["stdout"] == ""
    assert detail["exit_code"] is None


def test_agent_api_has_no_approval_endpoint(broker):
    request_id = _submit_needs_approval(broker)
    # No such route exists on the agent app.
    resp = broker.agent.post(
        f"/tasks/requests/{request_id}/approve", headers=agent_headers()
    )
    assert resp.status_code == 404
    resp2 = broker.agent.post(f"/requests/{request_id}/approve", headers=agent_headers())
    assert resp2.status_code == 404


def test_approval_only_via_admin_channel(broker):
    request_id = _submit_needs_approval(broker)
    # Admin endpoint rejects the agent token.
    denied = broker.admin.post(
        f"/requests/{request_id}/approve", headers={"x-admin-token": broker.broker_token}
    )
    assert denied.status_code == 401
    # Still pending after the rejected attempt.
    assert broker.agent.get(
        f"/tasks/requests/{request_id}", headers=agent_headers()
    ).json()["status"] == "pending"


def test_admin_approve_runs_task(broker):
    request_id = _submit_needs_approval(broker)
    resp = broker.admin.post(f"/requests/{request_id}/approve", headers=admin_headers())
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    detail = broker.agent.get(
        f"/tasks/requests/{request_id}", headers=agent_headers()
    ).json()
    assert detail["status"] == "success"
    assert "approved task ran" in detail["stdout"]


def test_deny_then_approve_conflicts(broker):
    request_id = _submit_needs_approval(broker)
    denied = broker.admin.post(f"/requests/{request_id}/deny", headers=admin_headers())
    assert denied.status_code == 200
    assert denied.json()["status"] == "denied"

    # Approving after a decision must fail (no double-decision).
    conflict = broker.admin.post(f"/requests/{request_id}/approve", headers=admin_headers())
    assert conflict.status_code == 409


def test_show_exposes_resolved_command_to_admin(broker):
    resp = broker.agent.post(
        "/tasks/deploy", json={"args": {"target": "staging"}}, headers=agent_headers()
    )
    request_id = resp.json()["request_id"]
    detail = broker.admin.get(f"/requests/{request_id}", headers=admin_headers()).json()
    assert detail["args"] == {"target": "staging"}
    assert "command" in detail and isinstance(detail["command"], list)
