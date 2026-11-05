"""Check-type registry.

A check type is just a function:

    @check("my_check", "One-line description")
    def my_check(ctx, params):
        ...
        return Outcome.ok("it worked")

Built-in checkers register themselves in `testpack.checkers`. Plugins in the
`plugins/` directory register extra types the same way, which is how you add
arbitrary Python logic without touching the runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict

from .models import Outcome

CheckFn = Callable[[object, dict], Outcome]


@dataclass(frozen=True)
class RegisteredCheck:
    name: str
    function: CheckFn
    description: str = ""
    source: str = "built-in"


_REGISTRY: Dict[str, RegisteredCheck] = {}


def check(name: str, description: str = "") -> Callable[[CheckFn], CheckFn]:
    """Decorator used by built-in checkers and plugins."""

    def decorator(function: CheckFn) -> CheckFn:
        if name in _REGISTRY:
            existing = _REGISTRY[name]
            raise RuntimeError(
                f"check type '{name}' is already registered by {existing.source}; "
                "choose a different name for your plugin"
            )
        _REGISTRY[name] = RegisteredCheck(name=name, function=function, description=description)
        return function

    return decorator


def get_check(name: str) -> RegisteredCheck | None:
    return _REGISTRY.get(name)


def all_checks() -> list[RegisteredCheck]:
    return sorted(_REGISTRY.values(), key=lambda item: item.name)


def names() -> list[str]:
    return sorted(_REGISTRY)
