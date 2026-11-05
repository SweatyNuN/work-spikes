"""Version comparison without making `packaging` a hard dependency.

`packaging` is used when it is installed (it normally is, on a workbench).
Otherwise a small fallback understands the operators that show up in checks:
`==`, `!=`, `>`, `>=`, `<`, `<=`, `~=` and `==x.y.*`.
"""

from __future__ import annotations

import re

try:  # pragma: no cover - exercised implicitly on a workbench
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version
except ImportError:  # pragma: no cover - fallback path
    SpecifierSet = None  # type: ignore[assignment]
    Version = None  # type: ignore[assignment]

_NUMBER = re.compile(r"(\d+(?:\.\d+)*)")
_CLAUSE = re.compile(r"^(>=|<=|==|!=|>|<|=|~=)\s*(.+)$")


def _parts(text: str) -> tuple[int, ...]:
    match = _NUMBER.search(str(text))
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _padded(
    left: tuple[int, ...], right: tuple[int, ...]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)), right + (0,) * (width - len(right))


def _compare(left: str, right: str) -> int:
    a, b = _padded(_parts(left), _parts(right))
    return (a > b) - (a < b)


def _fallback_satisfies(actual: str, spec: str) -> bool:
    for raw_clause in str(spec).split(","):
        clause = raw_clause.strip()
        if not clause:
            continue

        match = _CLAUSE.match(clause)
        operator, wanted = (match.group(1), match.group(2).strip()) if match else ("==", clause)
        if operator == "=":
            operator = "=="

        if operator == "~=":
            if _compare(actual, wanted) < 0:
                return False
            actual_parts, wanted_parts = _parts(actual), _parts(wanted)
            if (
                len(wanted_parts) >= 2
                and actual_parts[: len(wanted_parts) - 1] != wanted_parts[: len(wanted_parts) - 1]
            ):
                return False
            continue

        if operator == "==" and wanted.endswith(".*"):
            prefix = _parts(wanted[:-2])
            if _parts(actual)[: len(prefix)] != prefix:
                return False
            continue

        result = _compare(actual, wanted)
        if operator == ">=" and result < 0:
            return False
        if operator == ">" and result <= 0:
            return False
        if operator == "<=" and result > 0:
            return False
        if operator == "<" and result >= 0:
            return False
        if operator == "==" and result != 0:
            return False
        if operator == "!=" and result == 0:
            return False
    return True


def satisfies(actual: str, spec: str | None) -> bool:
    """Return True if `actual` satisfies the comma-separated version spec."""

    if not spec:
        return True

    if SpecifierSet is not None and Version is not None:
        try:
            return Version(str(actual)) in SpecifierSet(str(spec))
        except Exception:
            pass

    return _fallback_satisfies(str(actual), str(spec))
