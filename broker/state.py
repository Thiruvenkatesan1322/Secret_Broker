"""Shared broker state: approval store, and the build_state() wiring entry point."""

from __future__ import annotations

import datetime
import threading
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx

from .audit import AuditLog
from .config import Settings, load_policy, load_tasks
from .models import Policy, TasksConfig
from .ratelimit import RateLimiter
from .redaction import Redactor
from .secrets_loader import load_secrets

TERMINAL_STATES: frozenset[str] = frozenset({"success", "failed", "denied", "error"})


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@dataclass
class TaskRequest:
    id: str
    name: str
    args: dict
    command: list[str]
    cwd: str
    auto_approve: bool
    status: str
    created_at: str
    caller: str = "agent"
    approver: Optional[str] = None
    decided_at: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None

    def public(self) -> dict:
        """Agent-facing view: status and (redacted) output only, no resolved command."""
        return {
            "request_id": self.id,
            "task": self.name,
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }

    def admin_view(self) -> dict:
        """Admin-facing view: adds the exact args, resolved command, and working dir."""
        data = self.public()
        data.update(
            {
                "args": self.args,
                "command": self.command,
                "cwd": self.cwd,
                "auto_approve": self.auto_approve,
                "approver": self.approver,
                "decided_at": self.decided_at,
            }
        )
        return data


class ApprovalStore:
    """Thread-safe in-memory store of task requests."""

    def __init__(self) -> None:
        self._items: dict[str, TaskRequest] = {}
        self._lock = threading.Lock()

    def create(self, **kwargs) -> TaskRequest:
        request = TaskRequest(id=uuid.uuid4().hex, created_at=_now(), **kwargs)
        with self._lock:
            self._items[request.id] = request
        return request

    def get(self, request_id: str) -> Optional[TaskRequest]:
        with self._lock:
            return self._items.get(request_id)

    def list(self) -> list[TaskRequest]:
        with self._lock:
            return list(self._items.values())

    def update(self, request_id: str, **changes) -> Optional[TaskRequest]:
        with self._lock:
            request = self._items.get(request_id)
            if request is None:
                return None
            for key, value in changes.items():
                setattr(request, key, value)
            return request

    def transition(self, request_id: str, expected: str, new_status: str, **changes):
        """Atomically move a request from `expected` to `new_status`.

        Returns the request on success, None if not found, or False if the current
        status is not `expected` (prevents double-approve / approve-after-deny races).
        """
        with self._lock:
            request = self._items.get(request_id)
            if request is None:
                return None
            if request.status != expected:
                return False
            request.status = new_status
            for key, value in changes.items():
                setattr(request, key, value)
            return request


@dataclass
class BrokerState:
    settings: Settings
    policy: Policy
    tasks: TasksConfig
    secrets: dict
    redactor: Redactor
    audit: AuditLog
    rate_limiter: RateLimiter
    store: ApprovalStore
    http: httpx.AsyncClient


def build_state(settings: Settings) -> BrokerState:
    """Load config + secrets and construct the shared state. Fails closed on any error."""
    policy = load_policy(settings.policy_path)
    tasks = load_tasks(settings.tasks_path)
    secrets = load_secrets(settings.secrets_dir, policy.required_secrets())
    redactor = Redactor(
        list(secrets.values()) + [settings.broker_token, settings.admin_token]
    )
    audit = AuditLog(settings.audit_path, redactor)
    http = httpx.AsyncClient(follow_redirects=False, timeout=settings.upstream_timeout)
    return BrokerState(
        settings=settings,
        policy=policy,
        tasks=tasks,
        secrets=secrets,
        redactor=redactor,
        audit=audit,
        rate_limiter=RateLimiter(),
        store=ApprovalStore(),
        http=http,
    )
