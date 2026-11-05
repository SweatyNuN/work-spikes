"""Example plugin: a mutating integration test with guaranteed cleanup.

Enable the corresponding check in checks/60_integrations.yml when you want to
prove end-to-end write access, not just bucket metadata.
"""

from __future__ import annotations

import uuid

from testpack.models import Outcome
from testpack.registry import check


@check("storage_roundtrip", "Write, read and delete a tiny object in a GCS bucket")
def storage_roundtrip(ctx, params):
    try:
        from google.cloud import storage
    except ImportError:
        return Outcome.fail(
            "google-cloud-storage is not installed",
            hint="pip install google-cloud-storage",
        )

    bucket_name = params.get("bucket") or ctx.get("bucket")
    project = ctx.get("project_id")
    if not bucket_name:
        return Outcome.skip("needs config value 'bucket'")

    prefix = str(params.get("prefix", "_testpack")).rstrip("/")
    blob_name = f"{prefix}/{uuid.uuid4().hex}.txt"
    payload = "test-pack ok"
    blob = None

    try:
        client = storage.Client(project=project)
        blob = client.bucket(bucket_name).blob(blob_name)
        blob.upload_from_string(payload, content_type="text/plain")
        downloaded = blob.download_as_text()

        if downloaded != payload:
            return Outcome.fail(
                "object contents did not round-trip",
                detail=f"wrote {payload!r}, read {downloaded!r}",
            )

        return Outcome.ok(f"object round-tripped in gs://{bucket_name}")
    except Exception as exc:
        return Outcome.fail(
            "Cloud Storage round-trip failed",
            detail=f"{type(exc).__name__}: {exc}",
            hint="Check bucket IAM, the bucket name, and that storage.googleapis.com is enabled.",
        )
    finally:
        # Best-effort cleanup: never leave test objects behind.
        if blob is not None:
            try:
                blob.delete()
            except Exception:
                pass
