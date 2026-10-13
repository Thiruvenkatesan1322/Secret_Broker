# secret-broker (minimal)

A tiny **local secrets proxy** for AI coding agents, in a single file.

Your AI agent should never see your API keys. `secret-broker` gives the agent only a
localhost endpoint and a throwaway token. It can call **only allow-listed APIs**; the broker
injects your real key **server-side** and **scrubs secrets** from every response. Your real
keys never reach the agent, your shell history, or the project folder.

> This is the minimal, proxy-only edition — one file, no third-party dependencies.

## Files

| File | Purpose |
|---|---|
| [`minimal/broker_min.py`](minimal/broker_min.py) | The whole broker — run this. |
| [`examples/token_demo.py`](examples/token_demo.py) | Runnable walkthrough of how the token gates access. |
| [`docs/index.html`](docs/index.html) | Interactive visual explainer (open in a browser). |

## Quick start

```powershell
# 1) Put your real key where the agent can't read it — an env var OR the OS keychain:
$env:OPENAI_API_KEY = "sk-..."
#    (or, persistent & encrypted:  pip install keyring
#     python -c "import keyring; keyring.set_password('secret-broker','OPENAI_API_KEY','sk-...')")

# 2) Run the broker
python minimal/broker_min.py
#    -> prints:  BROKER_TOKEN (give this to the agent): tok_xxxxx

# 3) The agent calls only allow-listed endpoints, with the token:
curl http://127.0.0.1:8787/proxy/openai/v1/models -H "X-Broker-Token: tok_xxxxx"
```

To try it without any real key or network, run the demo:

```powershell
python examples/token_demo.py
```

## How it works

Everything lives in [`minimal/broker_min.py`](minimal/broker_min.py):

1. **`SERVICES`** (top of file) — the allowlist of `(method, path)` pairs per service. Default
   deny: anything not listed returns `403`. Edit this to add your own endpoints.
2. **`load_secret`** — reads each key from an environment variable first, then the OS keychain
   (Windows Credential Manager / macOS Keychain / Linux Secret Service), service `secret-broker`.
3. **`make_redactor`** — removes the real key and common credential shapes (`Bearer …`, `sk-…`,
   `AKIA…`, JWTs) from every response.
4. **`clean_path` / `route_allowed`** — block path traversal, absolute URLs, and redirects
   (SSRF protection), and enforce the allowlist.
5. **`Handler`** — checks the `X-Broker-Token` (constant-time), strips any `Authorization` the
   agent sent, injects the real key server-side, forwards the call, and returns a redacted
   response.

## Where your secrets are kept

Not in the project directory and not in a plaintext `.env`. Use either:

- **Environment variable** injected at launch (e.g. from a secret manager), or
- the **OS keychain**, encrypted at rest for your user (on Windows, via DPAPI).

## Security notes

- Default deny everywhere; no wildcard forwarding; no shell execution.
- The agent gets a throwaway token, never the real key; client-supplied `Authorization` is
  stripped and replaced server-side.
- Secrets are redacted from responses.

**Limitation:** if the agent runs as the *same OS user* as the broker, it could read the same
environment/keychain. For a hard boundary, run the broker as a different OS user or in a VM.

## Run isolated on this machine (no Docker)

To make the boundary real on Windows, run the broker as a **dedicated low-privilege user** so an
agent running as you can't read its key, environment, or process — it can only reach the port.
Scripts are in [`isolate/`](isolate):

```powershell
# One time, in an ELEVATED PowerShell (Run as administrator):
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\isolate\setup-broker-user.ps1          # prompts (hidden) for your API key; prints a token
```

This creates a `secretbroker` local user, locks down `C:\ProgramData\secret-broker` with NTFS
ACLs (your normal user can't read it), stores the key + token there, and registers a Scheduled
Task that runs the broker as `secretbroker` on `127.0.0.1:8787`. Then, in **your** shell:

```powershell
$env:BROKER_TOKEN = "tok_..."            # the token the script printed
curl http://127.0.0.1:8787/health
```

Remove it all with `.\isolate\uninstall-broker-user.ps1` (elevated).

**This is a hard boundary only if your agent runs as a _standard (non-admin)_ user.** A local
administrator can bypass any same-machine isolation — in that case use a separate VM or host and
expose only `127.0.0.1:8787` to the agent. Python should be installed for **all users** so the
broker user can run it.

## License

MIT — see [LICENSE](LICENSE).
