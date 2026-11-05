"""Configuration loading and value resolution.

The important idea is that a pack is reusable across environments. Values can
be:

  * literal              project_id: my-uat-project
  * discovered           project_id: auto
  * derived              bucket: "${project_id}-fucket"
  * overridden           python run.py --project-id my-uat-project

`auto` resolution uses, in order: environment variables, the GCE metadata
server, and the gcloud CLI. That means the same repo works on a laptop, in
Cloud Build, and inside a deployed workbench without editing YAML.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .interpolate import MissingValue, interpolate


def _detect_root() -> Path:
    """Find the directory that contains checks/ and plugins/.

    This supports three ways of running the pack:
      * from the repo (python run.py / python test-pack/run.py)
      * as an editable install (test-pack command)
      * from another project directory that has its own checks/ (TESTPACK_ROOT)
    """

    configured = os.environ.get("TESTPACK_ROOT")
    if configured:
        path = Path(configured).expanduser()
        return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()

    cwd = Path.cwd()
    if (cwd / "checks").is_dir():
        return cwd

    package_parent = Path(__file__).resolve().parent.parent
    if (package_parent / "checks").is_dir():
        return package_parent

    return cwd


TOOL_ROOT = _detect_root()

DEFAULT_SETTINGS: dict[str, Any] = {
    "checks_dir": "checks",
    "plugins_dir": "plugins",
    "default_timeout": 60,
}

# These defaults mirror ../platform-terraform so the pack works out of the box
# against the Terraform in this repo. Override them in config.yml.
DEFAULT_VALUES: dict[str, Any] = {
    "project_id": "auto",
    "project_number": "auto",
    "region": "auto",
    "zone": "auto",
    "bucket": "${project_id}-fucket",
    "kms_keyring": "vertex-keyring",
    "kms_key": "vertex-cmek",
    "kms_location": "${region}",
    "expected_user": "",
    "service_agent": "service-${project_number}@gcp-sa-aiplatform.iam.gserviceaccount.com",
    "compute_service_account": "${project_number}-compute@developer.gserviceaccount.com",
    # Private Service Connect for Vertex AI Pipelines. Empty values skip the
    # PSC checks; set them to the platform-terraform outputs to enable them.
    "psc_network_attachment": "",
    "psc_subnet": "",
    "psc_network": "",
    "psc_region": "${region}",
    "psc_connection_preference": "ACCEPT_AUTOMATIC",
    # Optional: a compiled pipeline template for the real PSC pipeline run.
    "pipeline_template": "",
    "pipeline_root": "gs://${bucket}/pipeline-root",
    "pipeline_service_account": "",
}

_ENV_OVERRIDES = {
    "TESTPACK_PROJECT_ID": "project_id",
    "TESTPACK_PROJECT_NUMBER": "project_number",
    "TESTPACK_REGION": "region",
    "TESTPACK_ZONE": "zone",
}

_METADATA_ROOT = "http://metadata.google.internal/computeMetadata/v1"
_metadata_cache: dict[str, str | None] = {}


class ConfigError(Exception):
    """A problem the user can fix in config.yml or on the command line."""


class Values:
    """Config values with recursive ${...} interpolation and cycle detection."""

    def __init__(self, raw: Mapping[str, Any]):
        self._raw = dict(raw)
        self._cache: dict[str, Any] = {}
        self._stack: list[str] = []

    def get(self, key: str) -> Any:
        if key in self._cache:
            return self._cache[key]
        if key not in self._raw:
            raise MissingValue(key)

        raw = self._raw[key]
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            raise MissingValue(key)

        if key in self._stack:
            cycle = " -> ".join([*self._stack, key])
            raise MissingValue(key, f"has a circular reference ({cycle})")

        self._stack.append(key)
        try:
            value = interpolate(raw, self)
        finally:
            self._stack.pop()

        if isinstance(value, str) and value.strip().lower() == "auto":
            raise MissingValue(key, "could not be auto-detected")

        self._cache[key] = value
        return value

    def try_get(self, key: str, default: Any = None) -> Any:
        try:
            return self.get(key)
        except MissingValue:
            return default

    def resolved(self) -> dict[str, Any]:
        """Every value that can currently be resolved. Unresolved ones are omitted."""
        output: dict[str, Any] = {}
        for key in self._raw:
            try:
                output[key] = self.get(key)
            except MissingValue:
                continue
        return output

    def missing(self) -> list[str]:
        missing: list[str] = []
        for key in self._raw:
            try:
                self.get(key)
            except MissingValue:
                missing.append(key)
        return missing


@dataclass
class Config:
    values: Values
    raw_values: dict[str, Any]
    settings: dict[str, Any]
    root: Path
    source: Path | None = None

    @property
    def source_label(self) -> str:
        return str(self.source) if self.source else "(built-in defaults)"

    def dir_path(self, setting: str, default: str) -> Path:
        raw = str(self.settings.get(setting, default))
        path = Path(raw).expanduser()
        return path if path.is_absolute() else (self.root / path)

    @property
    def checks_dir(self) -> Path:
        return self.dir_path("checks_dir", "checks")

    @property
    def plugins_dir(self) -> Path:
        return self.dir_path("plugins_dir", "plugins")

    @property
    def default_timeout(self) -> float:
        try:
            return float(self.settings.get("default_timeout", 60))
        except (TypeError, ValueError):
            return 60.0


# ---------------------------------------------------------------------------
# Auto discovery
# ---------------------------------------------------------------------------


def _is_auto(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() == "auto"


def _literal(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or "${" in value:
        return None
    return value


def _metadata(path: str, timeout: float = 1.0) -> str | None:
    if path in _metadata_cache:
        return _metadata_cache[path]

    request = urllib.request.Request(
        f"{_METADATA_ROOT}/{path.lstrip('/')}",
        headers={"Metadata-Flavor": "Google"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = response.read().decode("utf-8", "replace").strip()
    except Exception:
        value = None

    _metadata_cache[path] = value or None
    return _metadata_cache[path]


def _gcloud_value(*args: str, timeout: float = 10.0) -> str | None:
    executable = shutil.which("gcloud")
    if executable is None:
        return None
    try:
        proc = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    if not value or value in {"(unset)", "None", "null"}:
        return None
    return value


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _detect_project_id() -> str | None:
    return (
        _first_env("GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT", "CLOUDSDK_CORE_PROJECT")
        or _metadata("project/project-id")
        or _gcloud_value("config", "get-value", "project")
    )


def _detect_project_number(project_id: str | None) -> str | None:
    from_env = _first_env("GOOGLE_CLOUD_PROJECT_NUMBER", "TESTPACK_PROJECT_NUMBER")
    if from_env:
        return from_env
    from_metadata = _metadata("project/numeric-project-id")
    if from_metadata:
        return from_metadata

    project = _literal(project_id)
    if not project:
        return None
    return _gcloud_value(
        "projects",
        "describe",
        project,
        "--format=value(projectNumber)",
        "--quiet",
    )


def _detect_zone() -> str | None:
    zone = _first_env("GOOGLE_CLOUD_ZONE", "CLOUDSDK_COMPUTE_ZONE")
    if zone:
        return zone

    from_metadata = _metadata("instance/zone")
    if from_metadata:
        return from_metadata.rsplit("/", 1)[-1]

    return _gcloud_value("config", "get-value", "compute/zone")


def _detect_region(zone: str | None) -> str | None:
    region = _first_env("GOOGLE_CLOUD_REGION", "CLOUDSDK_COMPUTE_REGION")
    if region:
        return region

    from_gcloud = _gcloud_value("config", "get-value", "compute/region")
    if from_gcloud:
        return from_gcloud

    # europe-west2-a -> europe-west2
    if zone:
        separator = zone.rfind("-")
        if separator > 0:
            return zone[:separator]
    return None


def _detect_account() -> str | None:
    account = _gcloud_value("config", "get-value", "account")
    # A workbench VM usually runs as a service account; that is not a "user"
    # for IAM binding purposes, so leave expected_user unset in that case.
    if account and account.strip().endswith(".gserviceaccount.com"):
        return None
    return account


def _resolve_autos(raw: dict[str, Any]) -> None:
    if _is_auto(raw.get("project_id")):
        raw["project_id"] = _detect_project_id()

    if _is_auto(raw.get("project_number")):
        raw["project_number"] = _detect_project_number(raw.get("project_id"))

    if _is_auto(raw.get("zone")):
        raw["zone"] = _detect_zone()

    if _is_auto(raw.get("region")):
        raw["region"] = _detect_region(raw.get("zone"))

    if _is_auto(raw.get("expected_user")):
        raw["expected_user"] = _detect_account()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _read_yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc

    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse {path}: {exc}") from exc


def _discover_config(root: Path) -> Path | None:
    from_env = os.environ.get("TESTPACK_CONFIG")
    if from_env:
        path = Path(from_env).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        if not path.exists():
            raise ConfigError(f"TESTPACK_CONFIG points to a missing file: {path}")
        return path

    for name in ("config.yml", "config.yaml"):
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def load_config(
    config_path: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    root: Path | None = None,
) -> Config:
    """Load config.yml (if present), merge defaults and overrides, resolve autos."""

    root = Path(root) if root else TOOL_ROOT
    overrides = dict(overrides or {})

    source: Path | None
    if config_path:
        source = Path(config_path).expanduser()
        if not source.is_absolute():
            source = (Path.cwd() / source).resolve()
        if not source.exists():
            raise ConfigError(f"config file not found: {source}")
    else:
        source = _discover_config(root)

    file_values: dict[str, Any] = {}
    file_settings: dict[str, Any] = {}

    if source is not None:
        loaded = _read_yaml(source)
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise ConfigError(
                f"{source}: expected a mapping at the top level. "
                "Put your values under a 'values:' key."
            )

        unexpected = set(loaded) - {"testpack", "values"}
        if unexpected:
            raise ConfigError(
                f"{source}: unexpected top-level key(s): {', '.join(sorted(unexpected))}. "
                "Use 'testpack:' for runner settings and 'values:' for your own values."
            )

        file_settings = loaded.get("testpack") or {}
        file_values = loaded.get("values") or {}
        if not isinstance(file_settings, dict):
            raise ConfigError(f"{source}: 'testpack' must be a mapping")
        if not isinstance(file_values, dict):
            raise ConfigError(f"{source}: 'values' must be a mapping")

    raw: dict[str, Any] = dict(DEFAULT_VALUES)
    raw.update(file_values)

    # Environment overrides win over the file, so CI can call the same pack
    # without rewriting config.yml.
    for env_name, key in _ENV_OVERRIDES.items():
        value = os.environ.get(env_name)
        if value:
            raw[key] = value

    raw.update(overrides)

    settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
    settings.update(file_settings)

    _resolve_autos(raw)

    return Config(
        values=Values(raw),
        raw_values=raw,
        settings=settings,
        root=root,
        source=source,
    )


def parse_overrides(
    project_id: str | None = None,
    project_number: str | None = None,
    region: str | None = None,
    zone: str | None = None,
    assignments: list[str] | None = None,
) -> dict[str, Any]:
    """Turn CLI flags and --set key=value pairs into a values override dict."""

    overrides: dict[str, Any] = {}
    for key, value in (
        ("project_id", project_id),
        ("project_number", project_number),
        ("region", region),
        ("zone", zone),
    ):
        if value:
            overrides[key] = value

    for item in assignments or []:
        if "=" not in item:
            raise ConfigError(f"--set expects KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ConfigError(f"--set expects KEY=VALUE, got {item!r}")
        overrides[key] = value

    return overrides
