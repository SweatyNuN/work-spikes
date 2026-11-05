#!/usr/bin/env python3
"""Compile a tiny pipeline template for the PSC integration check.

    pip install kfp
    python examples/psc_pipeline.py          # writes psc_pipeline.json
    gcloud storage cp psc_pipeline.json gs://BUCKET/test-pack/psc_pipeline.json

Then set in config.yml:

    pipeline_template: gs://BUCKET/test-pack/psc_pipeline.json
    pipeline_root: gs://BUCKET/pipeline-root
    psc_network_attachment: projects/.../networkAttachments/vertex-psc-attachment

and enable integration.pipeline-psc in checks/60_integrations.yml.

The pipeline itself is intentionally trivial: it proves scheduling and
execution over PSC, not the team's actual workload.
"""

from __future__ import annotations

from kfp import compiler, dsl


@dsl.component(base_image="python:3.11-slim")
def say_hello() -> str:
    print("test-pack: hello from a PSC pipeline task")
    return "ok"


@dsl.pipeline(name="test-pack-psc-smoke", description="Minimal PSC-I smoke test")
def psc_smoke_pipeline():
    say_hello()


if __name__ == "__main__":
    compiler.Compiler().compile(psc_smoke_pipeline, "psc_pipeline.json")
    print("Wrote psc_pipeline.json")
