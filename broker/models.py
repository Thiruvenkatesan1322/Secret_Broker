"""Pydantic models for policy.yaml and tasks.yaml. All validation fails closed."""

from __future__ import annotations

import re
import string
import urllib.parse
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from .errors import ValidationError


class AuthSpec(BaseModel):
    """How the broker injects the real credential for a service, server-side."""

    model_config = ConfigDict(extra="forbid")

    header: str = "Authorization"
    format: str = "Bearer {secret}"
    secret: str  # name of the secret to resolve from the secrets loader

    @field_validator("format")
    @classmethod
    def _must_reference_secret(cls, value: str) -> str:
        if "{secret}" not in value:
            raise ValueError("auth.format must contain the '{secret}' placeholder")
        return value


class RouteSpec(BaseModel):
    """A single allow-listed (methods, path-regex) pair for a service."""

    model_config = ConfigDict(extra="forbid")

    methods: list[str]
    path: str
    _pattern: Optional[re.Pattern[str]] = PrivateAttr(default=None)

    @field_validator("methods")
    @classmethod
    def _upper_nonempty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("route.methods must not be empty")
        return [m.upper() for m in value]

    @model_validator(mode="after")
    def _compile(self) -> "RouteSpec":
        try:
            self._pattern = re.compile(self.path)
        except re.error as exc:
            raise ValueError(f"invalid route path regex {self.path!r}: {exc}") from exc
        return self

    def matches(self, method: str, path: str) -> bool:
        assert self._pattern is not None
        return method.upper() in self.methods and self._pattern.fullmatch(path) is not None


class ServiceSpec(BaseModel):
    """An upstream service the broker is allowed to proxy to."""

    model_config = ConfigDict(extra="forbid")

    base_url: str
    auth: AuthSpec
    routes: list[RouteSpec]
    rate_limit_per_minute: int = Field(default=60, ge=1)
    forward_headers: list[str] = Field(default_factory=lambda: ["content-type", "accept"])
    max_response_bytes: Optional[int] = Field(default=None, ge=1)
    _host: Optional[str] = PrivateAttr(default=None)

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("base_url must use http or https")
        if not parsed.hostname:
            raise ValueError("base_url must include a host")
        if parsed.query or parsed.fragment or parsed.params:
            raise ValueError("base_url must not contain a query, params, or fragment")
        return value.rstrip("/")

    @model_validator(mode="after")
    def _finalize(self) -> "ServiceSpec":
        if not self.routes:
            raise ValueError("service must declare at least one route")
        self._host = urllib.parse.urlparse(self.base_url).hostname
        return self

    @property
    def host(self) -> str:
        assert self._host is not None
        return self._host


class Policy(BaseModel):
    """Top-level policy.yaml document. Default deny: unlisted services/routes are rejected."""

    model_config = ConfigDict(extra="forbid")

    services: dict[str, ServiceSpec]

    @field_validator("services")
    @classmethod
    def _nonempty(cls, value: dict[str, ServiceSpec]) -> dict[str, ServiceSpec]:
        if not value:
            raise ValueError("policy must declare at least one service")
        return value

    def required_secrets(self) -> set[str]:
        return {svc.auth.secret for svc in self.services.values()}

    def get_service(self, name: str) -> Optional[ServiceSpec]:
        return self.services.get(name)

    def is_allowed(self, service: ServiceSpec, method: str, path: str) -> bool:
        return any(route.matches(method, path) for route in service.routes)


class ArgSpec(BaseModel):
    """Typed, validated schema for a single task argument."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["string", "int", "enum"] = "string"
    regex: Optional[str] = None
    choices: Optional[list[str]] = None
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    required: bool = True
    default: Optional[str] = None
    _rx: Optional[re.Pattern[str]] = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _finalize(self) -> "ArgSpec":
        if self.type == "string" and self.regex:
            try:
                self._rx = re.compile(self.regex)
            except re.error as exc:
                raise ValueError(f"invalid arg regex {self.regex!r}: {exc}") from exc
        if self.type == "enum" and not self.choices:
            raise ValueError("enum arg must declare choices")
        return self

    def validate_value(self, name: str, value: object) -> str:
        """Validate a raw value and return its canonical string form for argv.

        Raises broker.errors.ValidationError on any failure (fail closed).
        """
        if self.type == "enum":
            svalue = str(value)
            if self.choices is None or svalue not in self.choices:
                raise ValidationError(f"arg '{name}' must be one of {self.choices}")
            return svalue
        if self.type == "int":
            try:
                ivalue = int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"arg '{name}' must be an integer") from exc
            if self.minimum is not None and ivalue < self.minimum:
                raise ValidationError(f"arg '{name}' must be >= {self.minimum}")
            if self.maximum is not None and ivalue > self.maximum:
                raise ValidationError(f"arg '{name}' must be <= {self.maximum}")
            return str(ivalue)
        # string
        if not isinstance(value, str):
            raise ValidationError(f"arg '{name}' must be a string")
        if self._rx is not None and self._rx.fullmatch(value) is None:
            raise ValidationError(f"arg '{name}' does not match the required pattern")
        return value


class TaskSpec(BaseModel):
    """A named task with a fixed argv template and validated args. Never uses a shell."""

    model_config = ConfigDict(extra="forbid")

    command: list[str]
    args: dict[str, ArgSpec] = Field(default_factory=dict)
    cwd: str = "."
    timeout: float = Field(default=60.0, gt=0)
    auto_approve: bool = False

    @field_validator("command")
    @classmethod
    def _nonempty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("task.command must not be empty")
        return value

    @model_validator(mode="after")
    def _check_placeholders(self) -> "TaskSpec":
        declared = set(self.args)
        for part in self.command:
            for _literal, field_name, _spec, _conv in string.Formatter().parse(part):
                if field_name is None:
                    continue
                if field_name == "" or not field_name.isidentifier():
                    raise ValueError(f"invalid placeholder in command part {part!r}")
                if field_name not in declared:
                    raise ValueError(
                        f"command references undeclared arg '{field_name}' in {part!r}"
                    )
        return self


class TasksConfig(BaseModel):
    """Top-level tasks.yaml document."""

    model_config = ConfigDict(extra="forbid")

    tasks: dict[str, TaskSpec]

    @field_validator("tasks")
    @classmethod
    def _nonempty(cls, value: dict[str, TaskSpec]) -> dict[str, TaskSpec]:
        if not value:
            raise ValueError("tasks config must declare at least one task")
        return value
