"""Runtime settings (from env) and YAML config loaders. All loaders fail closed."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import ConfigError
from .models import Policy, TasksConfig


def _env_or_file(name: str, default: str | None = None) -> str | None:
    """Read a value from env var NAME, or from the file named by NAME_FILE (Docker secrets)."""
    value = os.environ.get(name)
    if value:
        return value
    file_path = os.environ.get(f"{name}_FILE")
    if file_path:
        path = Path(file_path)
        if not path.is_file():
            raise ConfigError(f"{name}_FILE points to a missing file: {file_path}")
        return path.read_text(encoding="utf-8").strip()
    return default


@dataclass(frozen=True)
class Settings:
    broker_token: str
    admin_token: str
    policy_path: Path
    tasks_path: Path
    audit_path: Path
    secrets_dir: Path
    workspace_dir: Path
    agent_host: str = "127.0.0.1"
    agent_port: int = 8787
    admin_host: str = "127.0.0.1"
    admin_port: int = 8788
    max_request_bytes: int = 1_048_576
    max_response_bytes: int = 5_242_880
    upstream_timeout: float = 30.0

    @classmethod
    def from_env(cls) -> "Settings":
        broker_token = _env_or_file("BROKER_TOKEN")
        admin_token = _env_or_file("BROKER_ADMIN_TOKEN")
        if not broker_token or not admin_token:
            raise ConfigError(
                "BROKER_TOKEN and BROKER_ADMIN_TOKEN must both be set "
                "(directly or via *_FILE / Docker secrets)"
            )
        if broker_token == admin_token:
            raise ConfigError("BROKER_TOKEN and BROKER_ADMIN_TOKEN must be different values")
        return cls(
            broker_token=broker_token,
            admin_token=admin_token,
            policy_path=Path(os.environ.get("BROKER_POLICY", "policy.yaml")),
            tasks_path=Path(os.environ.get("BROKER_TASKS", "tasks.yaml")),
            audit_path=Path(os.environ.get("BROKER_AUDIT_LOG", "audit.jsonl")),
            secrets_dir=Path(os.environ.get("BROKER_SECRETS_DIR", "/run/secrets")),
            workspace_dir=Path(os.environ.get("BROKER_WORKSPACE", "workspace")),
            agent_host=os.environ.get("BROKER_AGENT_HOST", "127.0.0.1"),
            agent_port=int(os.environ.get("BROKER_AGENT_PORT", "8787")),
            admin_host=os.environ.get("BROKER_ADMIN_HOST", "127.0.0.1"),
            admin_port=int(os.environ.get("BROKER_ADMIN_PORT", "8788")),
            max_request_bytes=int(os.environ.get("BROKER_MAX_REQUEST_BYTES", str(1_048_576))),
            max_response_bytes=int(os.environ.get("BROKER_MAX_RESPONSE_BYTES", str(5_242_880))),
            upstream_timeout=float(os.environ.get("BROKER_UPSTREAM_TIMEOUT", "30")),
        )


def _read_yaml(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config {path} must be a mapping at the top level")
    return data


def load_policy(path: Path) -> Policy:
    try:
        return Policy.model_validate(_read_yaml(path))
    except ConfigError:
        raise
    except Exception as exc:  # pydantic ValidationError, etc.
        raise ConfigError(f"invalid policy ({path}): {exc}") from exc


def load_tasks(path: Path) -> TasksConfig:
    try:
        return TasksConfig.model_validate(_read_yaml(path))
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError(f"invalid tasks ({path}): {exc}") from exc
