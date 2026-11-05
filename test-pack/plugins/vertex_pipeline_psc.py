"""Vertex AI Pipelines over Private Service Connect (PSC-I).

Two checks live here:

* `vertex_psc_sdk` (safe, fast) proves the installed Vertex AI SDK exposes the
  PSC interface configuration on PipelineJob.
* `vertex_pipeline_psc` (disabled by default) submits a real pipeline run with
  a PSC network attachment and waits for it. That is the only way to prove the
  whole path — network attachment, IAM, image pull, and pipeline execution —
  actually works, but it costs money and time, so it is opt-in.

The high-level `aiplatform.PipelineJob` wrapper does not take a
`psc_interface_config` argument in the 2.x SDK yet. The field exists on the
underlying proto (`google.cloud.aiplatform_v1.types.PipelineJob`), so the
plugin sets it on `_gca_resource` before `submit()`. That is the documented
workaround until the wrapper catches up.
"""

from __future__ import annotations

import importlib.metadata
import time

from testpack.gcp_names import parse_network_attachment
from testpack.models import Outcome
from testpack.registry import check

_SUCCESS_STATES = {"PIPELINE_STATE_SUCCEEDED"}
_FAILURE_STATES = {
    "PIPELINE_STATE_FAILED",
    "PIPELINE_STATE_CANCELLED",
    "PIPELINE_STATE_PAUSED",
    "PIPELINE_STATE_EXPIRED",
}


@check("vertex_psc_sdk", "Check the installed Vertex AI SDK supports PSC interfaces")
def vertex_psc_sdk(ctx, params):
    attachment = params.get("network_attachment") or ctx.get("psc_network_attachment")
    if not attachment:
        return Outcome.skip("needs config value 'psc_network_attachment'")

    try:
        from google.cloud.aiplatform_v1.types import PipelineJob as PipelineJobProto
        from google.cloud.aiplatform_v1.types import PscInterfaceConfig  # noqa: F401
    except ImportError as exc:
        return Outcome.fail(
            "the installed Vertex AI SDK does not expose PSC interface types",
            detail=f"{type(exc).__name__}: {exc}",
            hint="pip install --upgrade google-cloud-aiplatform",
        )

    try:
        version = importlib.metadata.version("google-cloud-aiplatform")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"

    fields = getattr(getattr(PipelineJobProto, "meta", None), "fields", {})
    if "psc_interface_config" not in fields:
        return Outcome.fail(
            f"google-cloud-aiplatform {version} does not support "
            "psc_interface_config on PipelineJob",
            hint="Upgrade to a release that includes PSC interface support.",
        )

    reference = parse_network_attachment(
        attachment,
        project=ctx.get("project_id"),
        region=ctx.get("psc_region") or ctx.get("region"),
    )
    if not reference.region:
        return Outcome.fail(
            "could not determine the region for the PSC network attachment",
            detail=f"network_attachment={attachment!r}",
            hint="Set psc_region, or provide the full network attachment resource name.",
        )

    return Outcome.ok(
        f"google-cloud-aiplatform {version} supports PSC-I",
        detail=f"network attachment: {reference.attachment_name or attachment}",
    )


@check("vertex_pipeline_psc", "Submit a Vertex AI pipeline run using a PSC network attachment")
def vertex_pipeline_psc(ctx, params):
    template = params.get("template_path") or ctx.get("pipeline_template")
    pipeline_root = params.get("pipeline_root") or ctx.get("pipeline_root")
    attachment = params.get("network_attachment") or ctx.get("psc_network_attachment")
    project = ctx.get("project_id")
    region = params.get("region") or ctx.get("psc_region") or ctx.get("region")

    # A full resource name already carries the project and region, so resolve
    # it before deciding that project/region are missing.
    reference = None
    if attachment:
        reference = parse_network_attachment(attachment, project=project, region=region)
        project = reference.project or project
        region = reference.region or region

    missing = [
        name
        for name, value in (
            ("pipeline_template", template),
            ("pipeline_root", pipeline_root),
            ("psc_network_attachment", attachment),
            ("project_id", project),
            ("region", region),
        )
        if not value
    ]
    if missing:
        return Outcome.skip(f"needs config value(s): {', '.join(missing)}")

    if reference is None or not reference.project or not reference.region:
        return Outcome.fail(
            "could not build a full PSC network attachment resource name",
            detail=f"network_attachment={attachment!r}",
            hint="Use projects/PROJECT/regions/REGION/networkAttachments/NAME.",
        )

    try:
        from google.cloud import aiplatform
        from google.cloud.aiplatform_v1.types import DnsPeeringConfig, PscInterfaceConfig
    except ImportError as exc:
        return Outcome.fail(
            "google-cloud-aiplatform is not installed or lacks PSC support",
            detail=f"{type(exc).__name__}: {exc}",
            hint="pip install --upgrade google-cloud-aiplatform",
        )

    try:
        psc_config = PscInterfaceConfig(
            network_attachment=reference.attachment_name or str(attachment)
        )

        dns_peering = params.get("dns_peering") or []
        for item in dns_peering:
            if not isinstance(item, dict):
                return Outcome.fail("dns_peering entries must be mappings")
            missing_dns = [
                key for key in ("domain", "target_project", "target_network") if not item.get(key)
            ]
            if missing_dns:
                return Outcome.fail(
                    f"dns_peering entry is missing {', '.join(missing_dns)}",
                    detail=str(item),
                )
            psc_config.dns_peering_configs.append(
                DnsPeeringConfig(
                    domain=str(item["domain"]),
                    target_project=str(item["target_project"]),
                    target_network=str(item["target_network"]),
                )
            )

        aiplatform.init(project=project, location=region)
        job = aiplatform.PipelineJob(
            display_name=str(params.get("display_name") or "test-pack-psc-smoke"),
            template_path=str(template),
            pipeline_root=str(pipeline_root),
            enable_caching=False,
            labels={"managed-by": "test-pack"},
        )

        # PSC-I is on the proto but not yet a wrapper argument in SDK 2.x.
        job._gca_resource.psc_interface_config = psc_config

        submit_kwargs = {}
        if params.get("service_account"):
            submit_kwargs["service_account"] = str(params["service_account"])
        job.submit(**submit_kwargs)
    except Exception as exc:
        return Outcome.fail(
            "could not submit the PSC pipeline job",
            detail=f"{type(exc).__name__}: {exc}",
            hint=(
                "Check that PSC-I is available for the project, the Vertex service "
                "agent has roles/compute.networkUser on the subnet, and the pipeline "
                "template and root bucket are readable."
            ),
        )

    resource_name = job.resource_name
    job_id = resource_name.rsplit("/", 1)[-1]
    console_url = (
        "https://console.cloud.google.com/vertex-ai/pipelines/locations/"
        f"{region}/runs/{job_id}?project={project}"
    )

    if not params.get("wait", True):
        return Outcome.ok(
            "pipeline submitted with PSC networking",
            detail=f"{resource_name}\n{console_url}",
        )

    timeout = float(params.get("timeout") or 1800)
    poll_seconds = float(params.get("poll_seconds") or 15)
    deadline = time.monotonic() + timeout
    last_state = "UNKNOWN"

    while time.monotonic() < deadline:
        try:
            response = job.api_client.get_pipeline_job(name=resource_name)
            state = response.state
            last_state = getattr(state, "name", str(state))
        except Exception as exc:
            return Outcome.fail(
                "could not poll the pipeline job",
                detail=f"{type(exc).__name__}: {exc}\nresource: {resource_name}",
            )

        if last_state in _SUCCESS_STATES:
            return Outcome.ok(
                "pipeline completed successfully with PSC networking",
                detail=f"{resource_name}\n{console_url}",
            )
        if last_state in _FAILURE_STATES:
            return Outcome.fail(
                f"pipeline ended in {last_state}",
                detail=f"{resource_name}\n{console_url}",
                hint="Open the pipeline run and inspect the failing task logs.",
            )

        time.sleep(poll_seconds)

    if params.get("cancel_on_timeout", True):
        try:
            job.api_client.cancel_pipeline_job(name=resource_name)
        except Exception:
            pass

    return Outcome.fail(
        f"pipeline did not finish within {timeout:.0f}s (last state {last_state})",
        detail=f"{resource_name}\n{console_url}",
        hint="Increase timeout, or set wait: false to only test submission.",
    )
