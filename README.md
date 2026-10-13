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

## License

MIT — see [LICENSE](LICENSE).
