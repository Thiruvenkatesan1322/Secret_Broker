"""Load secrets from a Docker-secrets directory or the environment. Fails closed."""

from __future__ import annotations

import os
from pathlib import Path

from .errors import SecretError


def load_secrets(secrets_dir: Path, required: set[str]) -> dict[str, str]:
    """Resolve every required secret name to a value.

    Resolution order per name: a file in `secrets_dir` whose name matches
    (case-insensitively), then an environment variable of the same name.
    Raises SecretError if any required secret is missing or empty.
    """
    from_dir: dict[str, str] = {}
    if secrets_dir and Path(secrets_dir).is_dir():
        for entry in Path(secrets_dir).iterdir():
            if entry.is_file():
                try:
                    from_dir[entry.name] = entry.read_text(encoding="utf-8").strip()
                except OSError:
                    continue

    lower_map = {name.lower(): name for name in from_dir}
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for name in required:
        value: str | None = None
        if name in from_dir:
            value = from_dir[name]
        elif name.lower() in lower_map:
            value = from_dir[lower_map[name.lower()]]
        else:
            value = os.environ.get(name)
        if not value:
            missing.append(name)
        else:
            resolved[name] = value

    if missing:
        # Names only; never echo any attempted values.
        raise SecretError(f"required secrets are not available: {sorted(missing)}")
    return resolved
