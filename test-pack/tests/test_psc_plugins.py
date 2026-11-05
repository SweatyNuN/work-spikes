"""Tests for the bundled PSC plugin that do not need a live GCP project.

These are skipped when the optional `gcp` extra is not installed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("google.cloud.aiplatform_v1")

_PLUGIN = Path(__file__).resolve().parent.parent / "plugins" / "vertex_pipeline_psc.py"
_SPEC = importlib.util.spec_from_file_location("testpack_psc_plugin_under_test", _PLUGIN)
assert _SPEC is not None and _SPEC.loader is not None
psc_plugin = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(psc_plugin)


class StubContext:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_sdk_supports_psc():
    outcome = psc_plugin.vertex_psc_sdk(
        StubContext({"project_id": "demo", "region": "europe-west2"}),
        {
            "network_attachment": (
                "projects/demo/regions/europe-west2/networkAttachments/vertex-psc-attachment"
            )
        },
    )

    assert outcome.status == "pass"
    assert "supports PSC-I" in outcome.message
    assert "vertex-psc-attachment" in outcome.detail


def test_sdk_skips_without_attachment():
    outcome = psc_plugin.vertex_psc_sdk(StubContext(), {})

    assert outcome.status == "skip"
    assert "psc_network_attachment" in outcome.message


def test_pipeline_check_skips_without_configuration():
    outcome = psc_plugin.vertex_pipeline_psc(StubContext(), {})

    assert outcome.status == "skip"
    assert "pipeline_template" in outcome.message
