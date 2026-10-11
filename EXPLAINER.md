# secret-broker — a simple explainer

## The one-liner
**secret-broker keeps your API keys away from AI coding agents.** The agent can still get
work done — it just never sees your actual secrets, and it can't run risky commands without
your approval.

---

## The problem
AI coding agents run on your machine, as you. They can read your files and run commands.
That's useful — but it also means that if your API keys sit in a `.env` file or environment
variable, a misbehaving or tricked ("prompt-injected") agent could copy them and send them
somewhere. Once a key leaks, anyone can run up your bill or access your accounts.

## The idea
Put a small gatekeeper — the **broker** — between the agent and anything sensitive.

- The agent gets a **throwaway local token**, not your real keys.
- The broker holds the real keys privately and uses them *on the agent's behalf*.
- Anything risky waits for **your** approval.

Think of it like a hotel front desk: guests can ask the desk to do things, but they never
get the master keys, and some requests need a manager's sign-off.

---

## How it works (3 steps)

1. **Agent asks** the broker to do something (it only has a local token).
2. **Broker adds the real key** and makes the actual call — or, for risky actions, holds the
   request until you approve it.
3. **Broker returns a safe answer**, with any secret automatically scrubbed out.

---

## A simple example

The agent wants to list available AI models. It asks the broker:

```
GET /proxy/openai/v1/models
X-Broker-Token: (local token, NOT your real key)
```

Behind the scenes the broker adds your real key and calls the service. The agent gets back:

```
{ "data": ["gpt-4", "gpt-4o"] }
```

The agent sees the result — but never your key.

---

## What about risky actions?

Some things (deploying, deleting, anything that changes the world) shouldn't happen
automatically. For those:

1. The agent requests it → the broker marks it **"pending"** and does nothing yet.
2. **You** review it in your own terminal and see the *exact* command that would run.
3. You type `approve` (or `deny`). Only then does it run.

The agent literally has no way to approve its own requests — that power lives in a separate
channel only you control.

---

## Why it's safe (in plain terms)

- **Keys never reach the agent.** They're added by the broker, server-side.
- **Only approved destinations work.** The agent can't call random URLs — only a pre-set
  allowlist. Everything else is denied by default.
- **No arbitrary commands.** Tasks are predefined with fixed, validated inputs — no "run
  whatever you want."
- **Secrets get scrubbed** from every response, log, and error message.
- **You hold the approval.** Risky actions need your explicit sign-off.

---

## Who is this for?
Anyone letting an AI agent work in a codebase that touches real credentials or real systems —
developers, teams, or anyone who wants the productivity of AI agents without handing them the
keys to the kingdom.
