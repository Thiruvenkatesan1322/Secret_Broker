"""Exception hierarchy. Everything fails closed: callers treat any BrokerError as deny."""

from __future__ import annotations


class BrokerError(Exception):
    """Base class for all broker errors."""


class ConfigError(BrokerError):
    """Configuration is missing or invalid. Startup must abort (fail closed)."""


class SecretError(ConfigError):
    """A required secret could not be loaded."""


class SecurityError(BrokerError):
    """A request failed a security check (SSRF, path traversal, bad host, ...)."""


class ValidationError(BrokerError):
    """Task args or proxy inputs failed validation."""
