"""Task validation, command resolution, and sandboxed execution (no shell, clean env)."""

from __future__ import annotations

import asyncio
import datetime
import os
import subprocess

from .errors import ConfigError, ValidationError
from .models import TaskSpec
from .state import BrokerState, TaskRequest

# Environment variables deliberately NOT inherited by tasks: none of the broker's
# secrets are here. Only a minimal, portable set is passed through.
_SAFE_ENV_KEYS = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "PATHEXT",
    "COMSPEC",
)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def validate_args(task: TaskSpec, raw: object) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValidationError("args must be an object")
    unknown = set(raw) - set(task.args)
    if unknown:
        raise ValidationError(f"unknown args: {sorted(unknown)}")
    validated: dict[str, str] = {}
    for name, spec in task.args.items():
        if name in raw and raw[name] is not None:
            validated[name] = spec.validate_value(name, raw[name])
        elif spec.default is not None:
            validated[name] = spec.validate_value(name, spec.default)
        elif spec.required:
            raise ValidationError(f"missing required arg: {name}")
    return validated


def resolve_command(task: TaskSpec, validated: dict) -> list[str]:
    try:
        return [part.format(**validated) for part in task.command]
    except (KeyError, IndexError) as exc:
        raise ValidationError(f"failed to resolve command: {exc}") from exc


def resolve_cwd(state: BrokerState, task: TaskSpec):
    base = state.settings.workspace_dir.resolve()
    target = (base / task.cwd).resolve()
    if target != base and base not in target.parents:
        raise ConfigError(f"task cwd escapes the workspace: {task.cwd}")
    if not target.is_dir():
        raise ConfigError(f"task cwd does not exist: {target}")
    return target


def _clean_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in _SAFE_ENV_KEYS if k in os.environ}
    env.setdefault("PATH", os.defpath)
    return env


def _finish(state: BrokerState, request: TaskRequest, **changes) -> None:
    changes.setdefault("finished_at", _now())
    state.store.update(request.id, **changes)
    updated = state.store.get(request.id)
    state.audit.record(
        kind="task_result",
        request_id=request.id,
        task=request.name,
        status=changes.get("status"),
        exit_code=changes.get("exit_code"),
    )


async def execute(state: BrokerState, request: TaskRequest) -> TaskRequest:
    """Run the resolved command and store redacted output. Never raises."""
    task = state.tasks.tasks[request.name]
    try:
        cwd = resolve_cwd(state, task)
    except ConfigError as exc:
        _finish(state, request, status="error", error=state.redactor.redact(str(exc)))
        return state.store.get(request.id)

    state.store.update(request.id, status="running")

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - argv list, shell=False, validated inputs
            request.command,
            cwd=str(cwd),
            env=_clean_env(),
            capture_output=True,
            text=True,
            timeout=task.timeout,
            shell=False,
            check=False,
        )

    try:
        proc = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        _finish(state, request, status="failed", error="task timed out", stderr="task timed out")
        return state.store.get(request.id)
    except (OSError, ValueError):
        _finish(state, request, status="error", error="execution error")
        return state.store.get(request.id)

    _finish(
        state,
        request,
        status="success" if proc.returncode == 0 else "failed",
        exit_code=proc.returncode,
        stdout=state.redactor.redact(proc.stdout or ""),
        stderr=state.redactor.redact(proc.stderr or ""),
    )
    return state.store.get(request.id)
