"""Checks about the operating system, files, environment variables and network."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request

from ..models import Outcome
from ..registry import check

_SECRET_NAME = re.compile(r"(SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|PRIVATE)", re.IGNORECASE)


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


@check("command", "Run a command and assert on its exit code or output")
def command(ctx, params):
    raw = params.get("command")
    if not raw:
        return Outcome.fail("check is missing the 'command' param")

    timeout = params.get("timeout") or ctx.default_timeout
    cwd = ctx.resolve_path(params["cwd"]) if params.get("cwd") else None
    result = ctx.run(
        raw,
        timeout=timeout,
        cwd=cwd,
        env=params.get("env"),
        shell=params.get("shell"),
    )

    if result.error:
        return Outcome.fail(
            f"could not run command: {result.error}",
            detail=result.detail(),
        )
    if result.timed_out:
        return Outcome.fail(
            f"command timed out after {float(timeout):g}s",
            detail=result.detail(),
        )

    expected = params.get("expect_exit", params.get("exit_code", 0))
    try:
        expected_codes = (
            {int(item) for item in expected}
            if isinstance(expected, (list, tuple, set))
            else {int(expected)}
        )
    except (TypeError, ValueError):
        return Outcome.fail("check has an invalid 'expect_exit' value")

    if result.returncode not in expected_codes:
        return Outcome.fail(
            f"command exited {result.returncode} (expected {sorted(expected_codes)})",
            detail=result.detail(),
        )

    problems: list[str] = []
    for needle in _as_list(params.get("stdout_contains")):
        if needle not in result.stdout:
            problems.append(f"stdout does not contain {needle!r}")
    for needle in _as_list(params.get("stdout_not_contains")):
        if needle in result.stdout:
            problems.append(f"stdout unexpectedly contains {needle!r}")
    for needle in _as_list(params.get("stderr_contains")):
        if needle not in result.stderr:
            problems.append(f"stderr does not contain {needle!r}")

    stdout_regex = params.get("stdout_regex")
    if stdout_regex:
        try:
            if re.search(str(stdout_regex), result.stdout, re.MULTILINE) is None:
                problems.append(f"stdout does not match /{stdout_regex}/")
        except re.error as exc:
            return Outcome.fail(f"invalid stdout_regex: {exc}")

    if problems:
        return Outcome.fail("; ".join(problems), detail=result.detail())

    message = str(params.get("message") or f"command exited {result.returncode}")
    if params.get("show_output"):
        first_line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
        if first_line:
            message += f": {first_line[:120]}"

    return Outcome.ok(message, detail=result.detail())


@check("file", "Assert a file or directory exists and optionally contains text")
def file_check(ctx, params):
    raw_path = params.get("path")
    if not raw_path:
        return Outcome.fail("check is missing the 'path' param")

    path = ctx.resolve_path(raw_path)
    should_exist = bool(params.get("exists", True))
    exists = path.exists()

    if should_exist and not exists:
        return Outcome.fail(f"{path} does not exist")
    if not should_exist and exists:
        return Outcome.fail(f"{path} exists but should not")
    if not exists:
        return Outcome.ok(f"{path} does not exist (as expected)")

    kind = params.get("kind")
    if kind == "file" and not path.is_file():
        return Outcome.fail(f"{path} is not a regular file")
    if kind == "directory" and not path.is_dir():
        return Outcome.fail(f"{path} is not a directory")

    size = path.stat().st_size
    if params.get("min_bytes") is not None and size < int(params["min_bytes"]):
        return Outcome.fail(
            f"{path} is {_human_size(size)}, "
            f"expected at least {_human_size(int(params['min_bytes']))}"
        )
    if params.get("max_bytes") is not None and size > int(params["max_bytes"]):
        return Outcome.fail(
            f"{path} is {_human_size(size)}, "
            f"expected at most {_human_size(int(params['max_bytes']))}"
        )

    assertions = any(params.get(key) is not None for key in ("contains", "not_contains", "regex"))

    if assertions:
        if not path.is_file():
            return Outcome.fail(f"cannot inspect the contents of {path}: not a regular file")
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return Outcome.fail(f"could not read {path}", detail=str(exc))

        problems: list[str] = []
        for needle in _as_list(params.get("contains")):
            if needle not in text:
                problems.append(f"does not contain {needle!r}")
        for needle in _as_list(params.get("not_contains")):
            if needle in text:
                problems.append(f"unexpectedly contains {needle!r}")
        if params.get("regex"):
            try:
                if re.search(str(params["regex"]), text, re.MULTILINE) is None:
                    problems.append(f"does not match /{params['regex']}/")
            except re.error as exc:
                return Outcome.fail(f"invalid regex: {exc}")

        if problems:
            return Outcome.fail(f"{path} " + "; ".join(problems))

    return Outcome.ok(f"{path} ({_human_size(size)})")


@check("env", "Assert an environment variable is set (and optionally its value)")
def env_check(ctx, params):
    name = params.get("name")
    if not name:
        return Outcome.fail("check is missing the 'name' param")

    name = str(name)
    value = os.environ.get(name)
    present = value is not None
    should_be_present = bool(params.get("present", True))

    if should_be_present and not present:
        return Outcome.fail(
            f"{name} is not set",
            hint=f"export {name}=... or set it on the workbench instance.",
        )
    if not should_be_present and present:
        return Outcome.fail(f"{name} is set but should not be")

    if not present:
        return Outcome.ok(f"{name} is not set (as expected)")

    problems: list[str] = []
    expected = params.get("equals")
    if expected is not None and value != str(expected):
        problems.append(f"does not equal {expected!r}")

    for needle in _as_list(params.get("contains")):
        if needle not in value:
            problems.append(f"does not contain {needle!r}")

    one_of = params.get("one_of")
    if one_of is not None and value not in {str(item) for item in _as_list(one_of)}:
        problems.append(f"is not one of {_as_list(one_of)}")

    if params.get("regex"):
        try:
            if re.search(str(params["regex"]), value) is None:
                problems.append(f"does not match /{params['regex']}/")
        except re.error as exc:
            return Outcome.fail(f"invalid regex: {exc}")

    secret = bool(params.get("secret")) or bool(_SECRET_NAME.search(name))
    shown = "***" if secret else (value[:80] + ("..." if len(value) > 80 else ""))
    if problems:
        return Outcome.fail(f"{name} " + "; ".join(problems), detail=f"{name}={shown}")

    return Outcome.ok(f"{name}={shown}")


@check("http", "Call an HTTP endpoint and assert the response")
def http_check(ctx, params):
    url = params.get("url")
    if not url:
        return Outcome.fail("check is missing the 'url' param")

    method = str(params.get("method", "GET")).upper()
    expected = params.get("status", params.get("expect_status", 200))
    allowed = (
        {int(item) for item in expected}
        if isinstance(expected, (list, tuple, set))
        else {int(expected)}
    )
    timeout = float(params.get("timeout") or min(ctx.default_timeout, 15))

    headers = {"User-Agent": "test-pack/1.0"}
    headers.update({str(key): str(value) for key, value in (params.get("headers") or {}).items()})

    body = params.get("body")
    request = urllib.request.Request(
        str(url),
        data=body.encode("utf-8") if isinstance(body, str) else body,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            text = response.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        text = exc.read(200_000).decode("utf-8", "replace") if exc.fp else ""
    except Exception as exc:
        return Outcome.fail(
            f"{method} {url} failed",
            detail=f"{type(exc).__name__}: {exc}",
            hint="Check the URL, DNS and any proxy settings on the workbench.",
        )

    if status not in allowed:
        return Outcome.fail(
            f"{method} {url} returned {status} (expected {sorted(allowed)})",
            detail=text[:2000],
        )

    problems: list[str] = []
    for needle in _as_list(params.get("contains")):
        if needle not in text:
            problems.append(f"body does not contain {needle!r}")
    if params.get("body_regex"):
        try:
            if re.search(str(params["body_regex"]), text, re.MULTILINE) is None:
                problems.append(f"body does not match /{params['body_regex']}/")
        except re.error as exc:
            return Outcome.fail(f"invalid body_regex: {exc}")

    if problems:
        return Outcome.fail("; ".join(problems), detail=text[:2000])

    return Outcome.ok(f"{method} {url} -> {status}")


@check("gpu", "Assert an NVIDIA GPU is visible")
def gpu(ctx, params):
    optional = bool(params.get("optional", False))
    result = ctx.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
        timeout=15,
    )

    if not result.ok:
        if optional:
            return Outcome.skip("no NVIDIA GPU detected (optional)")
        return Outcome.fail(
            "nvidia-smi is not available or failed",
            detail=result.detail(),
            hint="Attach a GPU to the workbench, or set params.optional: true.",
        )

    devices: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        devices.append((parts[0], parts[1] if len(parts) > 1 else ""))

    name_contains = params.get("name_contains")
    matching = [
        device
        for device in devices
        if not name_contains or str(name_contains).casefold() in device[0].casefold()
    ]

    minimum = int(params.get("min_count", 1))
    if len(matching) < minimum:
        if optional:
            return Outcome.skip(
                f"{len(matching)} matching GPU(s), expected at least {minimum} (optional)"
            )
        return Outcome.fail(
            f"{len(matching)} matching GPU(s), expected at least {minimum}",
            detail=", ".join(name for name, _ in devices) or "none",
        )

    names = ", ".join(f"{name} ({memory} MiB)" if memory else name for name, memory in matching)
    return Outcome.ok(f"{len(matching)} GPU(s): {names}")


@check("disk", "Assert a path is writable and has free space")
def disk(ctx, params):
    path = ctx.resolve_path(params.get("path", "~"))

    target = path
    while not target.exists() and target != target.parent:
        target = target.parent
    if not target.exists():
        return Outcome.fail(f"none of {path} or its parents exist")
    if target.is_file():
        target = target.parent

    writable = bool(params.get("writable", True))
    if writable:
        try:
            with tempfile.NamedTemporaryFile(
                dir=target, prefix=".testpack-", delete=True
            ) as handle:
                handle.write(b"ok")
                handle.flush()
        except OSError as exc:
            return Outcome.fail(
                f"{target} is not writable",
                detail=f"{type(exc).__name__}: {exc}",
                hint=(
                    "Check mount permissions, disk quota, or whether the "
                    "persistent disk is attached."
                ),
            )

    try:
        usage = shutil.disk_usage(target)
    except OSError as exc:
        return Outcome.fail(f"could not read disk usage for {target}", detail=str(exc))

    free_gb = usage.free / 1_000_000_000
    minimum = params.get("min_free_gb")
    if minimum is not None and free_gb < float(minimum):
        return Outcome.fail(
            f"{target} has {free_gb:.1f} GB free, expected at least {float(minimum):g} GB",
            hint="Clean up the workbench disk or resize it.",
        )

    suffix = ", writable" if writable else ""
    return Outcome.ok(f"{target}: {free_gb:.1f} GB free{suffix}")
