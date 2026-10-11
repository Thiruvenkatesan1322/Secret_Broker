"""broker-approve: the human approval CLI. Runs in YOUR terminal, never the agent's.

It talks to the admin API (separate port + admin token). The agent has neither.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys

import httpx


def _client() -> httpx.Client:
    base_url = os.environ.get("BROKER_ADMIN_URL", "http://127.0.0.1:8788")
    token = os.environ.get("BROKER_ADMIN_TOKEN")
    if not token:
        print(
            "ERROR: BROKER_ADMIN_TOKEN is not set in this terminal. "
            "Set it from your secret manager before approving.",
            file=sys.stderr,
        )
        sys.exit(2)
    return httpx.Client(base_url=base_url, headers={"x-admin-token": token}, timeout=30.0)


def _check(response: httpx.Response) -> None:
    if response.status_code == 401:
        print("ERROR: admin token rejected by broker.", file=sys.stderr)
        sys.exit(3)
    if response.status_code >= 400:
        print(f"ERROR {response.status_code}: {response.text}", file=sys.stderr)
        sys.exit(1)


def cmd_list(args: argparse.Namespace) -> None:
    with _client() as client:
        params = {"status": args.status} if args.status else None
        response = client.get("/requests", params=params)
        _check(response)
        items = response.json()["requests"]
    if not items:
        print("No requests.")
        return
    for item in items:
        print(
            f"{item['request_id']}  {item['status']:<9}  {item['task']:<16}  "
            f"args={json.dumps(item['args'])}"
        )


def cmd_show(args: argparse.Namespace) -> None:
    with _client() as client:
        response = client.get(f"/requests/{args.id}")
        _check(response)
        item = response.json()
    print(json.dumps(item, indent=2))
    print("\nResolved command (exactly what will run):")
    print("  " + " ".join(shlex.quote(part) for part in item["command"]))


def cmd_approve(args: argparse.Namespace) -> None:
    with _client() as client:
        response = client.post(f"/requests/{args.id}/approve")
        _check(response)
        item = response.json()
    print(f"Approved {args.id}: status={item['status']} exit_code={item.get('exit_code')}")
    if item.get("stdout"):
        print("--- stdout ---")
        print(item["stdout"])
    if item.get("stderr"):
        print("--- stderr ---")
        print(item["stderr"])


def cmd_deny(args: argparse.Namespace) -> None:
    with _client() as client:
        response = client.post(f"/requests/{args.id}/deny")
        _check(response)
        item = response.json()
    print(f"Denied {args.id}: status={item['status']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="broker-approve",
        description="Approve or deny broker task requests (admin channel).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list task requests")
    p_list.add_argument("--status", help="filter by status (e.g. pending)")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="show a request and its resolved command")
    p_show.add_argument("id")
    p_show.set_defaults(func=cmd_show)

    p_approve = sub.add_parser("approve", help="approve and run a pending request")
    p_approve.add_argument("id")
    p_approve.set_defaults(func=cmd_approve)

    p_deny = sub.add_parser("deny", help="deny a pending request")
    p_deny.add_argument("id")
    p_deny.set_defaults(func=cmd_deny)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
