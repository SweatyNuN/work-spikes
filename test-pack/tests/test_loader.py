from __future__ import annotations

import pytest

from testpack import checkers  # noqa: F401  (registers built-in types)
from testpack.loader import LoadError, load_checks


def _write(path, text):
    path.write_text(text, encoding="utf-8")


def test_loads_checks_and_defaults(tmp_path):
    _write(
        tmp_path / "checks.yml",
        """
category: Demo
defaults:
  severity: warning
  tags: [demo]
checks:
  - title: Python runs
    type: command
    params:
      command: ["python", "-c", "print('ok')"]
""",
    )

    specs = load_checks(tmp_path, default_timeout=30)

    assert len(specs) == 1
    spec = specs[0]
    assert spec.id == "python-runs"
    assert spec.category == "Demo"
    assert spec.severity == "warning"
    assert spec.tags == ("demo",)
    assert spec.timeout == 30
    assert spec.enabled is True
    assert spec.file == "checks.yml"


def test_unknown_check_type_has_a_useful_message(tmp_path):
    _write(
        tmp_path / "checks.yml",
        """
checks:
  - title: Nope
    type: not_a_real_check
""",
    )

    with pytest.raises(LoadError) as excinfo:
        load_checks(tmp_path)
    assert "unknown check type 'not_a_real_check'" in str(excinfo.value)
    assert "command" in str(excinfo.value)


def test_unknown_key_is_rejected(tmp_path):
    _write(
        tmp_path / "checks.yml",
        """
checks:
  - title: Typo
    type: command
    param:
      command: ["true"]
""",
    )

    with pytest.raises(LoadError) as excinfo:
        load_checks(tmp_path)
    assert "unknown key(s): param" in str(excinfo.value)


def test_duplicate_ids_are_rejected(tmp_path):
    _write(
        tmp_path / "a.yml",
        """
checks:
  - id: same
    title: One
    type: command
""",
    )
    _write(
        tmp_path / "b.yml",
        """
checks:
  - id: same
    title: Two
    type: command
""",
    )

    with pytest.raises(LoadError) as excinfo:
        load_checks(tmp_path)
    assert "duplicate check id 'same'" in str(excinfo.value)


def test_empty_directory_is_an_error(tmp_path):
    with pytest.raises(LoadError):
        load_checks(tmp_path)
