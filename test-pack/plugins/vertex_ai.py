"""Example plugin: a check that needs the Vertex AI Python SDK.

Plugins are plain Python files in this directory. Every function decorated
with @check("name") becomes a check type you can use from YAML:

    - title: Vertex AI SDK can initialise
      type: vertex_sdk_smoke

The function receives the shared `ctx` (config, command runner) and the
interpolated `params` dict, and returns an Outcome. Use this escape hatch for
anything that is awkward to express as a command or a simple assertion.
"""

from __future__ import annotations

from testpack.models import Outcome
from testpack.registry import check


@check("vertex_sdk_smoke", "Initialise the Vertex AI SDK and list endpoints")
def vertex_sdk_smoke(ctx, params):
    try:
        from google.cloud import aiplatform
    except ImportError:
        return Outcome.fail(
            "google-cloud-aiplatform is not installed",
            hint="pip install google-cloud-aiplatform",
        )

    project = ctx.get("project_id")
    region = params.get("region") or ctx.get("region")
    if not project or not region:
        return Outcome.skip("needs project_id and region")

    try:
        aiplatform.init(project=project, location=region)
        endpoints = aiplatform.Endpoint.list()
    except Exception as exc:
        return Outcome.fail(
            "Vertex AI SDK call failed",
            detail=f"{type(exc).__name__}: {exc}",
            hint=(
                "Check Application Default Credentials, roles/aiplatform.user "
                "and that aiplatform.googleapis.com is enabled."
            ),
        )

    names = [
        getattr(endpoint, "display_name", "") or getattr(endpoint, "resource_name", "")
        for endpoint in endpoints
    ]
    detail = "endpoints: " + (", ".join(name for name in names[:10] if name) or "none")
    if len(names) > 10:
        detail += f"\n... and {len(names) - 10} more"
    return Outcome.ok(
        f"SDK initialised in {region}; {len(endpoints)} endpoint(s) visible",
        detail=detail,
    )
