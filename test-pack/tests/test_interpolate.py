from __future__ import annotations

import pytest

from testpack.config import Values
from testpack.interpolate import MissingValue, interpolate


def test_simple_interpolation():
    values = Values({"project_id": "demo"})
    assert interpolate("${project_id}-bucket", values) == "demo-bucket"


def test_fallback():
    values = Values({})
    assert interpolate("${missing:-fallback}", values) == "fallback"


def test_env_fallback(monkeypatch):
    monkeypatch.delenv("TESTPACK_TEST_VAR", raising=False)
    values = Values({})
    assert interpolate("${env:TESTPACK_TEST_VAR:-local}", values) == "local"

    monkeypatch.setenv("TESTPACK_TEST_VAR", "from-env")
    assert interpolate("${env:TESTPACK_TEST_VAR}", values) == "from-env"


def test_missing_raises():
    with pytest.raises(MissingValue):
        interpolate("${missing}", Values({}))


def test_derived_values():
    values = Values(
        {
            "project_number": "123",
            "service_agent": "service-${project_number}@example.iam.gserviceaccount.com",
        }
    )
    assert values.get("service_agent") == "service-123@example.iam.gserviceaccount.com"


def test_empty_value_counts_as_missing():
    with pytest.raises(MissingValue):
        Values({"expected_user": ""}).get("expected_user")


def test_circular_reference():
    values = Values({"a": "${b}", "b": "${a}"})
    with pytest.raises(MissingValue):
        values.get("a")


def test_resolved_omits_unresolved():
    values = Values({"project_id": "demo", "bucket": "${project_id}-x", "bad": "${nope}"})
    assert values.resolved() == {"project_id": "demo", "bucket": "demo-x"}
    assert values.missing() == ["bad"]
