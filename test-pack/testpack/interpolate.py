"""Tiny ${value} templating used by config values and check parameters.

Supported forms:

    ${project_id}                  value from config.yml
    ${project_id:-my-project}      value with a fallback
    ${env:HOME}                    environment variable
    ${env:REGION:-europe-west2}    environment variable with a fallback

Empty strings count as missing. That is deliberate: it lets a check that
depends on an unset value be skipped instead of failing noisily.
"""

from __future__ import annotations

import os
import re
from typing import Any, Mapping, Protocol

_PLACEHOLDER = re.compile(r"\$\{([^{}]+)\}")


class MissingValue(Exception):
    """Raised when a placeholder cannot be resolved."""

    def __init__(self, key: str, reason: str = "is not set"):
        self.key = key
        self.reason = reason
        super().__init__(f"{key} {reason}")


class ValueSource(Protocol):
    def get(self, key: str) -> Any:  # pragma: no cover - typing helper
        ...


def _parse(expression: str) -> tuple[str, str, str | None]:
    expression = expression.strip()
    source = "values"
    if expression.startswith("env:"):
        source = "env"
        expression = expression[4:]
    if ":-" in expression:
        key, default = expression.split(":-", 1)
        return source, key.strip(), default
    return source, expression, None


def _lookup(expression: str, values: ValueSource | Mapping[str, Any] | None) -> str:
    source, key, default = _parse(expression)

    value: Any = None
    if source == "env":
        value = os.environ.get(key)
    elif values is not None:
        try:
            value = values.get(key)
        except MissingValue:
            value = None

    if value is None or (isinstance(value, str) and value.strip() == ""):
        if default is not None:
            return default
        raise MissingValue(key)
    return str(value)


def interpolate(value: Any, values: ValueSource | Mapping[str, Any] | None) -> Any:
    """Recursively replace placeholders in strings, lists and dicts."""

    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda match: _lookup(match.group(1), values), value)
    if isinstance(value, list):
        return [interpolate(item, values) for item in value]
    if isinstance(value, tuple):
        return tuple(interpolate(item, values) for item in value)
    if isinstance(value, dict):
        return {key: interpolate(item, values) for key, item in value.items()}
    return value
