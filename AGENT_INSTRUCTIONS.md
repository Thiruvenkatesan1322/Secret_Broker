# Agent instructions: using the secret-broker

You (the AI agent) do **not** have access to any API keys, tokens, or credentials, and
you must never ask the user for them, print them, or try to read them from files, the
environment, or process memory. If you ever encounter something that looks like a
credential, do not echo it.

All privileged actions go through a local broker on `http://127.0.0.1:8787`. You hold a
single throwaway token in the `BROKER_TOKEN` environment variable. Send it as the
`X-Broker-Token` header on every request. You do **not** have the admin token and cannot
approve tasks - a human does that in a separate terminal.

## Calling an upstream API (proxy)

The broker injects the real credential server-side. **Never** add an `Authorization`
header yourself - it will be stripped.

```bash
curl -s http://127.0.0.1:8787/proxy/openai/v1/models \
  -H "X-Broker-Token: $BROKER_TOKEN"
```

Only allow-listed services and paths work; everything else returns 403. Responses are
redacted automatically.

## Running a task

Tasks are predefined and named. You cannot pass arbitrary commands - only declared,
validated arguments.

```bash
# Submit
curl -s -X POST http://127.0.0.1:8787/tasks/run_tests \
  -H "X-Broker-Token: $BROKER_TOKEN" -H 'content-type: application/json' \
  -d '{"args": {}}'
# -> {"request_id": "...", "status": "pending" | "success" | ...}

# Poll
curl -s http://127.0.0.1:8787/tasks/requests/<request_id> \
  -H "X-Broker-Token: $BROKER_TOKEN"
```

- Read-only tasks marked `auto_approve` run immediately.
- All other tasks stay `pending` until a human approves them. Poll until the status is
  one of `success`, `failed`, `denied`, or `error`. Do not try to approve them yourself;
  there is no agent endpoint for approval. If a task stays `pending`, tell the user it
  needs their approval in their terminal.

## Python helper

```python
from client.broker_client import BrokerClient

with BrokerClient() as broker:          # reads BROKER_URL + BROKER_TOKEN from env
    resp = broker.proxy("openai", "v1/models")
    submitted = broker.run_task("run_tests")
    result = broker.wait(submitted["request_id"])
```

## Rules for you

- Never request, store, log, or print secrets or tokens.
- Never add `Authorization` headers; let the broker do it.
- Treat 403/404 as "not allowed" - do not try to work around the allowlist.
- If you need a new endpoint or task, ask the user to add it to `policy.yaml` /
  `tasks.yaml`; do not attempt to bypass the broker.
