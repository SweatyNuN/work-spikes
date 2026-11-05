"""Run checks and turn their outcomes into results."""

from __future__ import annotations

import time
import traceback
from typing import Iterable, Sequence

from .context import Context
from .interpolate import MissingValue, interpolate
from .models import FAIL, CheckSpec, Outcome, Result
from .registry import get_check


def select_specs(
    specs: Sequence[CheckSpec],
    only: Iterable[str] = (),
    skip: Iterable[str] = (),
) -> list[CheckSpec]:
    """Filter checks by id, id substring, tag, type or category."""

    only = tuple(only)
    skip = tuple(skip)

    def matches(spec: CheckSpec, selectors: Sequence[str]) -> bool:
        for selector in selectors:
            selector = selector.strip()
            if not selector:
                continue
            if selector in {spec.id, spec.type, spec.category}:
                return True
            if selector in spec.tags:
                return True
            if selector.casefold() in spec.id.casefold():
                return True
        return False

    selected: list[CheckSpec] = []
    for spec in specs:
        if only and not matches(spec, only):
            continue
        if skip and matches(spec, skip):
            continue
        selected.append(spec)
    return selected


def _safe_interpolate(value, ctx: Context):
    try:
        return interpolate(value, ctx.values)
    except MissingValue:
        return value


def run_checks(
    specs: Sequence[CheckSpec],
    ctx: Context,
    only: Iterable[str] = (),
    skip: Iterable[str] = (),
    fail_fast: bool = False,
) -> list[Result]:
    results: list[Result] = []

    for spec in select_specs(specs, only=only, skip=skip):
        if not spec.enabled:
            results.append(Result(spec, Outcome.skip("disabled in checks file")))
            continue

        result = run_one(spec, ctx)
        results.append(result)

        if fail_fast and result.status == FAIL:
            break

    return results


def run_one(spec: CheckSpec, ctx: Context) -> Result:
    started = time.perf_counter()

    # Parameters are interpolated at run time so a missing config value can
    # turn into a clear SKIP rather than blocking the whole pack at load time.
    try:
        params = interpolate(spec.params, ctx.values)
        # Make the check-level timeout the default for checkers that run
        # commands, unless the check itself set params.timeout.
        if spec.timeout is not None and isinstance(params, dict):
            params.setdefault("timeout", spec.timeout)
    except MissingValue as exc:
        return Result(
            spec,
            Outcome.skip(
                f"needs config value '{exc.key}'",
                hint=spec.hint or f"Set '{exc.key}' in config.yml or pass --set {exc.key}=...",
            ),
            time.perf_counter() - started,
        )

    title = _safe_interpolate(spec.title, ctx)
    hint = _safe_interpolate(spec.hint, ctx) if spec.hint else ""

    registered = get_check(spec.type)
    if registered is None:  # loader normally prevents this
        return Result(
            spec,
            Outcome.fail(f"unknown check type '{spec.type}'"),
            time.perf_counter() - started,
        )

    try:
        outcome = registered.function(ctx, params)
        if not isinstance(outcome, Outcome):
            raise TypeError(
                f"check type '{spec.type}' returned {type(outcome).__name__}, expected Outcome"
            )
    except MissingValue as exc:
        outcome = Outcome.skip(f"needs config value '{exc.key}'")
    except Exception as exc:
        detail = traceback.format_exc() if ctx.verbose else f"{type(exc).__name__}: {exc}"
        outcome = Outcome.fail(
            f"check crashed: {type(exc).__name__}: {exc}",
            detail=detail,
            hint="This is a bug in the check, not necessarily a problem with the environment.",
        )

    if outcome.status == FAIL and not outcome.hint and hint:
        outcome.hint = hint

    # A title can legitimately contain placeholders; keep the resolved form in
    # the report without mutating the spec.
    if title != spec.title:
        spec = CheckSpec(
            id=spec.id,
            title=title,
            type=spec.type,
            params=spec.params,
            category=spec.category,
            severity=spec.severity,
            tags=spec.tags,
            timeout=spec.timeout,
            enabled=spec.enabled,
            hint=spec.hint,
            file=spec.file,
        )

    return Result(spec, outcome, time.perf_counter() - started)
