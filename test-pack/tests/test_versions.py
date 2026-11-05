from __future__ import annotations

import pytest

from testpack.versions import satisfies


@pytest.mark.parametrize(
    "actual,spec,expected",
    [
        ("3.11.9", ">=3.10", True),
        ("3.9.18", ">=3.10", False),
        ("1.70.0", ">=1.60,<2", True),
        ("2.0.0", ">=1.60,<2", False),
        ("3.11.9", "==3.11.*", True),
        ("3.12.0", "==3.11.*", False),
        ("6.29.5", "!=6.30", True),
        ("2.0.0", "~=2.0.0", True),
        ("3.0.0", "~=2.0.0", False),
        ("1.0", None, True),
    ],
)
def test_satisfies(actual, spec, expected):
    assert satisfies(actual, spec) is expected
