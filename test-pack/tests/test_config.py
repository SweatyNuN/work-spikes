from __future__ import annotations

import pytest

from testpack.config import ConfigError, load_config, parse_overrides


def _config_file(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
testpack:
  default_timeout: 15
values:
  project_id: demo-project
  project_number: "123456"
  region: europe-west2
  zone: europe-west2-a
  bucket: "${project_id}-bucket"
  service_agent: "service-${project_number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
""",
        encoding="utf-8",
    )
    return path


def test_load_config_and_derive_values(tmp_path, monkeypatch):
    monkeypatch.delenv("TESTPACK_CONFIG", raising=False)
    path = _config_file(tmp_path)

    config = load_config(path, root=tmp_path)

    assert config.source == path
    assert config.default_timeout == 15
    assert config.values.get("bucket") == "demo-project-bucket"
    assert (
        config.values.get("service_agent")
        == "service-123456@gcp-sa-aiplatform.iam.gserviceaccount.com"
    )


def test_cli_overrides_win(tmp_path, monkeypatch):
    monkeypatch.delenv("TESTPACK_CONFIG", raising=False)
    path = _config_file(tmp_path)

    config = load_config(path, overrides={"region": "us-central1"}, root=tmp_path)

    assert config.values.get("region") == "us-central1"


def test_env_overrides_win_over_file(tmp_path, monkeypatch):
    monkeypatch.delenv("TESTPACK_CONFIG", raising=False)
    monkeypatch.setenv("TESTPACK_REGION", "asia-east1")
    path = _config_file(tmp_path)

    config = load_config(path, root=tmp_path)

    assert config.values.get("region") == "asia-east1"


def test_unknown_top_level_key_is_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv("TESTPACK_CONFIG", raising=False)
    path = tmp_path / "config.yml"
    path.write_text("project_id: demo\n", encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        load_config(path, root=tmp_path)
    assert "unexpected top-level key" in str(excinfo.value)


def test_missing_config_file_is_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv("TESTPACK_CONFIG", raising=False)
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yml", root=tmp_path)


def test_parse_overrides():
    assert parse_overrides(
        project_id="p",
        region="r",
        assignments=["bucket=b", "custom=value"],
    ) == {
        "project_id": "p",
        "region": "r",
        "bucket": "b",
        "custom": "value",
    }


def test_parse_overrides_rejects_bad_assignment():
    with pytest.raises(ConfigError):
        parse_overrides(assignments=["not-an-assignment"])
