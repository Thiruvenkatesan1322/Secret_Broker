"""Rate limiting: per-service sliding window returns 429 once the limit is exceeded."""

from __future__ import annotations

from tests.conftest import agent_headers


def test_rate_limit_enforced(broker):
    # Policy sets openai to 3 requests/minute.
    statuses = [
        broker.agent.get("/proxy/openai/v1/models", headers=agent_headers()).status_code
        for _ in range(4)
    ]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429
