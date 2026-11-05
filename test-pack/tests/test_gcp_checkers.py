"""Parser-level tests for the gcloud-backed checkers.

No network: each test feeds a realistic `gcloud --format=json` payload straight
to the checker. This is where field paths and IAM comparison logic get pinned
down without needing a live project.
"""

from __future__ import annotations

import json

from testpack.checkers import gcp
from testpack.context import CommandResult


class StubContext:
    def __init__(self, gcloud_json=None, run_json=None, values=None):
        self.gcloud_result = _result(gcloud_json)
        self.run_result = _result(run_json)
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def gcloud(self, args, project=None, timeout=None):
        return self.gcloud_result

    def run(self, command, timeout=None, cwd=None, env=None, shell=None):
        return self.run_result


def _result(payload) -> CommandResult:
    if payload is None:
        return CommandResult(argv=[], returncode=1, stderr="not found")
    stdout = payload if isinstance(payload, str) else json.dumps(payload)
    return CommandResult(argv=[], returncode=0, stdout=stdout)


def _patch_tools(monkeypatch, *names):
    monkeypatch.setattr(
        gcp.shutil, "which", lambda name: f"/usr/bin/{name}" if name in names else None
    )


def test_api_enabled(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    ctx = StubContext(
        gcloud_json="aiplatform.googleapis.com\nstorage.googleapis.com\n",
        values={"project_id": "demo"},
    )

    outcome = gcp.gcp_api_enabled(
        ctx, {"apis": ["aiplatform.googleapis.com", "storage.googleapis.com"]}
    )
    assert outcome.status == "pass"


def test_api_missing_is_reported(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    ctx = StubContext(
        gcloud_json="storage.googleapis.com\n",
        values={"project_id": "demo"},
    )

    outcome = gcp.gcp_api_enabled(
        ctx, {"apis": ["aiplatform.googleapis.com", "storage.googleapis.com"]}
    )
    assert outcome.status == "fail"
    assert "aiplatform.googleapis.com" in outcome.detail


def test_bucket_metadata(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    ctx = StubContext(
        gcloud_json={
            "location": "EUROPE-WEST2",
            "iamConfiguration": {"uniformBucketLevelAccess": {"enabled": True}},
        }
    )

    outcome = gcp.gcp_bucket(
        ctx,
        {"bucket": "demo-bucket", "location": "europe-west2", "uniform_access": True},
    )
    assert outcome.status == "pass"


def test_bucket_wrong_location(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    ctx = StubContext(
        gcloud_json={
            "location": "US-CENTRAL1",
            "iamConfiguration": {"uniformBucketLevelAccess": {"enabled": True}},
        }
    )

    outcome = gcp.gcp_bucket(ctx, {"bucket": "demo-bucket", "location": "europe-west2"})
    assert outcome.status == "fail"
    assert "US-CENTRAL1" in outcome.message


def test_kms_rotation_and_purpose(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    ctx = StubContext(gcloud_json={"rotationPeriod": "2592000s", "purpose": "ENCRYPT_DECRYPT"})

    outcome = gcp.gcp_kms_key(
        ctx,
        {
            "keyring": "vertex-keyring",
            "key": "vertex-cmek",
            "location": "europe-west2",
            "rotation_days": 30,
            "purpose": "ENCRYPT_DECRYPT",
        },
    )
    assert outcome.status == "pass"


def test_kms_wrong_rotation(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    ctx = StubContext(gcloud_json={"rotationPeriod": "86400s", "purpose": "ENCRYPT_DECRYPT"})

    outcome = gcp.gcp_kms_key(
        ctx,
        {
            "keyring": "vertex-keyring",
            "key": "vertex-cmek",
            "location": "europe-west2",
            "rotation_days": 30,
        },
    )
    assert outcome.status == "fail"
    assert "1.0 days" in outcome.message


def test_iam_binding_present(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    member = "serviceAccount:service-123@gcp-sa-aiplatform.iam.gserviceaccount.com"
    ctx = StubContext(
        gcloud_json={
            "bindings": [
                {
                    "role": "roles/cloudkms.cryptoKeyEncrypterDecrypter",
                    "members": [member],
                }
            ]
        },
        values={"project_id": "demo"},
    )

    outcome = gcp.gcp_iam_binding(
        ctx,
        {
            "scope": "kms_key",
            "keyring": "vertex-keyring",
            "key": "vertex-cmek",
            "location": "europe-west2",
            "role": "roles/cloudkms.cryptoKeyEncrypterDecrypter",
            "member": member,
        },
    )
    assert outcome.status == "pass"


def test_iam_binding_missing(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    ctx = StubContext(
        gcloud_json={"bindings": []},
        values={"project_id": "demo"},
    )

    outcome = gcp.gcp_iam_binding(
        ctx,
        {
            "scope": "project",
            "role": "roles/aiplatform.user",
            "member": "user:someone@example.com",
        },
    )
    assert outcome.status == "fail"
    assert "not granted" in outcome.message


def test_bigquery_query_value(monkeypatch):
    _patch_tools(monkeypatch, "bq")
    ctx = StubContext(
        run_json=[{"ok": "1"}],
        values={"project_id": "demo"},
    )

    outcome = gcp.gcp_bigquery_query(
        ctx, {"sql": "SELECT 1 AS ok", "column": "ok", "expect_value": "1"}
    )
    assert outcome.status == "pass"


def test_bigquery_query_wrong_value(monkeypatch):
    _patch_tools(monkeypatch, "bq")
    ctx = StubContext(
        run_json=[{"ok": "2"}],
        values={"project_id": "demo"},
    )

    outcome = gcp.gcp_bigquery_query(
        ctx, {"sql": "SELECT 2 AS ok", "column": "ok", "expect_value": "1"}
    )
    assert outcome.status == "fail"
    assert "expected '1'" in outcome.message


_SUBNET = {
    "ipCidrRange": "10.10.0.0/24",
    "network": "https://www.googleapis.com/compute/v1/projects/demo/global/networks/vertex-vpc",
    "privateIpGoogleAccess": True,
    "purpose": "PRIVATE_SERVICE_CONNECT",
    "region": "https://www.googleapis.com/compute/v1/projects/demo/regions/europe-west2",
}

_NETWORK_ATTACHMENT = {
    "connectionPreference": "ACCEPT_AUTOMATIC",
    "network": "https://www.googleapis.com/compute/v1/projects/demo/global/networks/vertex-vpc",
    "region": "https://www.googleapis.com/compute/v1/projects/demo/regions/europe-west2",
    "subnetworks": [
        "https://www.googleapis.com/compute/v1/projects/demo/regions/europe-west2/"
        "subnetworks/vertex-psc-subnet"
    ],
}


def test_psc_subnet(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    ctx = StubContext(gcloud_json=_SUBNET, values={"project_id": "demo"})

    outcome = gcp.gcp_subnet(
        ctx,
        {
            "subnet": "vertex-psc-subnet",
            "region": "europe-west2",
            "network": "vertex-vpc",
            "purpose": "PRIVATE_SERVICE_CONNECT",
            "private_ip_google_access": True,
            "ip_cidr_range": "10.10.0.0/24",
        },
    )
    assert outcome.status == "pass"


def test_psc_subnet_wrong_purpose(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    ctx = StubContext(gcloud_json=_SUBNET, values={"project_id": "demo"})

    outcome = gcp.gcp_subnet(
        ctx,
        {"subnet": "vertex-psc-subnet", "region": "europe-west2", "purpose": "PRIVATE"},
    )
    assert outcome.status == "fail"
    assert "PRIVATE_SERVICE_CONNECT" in outcome.message


def test_psc_network_attachment(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    ctx = StubContext(gcloud_json=_NETWORK_ATTACHMENT, values={"project_id": "demo"})

    outcome = gcp.gcp_network_attachment(
        ctx,
        {
            "network_attachment": (
                "projects/demo/regions/europe-west2/networkAttachments/vertex-psc-attachment"
            ),
            "subnet": "vertex-psc-subnet",
            "connection_preference": "ACCEPT_AUTOMATIC",
            "network": "vertex-vpc",
        },
    )
    assert outcome.status == "pass"


def test_psc_network_attachment_wrong_subnet(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    ctx = StubContext(gcloud_json=_NETWORK_ATTACHMENT, values={"project_id": "demo"})

    outcome = gcp.gcp_network_attachment(
        ctx,
        {
            "network_attachment": "vertex-psc-attachment",
            "region": "europe-west2",
            "subnet": "some-other-subnet",
        },
    )
    assert outcome.status == "fail"
    assert "some-other-subnet" in outcome.message


def test_psc_subnet_iam_binding(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    member = "serviceAccount:service-123@gcp-sa-aiplatform.iam.gserviceaccount.com"
    ctx = StubContext(
        gcloud_json={"bindings": [{"role": "roles/compute.networkUser", "members": [member]}]},
        values={"project_id": "demo"},
    )

    outcome = gcp.gcp_iam_binding(
        ctx,
        {
            "scope": "subnet",
            "subnet": "vertex-psc-subnet",
            "region": "europe-west2",
            "role": "roles/compute.networkUser",
            "member": member,
        },
    )
    assert outcome.status == "pass"


class FakeJsonResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *args):
        return self._body


def _iam_permissions_context(monkeypatch, granted):
    _patch_tools(monkeypatch, "gcloud")
    monkeypatch.setattr(
        gcp.urllib.request,
        "urlopen",
        lambda request, timeout=None: FakeJsonResponse({"permissions": granted}),
    )
    return StubContext(run_json="fake-access-token", values={"project_id": "demo"})


def test_iam_permissions_absent_passes_when_none_granted(monkeypatch):
    ctx = _iam_permissions_context(monkeypatch, [])

    outcome = gcp.gcp_iam_permissions(
        ctx,
        {"permissions": ["resourcemanager.projects.setIamPolicy"], "expect": "absent"},
    )

    assert outcome.status == "pass"
    assert "fake-access-token" not in outcome.message + outcome.detail


def test_iam_permissions_absent_fails_when_granted(monkeypatch):
    ctx = _iam_permissions_context(monkeypatch, ["resourcemanager.projects.setIamPolicy"])

    outcome = gcp.gcp_iam_permissions(
        ctx,
        {"permissions": ["resourcemanager.projects.setIamPolicy"], "expect": "absent"},
    )

    assert outcome.status == "fail"
    assert "setIamPolicy" in outcome.detail
    assert "fake-access-token" not in outcome.detail


def test_iam_permissions_present_passes_when_all_granted(monkeypatch):
    ctx = _iam_permissions_context(monkeypatch, ["storage.objects.get", "storage.objects.list"])

    outcome = gcp.gcp_iam_permissions(
        ctx,
        {
            "permissions": ["storage.objects.get", "storage.objects.list"],
            "expect": "present",
        },
    )

    assert outcome.status == "pass"


def test_iam_permissions_present_fails_when_missing(monkeypatch):
    ctx = _iam_permissions_context(monkeypatch, ["storage.objects.get"])

    outcome = gcp.gcp_iam_permissions(
        ctx,
        {
            "permissions": ["storage.objects.get", "storage.objects.list"],
            "expect": "present",
        },
    )

    assert outcome.status == "fail"
    assert "storage.objects.list" in outcome.detail


def test_iam_binding_absent_without_role_checks_any_binding(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    ctx = StubContext(
        gcloud_json={"bindings": [{"role": "roles/storage.objectViewer", "members": ["allUsers"]}]},
        values={"project_id": "demo"},
    )

    outcome = gcp.gcp_iam_binding(
        ctx,
        {"scope": "bucket", "bucket": "demo-bucket", "member": "allUsers", "present": False},
    )

    assert outcome.status == "fail"
    assert "allUsers" in outcome.message
    assert "roles/storage.objectViewer" in outcome.detail


def test_iam_binding_absent_without_role_passes_when_no_bindings(monkeypatch):
    _patch_tools(monkeypatch, "gcloud")
    ctx = StubContext(gcloud_json={"bindings": []}, values={"project_id": "demo"})

    outcome = gcp.gcp_iam_binding(
        ctx,
        {"scope": "bucket", "bucket": "demo-bucket", "member": "allUsers", "present": False},
    )

    assert outcome.status == "pass"
