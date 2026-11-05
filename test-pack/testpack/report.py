"""Console, JSON and JUnit reporting."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from . import __version__
from .models import FAIL, PASS, SKIP, Result

if TYPE_CHECKING:  # avoids importing PyYAML just to read the report module
    from .config import Config

_SECRET_KEY = re.compile(r"(SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|PRIVATE)", re.IGNORECASE)

_COLORS = {
    "red": "31",
    "green": "32",
    "yellow": "33",
    "cyan": "36",
    "dim": "2",
    "bold": "1",
}


class Style:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _wrap(self, name: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"\x1b[{_COLORS[name]}m{text}\x1b[0m"

    def bold(self, text: str) -> str:
        return self._wrap("bold", text)

    def dim(self, text: str) -> str:
        return self._wrap("dim", text)

    def green(self, text: str) -> str:
        return self._wrap("green", text)

    def red(self, text: str) -> str:
        return self._wrap("red", text)

    def yellow(self, text: str) -> str:
        return self._wrap("yellow", text)

    def cyan(self, text: str) -> str:
        return self._wrap("cyan", text)


@dataclass(frozen=True)
class Glyphs:
    passed: str
    failed: str
    warning: str
    skipped: str


_UNICODE = Glyphs("✓", "✗", "!", "–")
_ASCII = Glyphs("PASS", "FAIL", "WARN", "SKIP")


@dataclass
class Summary:
    passed: int
    failed: int
    warnings: int
    skipped: int
    critical_skipped: int
    duration: float

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.warnings + self.skipped

    @property
    def incomplete(self) -> bool:
        """True when nothing was actually verified (nothing ran or all skipped)."""
        return self.passed == 0 and self.failed == 0 and self.warnings == 0

    @property
    def ready(self) -> bool:
        return self.failed == 0 and not self.incomplete

    @property
    def has_warnings(self) -> bool:
        return self.warnings > 0


def summarize(results: Sequence[Result], duration: float = 0.0) -> Summary:
    return Summary(
        passed=sum(1 for result in results if result.status == PASS),
        failed=sum(1 for result in results if result.is_critical_failure),
        warnings=sum(1 for result in results if result.is_warning_failure),
        skipped=sum(1 for result in results if result.status == SKIP),
        critical_skipped=sum(
            1
            for result in results
            if result.status == SKIP and result.spec.enabled and not result.spec.is_warning
        ),
        duration=duration,
    )


def _use_color(explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _clip(text: str, max_lines: int, max_chars: int) -> str:
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n... (truncated)"
    lines = text.splitlines()
    if len(lines) > max_lines:
        hidden = len(lines) - max_lines
        lines = [*lines[:max_lines], f"... ({hidden} more line(s); use --verbose)"]
    return "\n".join(lines)


def _indent(text: str, spaces: int = 6) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.splitlines())


def _print_header(style: Style, config: "Config", plugins: Sequence[str]) -> None:
    print(style.bold(f"test-pack v{__version__}") + style.dim("  Vertex AI Workbench readiness"))
    print()

    resolved = config.values.resolved()
    rows = [
        ("project", resolved.get("project_id")),
        ("project number", resolved.get("project_number")),
        ("region", resolved.get("region")),
        ("zone", resolved.get("zone")),
        ("config", config.source_label),
    ]
    if plugins:
        rows.append(("plugins", ", ".join(plugins)))

    for label, value in rows:
        if value:
            print(f"  {label:<15} {value}")
        else:
            print(f"  {label:<15} {style.dim('(not set)')}")

    gcloud = shutil.which("gcloud")
    if gcloud:
        print(f"  {'gcloud':<15} {gcloud}")
    print()


def print_report(
    results: Sequence[Result],
    config: "Config",
    plugins: Sequence[str] = (),
    elapsed: float = 0.0,
    quiet: bool = False,
    ascii_only: bool = False,
    color: bool | None = None,
    verbose: bool = False,
) -> Summary:
    style = Style(_use_color(color))
    glyphs = _ASCII if ascii_only else _UNICODE
    summary = summarize(results, elapsed)

    _print_header(style, config, plugins)

    groups: dict[str, list[Result]] = {}
    for result in results:
        groups.setdefault(result.spec.category, []).append(result)

    for category, group in groups.items():
        visible = [
            result
            for result in group
            if not (quiet and result.status == PASS)
            and not (
                quiet
                and result.status == SKIP
                and result.outcome.message == "disabled in checks file"
            )
        ]
        if not visible:
            continue

        print(style.bold(category))
        width = min(max((len(result.spec.title) for result in visible), default=0), 58)
        for result in visible:
            _print_result(result, style, glyphs, width, verbose)
        print()

    _print_summary(summary, style, verbose)
    return summary


def _print_result(
    result: Result,
    style: Style,
    glyphs: Glyphs,
    width: int,
    verbose: bool,
) -> None:
    if result.status == PASS:
        line = f"  {style.green(glyphs.passed)} {result.spec.title.ljust(width)}"
        if result.outcome.message:
            line += "  " + style.dim(result.outcome.message)
        if verbose:
            line += "  " + style.dim(f"({result.duration:.2f}s)")
        print(line)
        return

    if result.status == SKIP:
        line = f"  {style.dim(glyphs.skipped)} {result.spec.title.ljust(width)}"
        if result.outcome.message:
            line += "  " + style.dim(result.outcome.message)
        print(line)
        if result.outcome.hint and verbose:
            print(style.dim(_indent(f"hint: {result.outcome.hint}")))
        return

    # Failure or warning.
    if result.is_warning_failure:
        symbol = style.yellow(glyphs.warning)
    else:
        symbol = style.red(glyphs.failed)
    print(f"  {symbol} {result.spec.title}")
    if result.outcome.message:
        print(_indent(result.outcome.message))
    if result.outcome.detail:
        detail = result.outcome.detail if verbose else _clip(result.outcome.detail, 15, 3000)
        print(style.dim(_indent(detail)))
    if result.outcome.hint:
        print(style.dim(_indent(f"hint: {result.outcome.hint}")))


def _print_summary(summary: Summary, style: Style, verbose: bool) -> None:
    print(style.dim("-" * 64))

    parts = [style.green(f"{summary.passed} passed")]
    if summary.failed:
        parts.append(style.red(f"{summary.failed} failed"))
    if summary.warnings:
        parts.append(style.yellow(f"{summary.warnings} warning(s)"))
    if summary.skipped:
        skipped = f"{summary.skipped} skipped"
        if summary.critical_skipped:
            skipped += f" ({summary.critical_skipped} critical)"
        parts.append(style.yellow(skipped) if summary.critical_skipped else style.dim(skipped))
    parts.append(style.dim(f"{summary.duration:.1f}s"))
    print("  " + " | ".join(parts))

    if summary.failed:
        print("  " + style.red(style.bold("RESULT: NOT READY")))
    elif summary.incomplete:
        print("  " + style.yellow(style.bold("RESULT: INCOMPLETE")))
        print(style.dim("  Nothing was verified: every selected check was skipped."))
    elif summary.has_warnings:
        print("  " + style.yellow(style.bold("RESULT: READY WITH WARNINGS")))
    else:
        print("  " + style.green(style.bold("RESULT: READY")))

    if summary.critical_skipped and verbose:
        print(
            style.yellow(
                "  Critical checks were skipped. Resolve their config or re-run with --strict "
                "to treat this as a failure."
            )
        )


def print_check_list(
    results: Sequence[Result],
    config: "Config",
    plugins: Sequence[str] = (),
    ascii_only: bool = False,
    color: bool | None = None,
) -> None:
    style = Style(_use_color(color))
    print(style.bold("test-pack") + style.dim("  check list"))
    print()

    width_id = max((len(result.spec.id) for result in results), default=8)
    width_id = min(max(width_id, 8), 36)
    for result in results:
        spec = result.spec
        state = f"{'enabled' if spec.enabled else 'disabled':<8}"
        state = style.dim(state) if spec.enabled else style.yellow(state)
        severity = f"{spec.severity:<8}"
        if spec.severity == "warning":
            severity = style.yellow(severity)
        print(
            f"  {spec.id:<{width_id}}  {spec.type:<22}  {severity}  {state}  "
            f"{style.dim(spec.category)}  {spec.title}"
        )
    print()
    print(
        style.dim(
            f"{len(results)} check(s) from {config.checks_dir}"
            + (f"; plugins: {', '.join(plugins)}" if plugins else "")
        )
    )


def _safe_values(config: "Config") -> dict:
    output = {}
    for key, value in config.values.resolved().items():
        if _SECRET_KEY.search(key):
            output[key] = "***"
        else:
            output[key] = value
    return output


def write_json(
    results: Sequence[Result],
    config: "Config",
    path: str | Path,
    elapsed: float = 0.0,
) -> None:
    summary = summarize(results, elapsed)
    payload = {
        "tool": "test-pack",
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": _safe_values(config),
        "summary": {
            "total": summary.total,
            "passed": summary.passed,
            "failed": summary.failed,
            "warnings": summary.warnings,
            "skipped": summary.skipped,
            "critical_skipped": summary.critical_skipped,
            "incomplete": summary.incomplete,
            "ready": summary.ready,
            "duration_s": round(elapsed, 4),
        },
        "checks": [
            {
                "id": result.spec.id,
                "title": result.spec.title,
                "type": result.spec.type,
                "category": result.spec.category,
                "severity": result.spec.severity,
                "tags": list(result.spec.tags),
                "status": result.status,
                "message": result.outcome.message,
                "detail": result.outcome.detail,
                "hint": result.outcome.hint,
                "duration_s": round(result.duration, 4),
                "source": result.spec.file,
            }
            for result in results
        ],
    }

    target = Path(path).expanduser()
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_junit(
    results: Sequence[Result],
    path: str | Path,
    elapsed: float = 0.0,
) -> None:
    summary = summarize(results, elapsed)

    suite = ET.Element(
        "testsuite",
        {
            "name": "test-pack",
            "tests": str(summary.total),
            "failures": str(summary.failed + summary.warnings),
            "errors": "0",
            "skipped": str(summary.skipped),
            "time": f"{elapsed:.3f}",
        },
    )
    suite.set("timestamp", datetime.now(timezone.utc).isoformat(timespec="seconds"))

    for result in results:
        spec = result.spec
        case = ET.SubElement(
            suite,
            "testcase",
            {
                "classname": spec.category,
                "name": spec.title,
                "time": f"{result.duration:.3f}",
            },
        )

        if result.status == FAIL:
            prefix = "[warning] " if result.is_warning_failure else ""
            failure = ET.SubElement(case, "failure", {"message": prefix + result.outcome.message})
            failure.text = result.outcome.detail or result.outcome.message
        elif result.status == SKIP:
            ET.SubElement(case, "skipped", {"message": result.outcome.message})

    ET.indent(suite, space="  ")
    target = Path(path).expanduser()
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suite).write(target, encoding="utf-8", xml_declaration=True)
