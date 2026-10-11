"""Redaction: unit coverage of patterns + integration that upstream secrets are scrubbed."""

from __future__ import annotations

from broker.redaction import PLACEHOLDER, Redactor
from tests.conftest import agent_headers


def test_literal_secret_value_redacted():
    r = Redactor(["REALSECRET-supersecret-value-0001"])
    out = r.redact("prefix REALSECRET-supersecret-value-0001 suffix")
    assert "REALSECRET-supersecret-value-0001" not in out
    assert PLACEHOLDER in out


def test_bearer_token_redacted():
    r = Redactor()
    assert "abcdef123456" not in r.redact("Bearer abcdef123456")


def test_authorization_header_redacted():
    r = Redactor()
    out = r.redact("Authorization: Bearer abcdef123456")
    assert "abcdef123456" not in out


def test_openai_key_redacted():
    r = Redactor()
    assert "sk-ABCDEF0123456789" not in r.redact("key sk-ABCDEF0123456789 end")


def test_aws_key_redacted():
    r = Redactor()
    assert "AKIAIOSFODNN7EXAMPLE" not in r.redact("AKIAIOSFODNN7EXAMPLE")


def test_jwt_redacted():
    r = Redactor()
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abc_DEF-123"
    assert jwt not in r.redact(f"token={jwt}")


def test_redact_obj_recurses():
    r = Redactor(["topsecretvalue"])
    out = r.redact_obj({"a": ["topsecretvalue", {"b": "topsecretvalue"}]})
    assert out == {"a": [PLACEHOLDER, {"b": PLACEHOLDER}]}


def test_upstream_response_secret_is_redacted(broker):
    resp = broker.agent.get("/proxy/openai/v1/models", headers=agent_headers())
    assert resp.status_code == 200
    # The upstream echoed the real secret in two places; both must be scrubbed.
    assert broker.secret not in resp.text
    assert PLACEHOLDER in resp.text
