from __future__ import annotations

import sys
from pathlib import Path

from testpack.config import Config, Values
from testpack.context import Context


def _context(tmp_path: Path) -> Context:
    config = Config(values=Values({}), raw_values={}, settings={}, root=tmp_path)
    return Context(config, root=tmp_path)


def test_missing_working_directory(tmp_path):
    result = _context(tmp_path).run(["true"], cwd=tmp_path / "nope")
    assert not result.ok
    assert "working directory not found" in result.error


def test_list_with_shell_is_joined(tmp_path):
    result = _context(tmp_path).run(["echo", "hello world"], shell=True)
    assert result.ok
    assert "hello world" in result.stdout.strip()


def test_timeout_is_reported(tmp_path):
    result = _context(tmp_path).run(
        [sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.1
    )
    assert not result.ok
    assert result.timed_out
    assert result.returncode == 124
