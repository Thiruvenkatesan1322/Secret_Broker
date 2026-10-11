# secret-broker

A local **secrets proxy + approval-gated task runner** for AI coding agents.

AI agents running in your editor should never see your API keys or credentials. `secret-broker`
gives an agent only a localhost HTTP interface that:

1. **Proxies** allow-listed API calls, injecting the real credentials **server-side** so the
   agent never handles them, and
2. **Runs predefined tasks** only after **you** approve them in a separate terminal.

Default deny everywhere. No wildcard forwarding. No `shell=True`. No `eval`/`exec`. Secrets are
never written to disk, logs, error messages, or stack traces.

---

## How it works

```
AI agent  --X-Broker-Token-->  127.0.0.1:8787  (agent API: proxy + submit task + poll)
you       --X-Admin-Token-->   127.0.0.1:8788  (admin API: list/show/approve/deny)
```

- The **agent API** (`:8787`) can submit tasks and poll status, and proxy allow-listed calls.
  It **cannot** approve anything.
- The **admin API** (`:8788`) is where approvals happen, protected by a *different* token the
  agent never has. You drive it with the `broker-approve` CLI in your own terminal.
- The broker injects real auth headers server-side, strips any the agent sends, blocks SSRF
  (path traversal, absolute URLs, redirects, unlisted hosts), enforces per-service rate limits
  and size caps, redacts secrets from everything, and writes an append-only audit log.

---

## Project layout

```
broker/            FastAPI apps, proxy, task runner, redaction, security, audit, CLI
client/            broker_client.py - tiny agent-side helper
tests/             pytest suite (security-focused)
policy.yaml        services, base URLs, auth header format, allow-listed method+path regex
tasks.yaml         named tasks: argv template, typed args, cwd, timeout, auto_approve
.env.example       variable NAMES only (how to inject real values safely)
Dockerfile         non-root, read-only fs, no-new-privileges, drop all caps
docker-compose.yml 127.0.0.1 binding, Docker secrets, read-only workspace mount
Makefile           make up / make approve / make test / make secrets
AGENT_INSTRUCTIONS.md   drop into the agent's context
```

---

## Quick start (local, without Docker)

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# Run the tests
pytest -q
```

### Run the broker locally

Inject secrets via your environment (never into the project directory):

```bash
export BROKER_TOKEN=$(python -c "import secrets;print(secrets.token_urlsafe(32))")
export BROKER_ADMIN_TOKEN=$(python -c "import secrets;print(secrets.token_urlsafe(32))")
export OPENAI_API_KEY=...        # your real key, from your secret manager
export BROKER_SECRETS_DIR=/nonexistent   # force env-based secret loading for local dev
python -m broker
```

On Windows PowerShell:

```powershell
$env:BROKER_TOKEN = python -c "import secrets;print(secrets.token_urlsafe(32))"
$env:BROKER_ADMIN_TOKEN = python -c "import secrets;print(secrets.token_urlsafe(32))"
$env:OPENAI_API_KEY = "..."       # from your secret manager, not hardcoded
$env:BROKER_SECRETS_DIR = "C:\nonexistent"
python -m broker
```

---

## Run with Docker (recommended)

```bash
make secrets          # writes throwaway broker/admin tokens into ./secrets (git-ignored)
# put your real key in ./secrets/openai_api_key (or inject via op/doppler - see below)
make up               # builds and starts the broker on 127.0.0.1:8787 / :8788
```

The compose file binds only to `127.0.0.1`, runs the container as a non-root user with a
read-only root filesystem, `no-new-privileges`, and all Linux capabilities dropped. The
project directory is **not** mounted into the container - only a read-only `./workspace` and a
writable audit volume.

---

## Injecting secrets safely

Never put real secrets in the project directory or commit them. Pick one:

- **1Password CLI:** `op run --env-file=.env.op -- make up`
- **Doppler:** `doppler run -- make up`
- **Docker secrets:** place files in `./secrets/` (git-ignored); compose mounts them at
  `/run/secrets/<name>` inside the container only.

`.env.example` lists the variable **names** only.

---

## Approving tasks (in YOUR terminal)

Run this in a terminal the agent cannot drive. It needs the **admin** token:

```bash
export BROKER_ADMIN_TOKEN=...            # same value the broker was started with
export BROKER_ADMIN_URL=http://127.0.0.1:8788

broker-approve list                      # or: python -m broker.cli.approve list
broker-approve show <request_id>         # shows task, exact args, resolved command
broker-approve approve <request_id>
broker-approve deny <request_id>
```

(Or via Make: `make approve list`, `make approve approve <id>`.)

---

## Configuration

**policy.yaml** - services, base URL, auth header name/format + secret name, allow-listed
`methods` + `path` regex (fullmatched against the sub-path without a leading slash), per-service
`rate_limit_per_minute`, and optional `forward_headers`.

**tasks.yaml** - each task has a fixed argv `command` template, typed `args`
(`string`+regex / `enum`+choices / `int`+min/max), `cwd` (resolved under the workspace and not
allowed to escape it), `timeout`, and `auto_approve`.

---

## Threat model

- The agent runs as your OS user, inside the project folder, and can read any file and run
  shell commands there. Assume it may be prompt-injected.
- Secrets must not exist in the project directory, the agent's environment, or any file/process
  the agent's user can read.

**Mitigations:** secrets are loaded only from Docker secrets / injected env in a separate
container; the agent gets a throwaway token, not real credentials; auth is injected
server-side and client-supplied `Authorization` is stripped; default-deny proxy + task
allowlists; no shell execution; tasks run with a clean environment that does not inherit the
broker's secrets; all output, logs, and audit entries are redacted; approvals require a
separate admin token on a separate port.

---

## Known limitations

- **Same OS user:** if the agent and your approval terminal run as the *same* OS user on the
  same host, loopback/port separation is a soft boundary, not a hard one - a determined local
  process could interfere. For a hard boundary, run the broker as a **different OS user** or in
  a **separate VM/host**, and keep the admin token only in your human terminal. The Docker
  setup (separate container, non-root, no project mount) is the recommended posture.
- **Admin channel is a localhost port**, not a Unix socket (chosen for Windows + Docker
  portability). It is bound to `127.0.0.1` only and gated by a separate admin token.
- In-memory approval store: pending/among-run state is lost on restart (by design for a
  prototype). The audit log on disk is durable.
- Redaction is best-effort pattern + known-value matching; keep your policy/tasks tight.

---

## Hard rules enforced

- Default deny everywhere; no wildcard forwarding.
- No `shell=True`, no `eval`/`exec`; tasks run as argv lists with validated args.
- Secrets never written to disk, logs, errors, or stack traces.
- Pinned dependency versions; `gitleaks` pre-commit config included.
- Fail closed on any config or validation error.

---

## Manual checklist

See the end of the setup you ran, or:

1. Inject real secrets outside the project dir (`op run` / `doppler run` / `./secrets/*`).
2. Start the broker where the agent cannot reach its secrets (Docker, ideally a different user).
3. Run `broker-approve` in a separate terminal that holds the admin token.
4. Drop `AGENT_INSTRUCTIONS.md` into your agent's context.
