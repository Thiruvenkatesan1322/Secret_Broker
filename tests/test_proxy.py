"""Proxy: allowlist enforcement, SSRF/traversal guards, header stripping, redirect blocking."""

from __future__ import annotations

from tests.conftest import agent_headers


def test_allowed_endpoint_ok(broker):
    resp = broker.agent.get("/proxy/openai/v1/models", headers=agent_headers())
    assert resp.status_code == 200
    assert resp.json()["path"] == "/v1/models"


def test_unlisted_endpoint_forbidden(broker):
    resp = broker.agent.get("/proxy/openai/v1/secret-admin", headers=agent_headers())
    assert resp.status_code == 403


def test_unknown_service_forbidden(broker):
    resp = broker.agent.get("/proxy/unknown/v1/models", headers=agent_headers())
    assert resp.status_code == 403


def test_method_not_allowed_is_denied(broker):
    # DELETE is not in the allowlist for v1/models.
    resp = broker.agent.request("DELETE", "/proxy/openai/v1/models", headers=agent_headers())
    assert resp.status_code == 403


def test_path_traversal_blocked(broker):
    resp = broker.agent.get("/proxy/openai/..%2f..%2fetc%2fpasswd", headers=agent_headers())
    assert resp.status_code in (400, 403)


def test_absolute_url_blocked(broker):
    resp = broker.agent.get("/proxy/openai/http://evil.example/x", headers=agent_headers())
    assert resp.status_code in (400, 403)


def test_client_authorization_header_stripped(broker):
    resp = broker.agent.get(
        "/proxy/openai/v1/models",
        headers={**agent_headers(), "authorization": "Bearer CLIENTFAKE123456"},
    )
    assert resp.status_code == 200
    # The client's fake token never reaches the upstream; the real one is redacted.
    assert "CLIENTFAKE123456" not in resp.text
    assert broker.secret not in resp.text


def test_redirect_blocked(broker):
    resp = broker.agent.get("/proxy/openai/v1/redirect", headers=agent_headers())
    assert resp.status_code == 502
    assert "evil.example" not in resp.text
