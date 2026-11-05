"""Load YAML check files and Python plugins.

Errors here are user-facing: a mistyped key or an unknown check type should
produce a message that points at the file and line-ish location, not a stack
trace.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from .models import CRITICAL, WARNING, CheckSpec
from .registry import get_check
from .registry import names as check_type_names

_CHECK_KEYS = {
    "id",
    "title",
    "type",
    "params",
    "severity",
    "tags",
    "timeout",
    "enabled",
    "hint",
}
_FILE_KEYS = {"category", "description", "defaults", "checks"}
_DEFAULT_KEYS = {"severity", "tags", "timeout", "enabled"}


class LoadError(Exception):
    """A malformed checks file or plugin."""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "check"


def _prettify(value: str) -> str:
    value = re.sub(r"^[0-9]+[_-]*", "", value)
    return value.replace("_", " ").replace("-", " ").strip().title() or "General"


def _as_tags(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise LoadError(f"{where}: 'tags' must be a string or a list of strings")


def _as_severity(value: Any, where: str) -> str:
    severity = str(value or CRITICAL).strip().lower()
    if severity not in {CRITICAL, WARNING}:
        raise LoadError(f"{where}: 'severity' must be 'critical' or 'warning', got {value!r}")
    return severity


def _parse_check(
    item: Any,
    path: Path,
    index: int,
    category: str,
    defaults: dict[str, Any],
    default_timeout: float,
) -> CheckSpec:
    where = f"{path.name} check #{index}"
    if not isinstance(item, dict):
        raise LoadError(f"{where}: expected a mapping")

    unknown = set(item) - _CHECK_KEYS
    if unknown:
        raise LoadError(
            f"{where}: unknown key(s): {', '.join(sorted(unknown))}. "
            f"Allowed keys: {', '.join(sorted(_CHECK_KEYS))}"
        )

    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        raise LoadError(f"{where}: 'title' is required")
    title = title.strip()

    type_name = item.get("type")
    if not isinstance(type_name, str) or not type_name.strip():
        raise LoadError(f"{where} ({title}): 'type' is required")
    type_name = type_name.strip()
    if get_check(type_name) is None:
        available = ", ".join(check_type_names())
        raise LoadError(
            f"{where} ({title}): unknown check type '{type_name}'.\nAvailable types: {available}"
        )

    merged: dict[str, Any] = {**defaults, **item}
    severity = _as_severity(merged.get("severity"), where)
    tags = _as_tags(merged.get("tags"), where)

    timeout_raw = merged.get("timeout", default_timeout)
    try:
        timeout = float(timeout_raw)
    except (TypeError, ValueError):
        raise LoadError(f"{where}: 'timeout' must be a number of seconds") from None
    if timeout <= 0:
        raise LoadError(f"{where}: 'timeout' must be greater than zero")

    params = item.get("params") or {}
    if not isinstance(params, dict):
        raise LoadError(f"{where}: 'params' must be a mapping")

    hint = merged.get("hint")
    if hint is not None and not isinstance(hint, str):
        raise LoadError(f"{where}: 'hint' must be a string")

    check_id = item.get("id") or _slugify(title)
    if not isinstance(check_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", check_id):
        raise LoadError(
            f"{where}: 'id' may contain letters, numbers, '.', '_', ':' and '-', got {check_id!r}"
        )

    return CheckSpec(
        id=check_id,
        title=title,
        type=type_name,
        params=params,
        category=category,
        severity=severity,
        tags=tags,
        timeout=timeout,
        enabled=bool(merged.get("enabled", True)),
        hint=hint,
        file=path.name,
    )


def load_checks(checks_dir: Path, default_timeout: float = 60) -> list[CheckSpec]:
    """Read every *.yml / *.yaml file in `checks_dir`, in filename order."""

    checks_dir = Path(checks_dir)
    if not checks_dir.exists():
        raise LoadError(f"checks directory not found: {checks_dir}")
    if not checks_dir.is_dir():
        raise LoadError(f"checks path is not a directory: {checks_dir}")

    files = sorted([*checks_dir.glob("*.yml"), *checks_dir.glob("*.yaml")])
    if not files:
        raise LoadError(f"no .yml or .yaml check files found in {checks_dir}")

    specs: list[CheckSpec] = []
    seen: dict[str, str] = {}

    for path in files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise LoadError(f"{path.name}: invalid YAML: {exc}") from exc
        except OSError as exc:
            raise LoadError(f"could not read {path}: {exc}") from exc

        if data is None:
            continue
        if not isinstance(data, dict):
            raise LoadError(f"{path.name}: expected a mapping at the top level")

        unknown = set(data) - _FILE_KEYS
        if unknown:
            raise LoadError(
                f"{path.name}: unknown top-level key(s): {', '.join(sorted(unknown))}. "
                f"Allowed keys: {', '.join(sorted(_FILE_KEYS))}"
            )

        category = str(data.get("category") or _prettify(path.stem)).strip()
        defaults = data.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise LoadError(f"{path.name}: 'defaults' must be a mapping")
        unknown_defaults = set(defaults) - _DEFAULT_KEYS
        if unknown_defaults:
            raise LoadError(
                f"{path.name}: unknown key(s) in 'defaults': "
                f"{', '.join(sorted(unknown_defaults))}. "
                f"Allowed: {', '.join(sorted(_DEFAULT_KEYS))}"
            )

        checks = data.get("checks")
        if not isinstance(checks, list) or not checks:
            raise LoadError(f"{path.name}: expected a non-empty 'checks:' list")

        for index, item in enumerate(checks, 1):
            spec = _parse_check(item, path, index, category, defaults, default_timeout)
            if spec.id in seen:
                raise LoadError(
                    f"duplicate check id '{spec.id}' in {path.name} "
                    f"(already defined in {seen[spec.id]})"
                )
            seen[spec.id] = path.name
            specs.append(spec)

    return specs


def load_plugins(plugins_dir: Path) -> list[str]:
    """Import every *.py file in `plugins_dir`; @check decorators register types."""

    plugins_dir = Path(plugins_dir)
    if not plugins_dir.exists():
        return []
    if not plugins_dir.is_dir():
        raise LoadError(f"plugins path is not a directory: {plugins_dir}")

    loaded: list[str] = []
    for path in sorted(plugins_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue

        module_name = f"testpack_plugin_{_slugify(path.stem).replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise LoadError(f"could not load plugin {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(module_name, None)
            raise LoadError(
                f"could not load plugin {path.name}: {type(exc).__name__}: {exc}"
            ) from exc

        loaded.append(path.stem)

    return loaded
