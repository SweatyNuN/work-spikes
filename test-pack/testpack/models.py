"""Small data objects shared by the loader, runner and reporter.

Keeping these free of imports from the rest of the package means checkers,
plugins and the reporter can all depend on them safely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PASS = "pass"
FAIL = "fail"
SKIP = "skip"

CRITICAL = "critical"
WARNING = "warning"


@dataclass(frozen=True)
class CheckSpec:
    """A single check as declared in a YAML file."""

    id: str
    title: str
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    category: str = "General"
    severity: str = CRITICAL
    tags: tuple[str, ...] = ()
    timeout: float | None = None
    enabled: bool = True
    hint: str | None = None
    file: str = ""

    @property
    def is_warning(self) -> bool:
        return self.severity == WARNING


@dataclass
class Outcome:
    """What a checker returns. Checkers never raise for an expected failure."""

    status: str
    message: str
    detail: str = ""
    hint: str = ""

    @classmethod
    def ok(cls, message: str = "OK", detail: str = "", hint: str = "") -> "Outcome":
        return cls(PASS, message, detail, hint)

    @classmethod
    def fail(cls, message: str, detail: str = "", hint: str = "") -> "Outcome":
        return cls(FAIL, message, detail, hint)

    @classmethod
    def skip(cls, message: str, hint: str = "") -> "Outcome":
        return cls(SKIP, message, "", hint)


@dataclass
class Result:
    """A check plus what happened when it ran."""

    spec: CheckSpec
    outcome: Outcome
    duration: float = 0.0

    @property
    def status(self) -> str:
        return self.outcome.status

    @property
    def is_failure(self) -> bool:
        return self.outcome.status == FAIL

    @property
    def is_critical_failure(self) -> bool:
        return self.is_failure and self.spec.severity == CRITICAL

    @property
    def is_warning_failure(self) -> bool:
        return self.is_failure and self.spec.severity == WARNING
