from __future__ import annotations

import sys
from pathlib import Path

from testpack import checkers  # noqa: F401  (registers built-in types)
from testpack.config import Config, Values
from testpack.context import Context
from testpack.models import CheckSpec
from testpack.registry import check
from testpack.runner import run_checks, run_one, select_specs


def _context(tmp_path: Path, values: dict | None = None) -> Context:
    config = Config(
        values=Values(values or {}),
        raw_values=values or {},
        settings={},
        root=tmp_path,
    )
    return Context(config, root=tmp_path)


def _spec(**overrides) -> CheckSpec:
    data = {
        "id": "demo",
        "title": "Demo check",
        "type": "command",
        "params": {"command": [sys.executable, "-c", "print('hello')"]},
    }
    data.update(overrides)
    return CheckSpec(**data)


def test_command_passes(tmp_path):
    result = run_one(
        _spec(
            params={"command": [sys.executable, "-c", "print('hello')"], "stdout_contains": "hello"}
        ),
        _context(tmp_path),
    )
    assert result.status == "pass"
    assert "hello" not in result.outcome.message  # value is in detail, not message


def test_command_failure_reports_exit_code(tmp_path):
    result = run_one(
        _spec(params={"command": [sys.executable, "-c", "import sys; sys.exit(3)"]}),
        _context(tmp_path),
    )
    assert result.status == "fail"
    assert "exited 3" in result.outcome.message


def test_expected_non_zero_exit(tmp_path):
    result = run_one(
        _spec(
            params={
                "command": [sys.executable, "-c", "import sys; sys.exit(3)"],
                "expect_exit": 3,
            }
        ),
        _context(tmp_path),
    )
    assert result.status == "pass"


def test_check_level_timeout_is_applied(tmp_path):
    result = run_one(
        _spec(
            timeout=0.1,
            params={"command": [sys.executable, "-c", "import time; time.sleep(2)"]},
        ),
        _context(tmp_path),
    )
    assert result.status == "fail"
    assert "timed out" in result.outcome.message


def test_missing_config_value_skips(tmp_path):
    result = run_one(
        _spec(params={"command": ["echo", "${expected_user}"]}),
        _context(tmp_path),
    )
    assert result.status == "skip"
    assert "expected_user" in result.outcome.message


def test_selection_by_tag_and_substring():
    specs = [
        _spec(id="gcp.one", tags=("gcp",)),
        _spec(id="python.two", tags=("python",)),
        _spec(id="workbench.three", tags=("jupyter",)),
    ]

    assert [spec.id for spec in select_specs(specs, only=["gcp"])] == ["gcp.one"]
    assert [spec.id for spec in select_specs(specs, only=["two"])] == ["python.two"]
    assert [spec.id for spec in select_specs(specs, skip=["jupyter"])] == ["gcp.one", "python.two"]


def test_disabled_checks_are_skipped(tmp_path):
    result = run_one(_spec(enabled=False), _context(tmp_path))
    # run_one does not enforce `enabled`; run_checks does. That keeps run_one
    # useful for tests while the runner owns the policy.
    assert result.status == "pass"

    results = run_checks([_spec(enabled=False)], _context(tmp_path))
    assert results[0].status == "skip"
    assert results[0].outcome.message == "disabled in checks file"


def test_crashing_plugin_becomes_a_failure(tmp_path):
    @check("testpack_crashing_check", "test only")
    def crashing(ctx, params):
        raise RuntimeError("boom")

    result = run_one(_spec(type="testpack_crashing_check", params={}), _context(tmp_path))
    assert result.status == "fail"
    assert "RuntimeError" in result.outcome.message


def test_fail_fast_stops_after_first_failure(tmp_path):
    specs = [
        _spec(id="first", params={"command": [sys.executable, "-c", "import sys; sys.exit(1)"]}),
        _spec(id="second"),
    ]
    results = run_checks(specs, _context(tmp_path), fail_fast=True)
    assert len(results) == 1
    assert results[0].status == "fail"
