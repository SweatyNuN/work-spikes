"""Google Cloud checks, implemented through the gcloud CLI.

Using gcloud as the single backend keeps the pack dependency-free and gives
every check the same authentication behaviour (the workbench VM's credentials).
Anything that needs the Python SDK belongs in a plugin instead.
"""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request

from ..gcp_names import last_segment, parse_network_attachment, parse_subnet
from ..models import Outcome
from ..registry import check

_GCLOUD_HINT = (
    "Install the Google Cloud SDK and authenticate (gcloud auth login or "
    "application-default login), or skip these checks with --skip gcp."
)


def _missing_gcloud() -> Outcome | None:
    if shutil.which("gcloud") is None:
        return Outcome.fail("gcloud CLI not found", hint=_GCLOUD_HINT)
    return None


def _project(ctx, params) -> str | None:
    project = params.get("project") or ctx.get("project_id")
    return str(project) if project else None


def _load_json(result) -> object:
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"could not parse gcloud JSON output: {exc}") from exc


def _gcloud_failure(action: str, result, hint: str = _GCLOUD_HINT) -> Outcome:
    detail = result.detail()
    if result.returncode != 0 and result.stderr:
        first_line = next((line.strip() for line in result.stderr.splitlines() if line.strip()), "")
        if first_line:
            action = f"{action} ({first_line})"
    return Outcome.fail(action, detail=detail, hint=hint)


def _duration_seconds(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    unit = text[-1]
    try:
        number = float(text[:-1] if unit.isalpha() else text)
    except ValueError:
        return None
    factor = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit, 1)
    return number * factor


def _casefold_members(members) -> set[str]:
    return {str(member).casefold() for member in members}


def _dig(data, *path):
    node = data
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


@check("gcp_api_enabled", "Assert Google Cloud APIs are enabled")
def gcp_api_enabled(ctx, params):
    missing = _missing_gcloud()
    if missing:
        return missing

    project = _project(ctx, params)
    if not project:
        return Outcome.skip("needs config value 'project_id'")

    apis = params.get("apis")
    if apis is None and params.get("api"):
        apis = [params["api"]]
    if not apis:
        return Outcome.fail("check needs 'api' or 'apis'")
    apis = [str(api) for api in apis]

    result = ctx.gcloud(
        ["services", "list", "--enabled", "--format=value(config.name)"],
        project=project,
        timeout=params.get("timeout") or 60,
    )
    if not result.ok:
        return _gcloud_failure(f"could not list enabled APIs in {project}", result)

    enabled = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    missing_apis = [api for api in apis if api not in enabled]

    if missing_apis:
        return Outcome.fail(
            f"{len(missing_apis)} of {len(apis)} required API(s) are not enabled",
            detail="Missing:\n" + "\n".join(f"  - {api}" for api in missing_apis),
            hint=f"gcloud services enable {' '.join(missing_apis)} --project={project}",
        )

    return Outcome.ok(f"{len(apis)}/{len(apis)} required APIs enabled")


@check("gcp_bucket", "Assert a Cloud Storage bucket exists and matches expectations")
def gcp_bucket(ctx, params):
    missing = _missing_gcloud()
    if missing:
        return missing

    bucket = params.get("bucket") or ctx.get("bucket")
    if not bucket:
        return Outcome.skip("needs config value 'bucket'")

    project = _project(ctx, params)
    result = ctx.gcloud(
        ["storage", "buckets", "describe", f"gs://{bucket}", "--format=json"],
        project=project,
        timeout=params.get("timeout") or 45,
    )
    if not result.ok:
        return _gcloud_failure(
            f"bucket gs://{bucket} was not found or is not accessible",
            result,
            hint="Check the bucket name and that your account has storage.buckets.get.",
        )

    try:
        data = _load_json(result)
    except ValueError as exc:
        return Outcome.fail(str(exc), detail=result.stdout[:2000])
    if not isinstance(data, dict):
        return Outcome.fail("unexpected gcloud output for bucket describe")

    actual_location = data.get("location")
    expected_location = params.get("location")
    if expected_location:
        if not actual_location:
            return Outcome.fail("could not determine the bucket location from gcloud output")
        if str(actual_location).casefold() != str(expected_location).casefold():
            return Outcome.fail(
                f"bucket is in {actual_location}, expected {expected_location}",
                detail=result.stdout[:2000],
            )

    uniform = _dig(data, "iamConfiguration", "uniformBucketLevelAccess", "enabled")
    if uniform is None:
        uniform = _dig(data, "uniformBucketLevelAccess", "enabled")
    expected_uniform = params.get("uniform_access")
    if expected_uniform is not None:
        if uniform is None:
            return Outcome.fail(
                "could not determine uniform bucket-level access from gcloud output"
            )
        if bool(uniform) != bool(expected_uniform):
            state = "enabled" if uniform else "disabled"
            wanted = "enabled" if expected_uniform else "disabled"
            return Outcome.fail(f"uniform bucket-level access is {state}, expected {wanted}")

    versioning = _dig(data, "versioning", "enabled")
    if params.get("versioning") is not None and versioning is not None:
        if bool(versioning) != bool(params["versioning"]):
            return Outcome.fail(
                f"object versioning is {'enabled' if versioning else 'disabled'}, "
                f"expected {'enabled' if params['versioning'] else 'disabled'}"
            )

    public_access = _dig(data, "iamConfiguration", "publicAccessPrevention")
    if params.get("public_access_prevention") is not None and public_access is not None:
        if str(public_access).casefold() != str(params["public_access_prevention"]).casefold():
            return Outcome.fail(
                f"public access prevention is {public_access}, "
                f"expected {params['public_access_prevention']}"
            )

    details = [str(actual_location) if actual_location else "unknown location"]
    if uniform is not None:
        details.append(f"uniform access {'on' if uniform else 'off'}")
    return Outcome.ok(f"gs://{bucket} ({', '.join(details)})")


@check("gcp_kms_key", "Assert a Cloud KMS key exists with the expected settings")
def gcp_kms_key(ctx, params):
    missing = _missing_gcloud()
    if missing:
        return missing

    keyring = params.get("keyring") or ctx.get("kms_keyring")
    key = params.get("key") or ctx.get("kms_key")
    location = params.get("location") or ctx.get("kms_location") or ctx.get("region")
    if not keyring or not key or not location:
        return Outcome.skip("needs kms_keyring, kms_key and location/region")

    project = _project(ctx, params)
    result = ctx.gcloud(
        [
            "kms",
            "keys",
            "describe",
            str(key),
            f"--keyring={keyring}",
            f"--location={location}",
            "--format=json",
        ],
        project=project,
        timeout=params.get("timeout") or 45,
    )
    if not result.ok:
        return _gcloud_failure(
            f"KMS key {keyring}/{key} was not found in {location}",
            result,
            hint="Check the key ring, key name and region against your Terraform outputs.",
        )

    try:
        data = _load_json(result)
    except ValueError as exc:
        return Outcome.fail(str(exc), detail=result.stdout[:2000])
    if not isinstance(data, dict):
        return Outcome.fail("unexpected gcloud output for KMS key describe")

    rotation_seconds = _duration_seconds(data.get("rotationPeriod"))

    if params.get("rotation_days") is not None:
        if rotation_seconds is None:
            return Outcome.fail("could not determine the key rotation period")
        expected = float(params["rotation_days"]) * 86400
        if abs(rotation_seconds - expected) > 3600:
            actual_days = rotation_seconds / 86400
            return Outcome.fail(
                f"key rotates every {actual_days:.1f} days, "
                f"expected {float(params['rotation_days']):g}"
            )

    if params.get("rotation_period"):
        expected = _duration_seconds(params["rotation_period"])
        if expected is None:
            return Outcome.fail(f"invalid rotation_period {params['rotation_period']!r}")
        if rotation_seconds is None or abs(rotation_seconds - expected) > 1:
            actual = f"{rotation_seconds:g}s" if rotation_seconds is not None else "unknown"
            return Outcome.fail(
                f"rotation period is {actual}, expected {params['rotation_period']}"
            )

    purpose = data.get("purpose")
    if params.get("purpose") and purpose != params["purpose"]:
        return Outcome.fail(f"key purpose is {purpose}, expected {params['purpose']}")

    summary = f"{keyring}/{key} in {location}"
    if rotation_seconds is not None:
        summary += f", rotation {rotation_seconds / 86400:.1f} days"
    if purpose:
        summary += f", {purpose}"
    return Outcome.ok(summary)


@check(
    "gcp_iam_binding",
    "Assert an IAM role binding on a project, bucket, KMS key, subnet or service account",
)
def gcp_iam_binding(ctx, params):
    missing = _missing_gcloud()
    if missing:
        return missing

    scope = str(params.get("scope", "project")).strip().lower()
    role = params.get("role")
    members = params.get("members")
    if members is None and params.get("member"):
        members = [params["member"]]
    if not members:
        return Outcome.fail("check needs 'member' or 'members'")
    members = [str(member) for member in members]
    should_be_present = bool(params.get("present", True))
    if should_be_present and not role:
        return Outcome.fail("check needs 'role' when present is true")

    project = _project(ctx, params)
    run_project = project
    target = ""

    if scope == "project":
        if not project:
            return Outcome.skip("needs config value 'project_id'")
        args = ["projects", "get-iam-policy", project, "--format=json"]
        run_project = None
        target = f"project {project}"

    elif scope in {"bucket", "gcs"}:
        bucket = params.get("bucket") or ctx.get("bucket")
        if not bucket:
            return Outcome.skip("needs config value 'bucket'")
        args = ["storage", "buckets", "get-iam-policy", f"gs://{bucket}", "--format=json"]
        target = f"gs://{bucket}"

    elif scope in {"kms", "kms_key", "kms-key"}:
        keyring = params.get("keyring") or ctx.get("kms_keyring")
        key = params.get("key") or ctx.get("kms_key")
        location = params.get("location") or ctx.get("kms_location") or ctx.get("region")
        if not keyring or not key or not location:
            return Outcome.skip("needs keyring, key and location/region")
        args = [
            "kms",
            "keys",
            "get-iam-policy",
            str(key),
            f"--keyring={keyring}",
            f"--location={location}",
            "--format=json",
        ]
        target = f"KMS key {keyring}/{key}"

    elif scope in {"subnet", "subnetwork"}:
        raw_subnet = params.get("subnet")
        if not raw_subnet:
            return Outcome.skip("needs a 'subnet' parameter")
        subnet = parse_subnet(
            raw_subnet,
            project=project,
            region=params.get("region") or ctx.get("psc_region") or ctx.get("region"),
        )
        if not subnet.region:
            return Outcome.skip("needs a region for the subnet")
        args = [
            "compute",
            "networks",
            "subnets",
            "get-iam-policy",
            subnet.name,
            f"--region={subnet.region}",
            "--format=json",
        ]
        target = f"subnet {subnet.name}"
        run_project = subnet.project or project

    elif scope in {"service_account", "service-account", "sa"}:
        email = params.get("service_account") or params.get("email")
        if not email:
            return Outcome.skip("needs a 'service_account' email")
        args = ["iam", "service-accounts", "get-iam-policy", str(email), "--format=json"]
        target = f"service account {email}"

    else:
        return Outcome.fail(
            f"unknown IAM scope '{scope}'",
            hint="Use scope: project, bucket, kms_key, subnet or service_account.",
        )

    result = ctx.gcloud(args, project=run_project, timeout=params.get("timeout") or 45)
    if not result.ok:
        return _gcloud_failure(
            f"could not read the IAM policy for {target}",
            result,
            hint="Check that you have permission to view the IAM policy.",
        )

    try:
        data = _load_json(result)
    except ValueError as exc:
        return Outcome.fail(str(exc), detail=result.stdout[:2000])

    bindings = data.get("bindings", []) if isinstance(data, dict) else []
    granted: dict[str, set[str]] = {}
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        granted[str(binding.get("role", ""))] = {
            str(member) for member in binding.get("members", [])
        }

    if role:
        actual_for_role = granted.get(str(role), set())
        actual_folded = _casefold_members(actual_for_role)
        missing_members = [member for member in members if member.casefold() not in actual_folded]

        if should_be_present and missing_members:
            roles_summary = (
                ", ".join(sorted(role_name for role_name in granted if granted[role_name]))
                or "none"
            )
            return Outcome.fail(
                f"{role} is not granted to {', '.join(missing_members)} on {target}",
                detail=(
                    f"Roles present on {target}: {roles_summary}\n"
                    f"Members with {role}: {', '.join(sorted(actual_for_role)) or 'none'}"
                ),
                hint="Apply the Terraform or grant the role manually, then re-run.",
            )

        if not should_be_present and not missing_members:
            return Outcome.fail(
                f"{role} is granted to {', '.join(members)} on {target}, but should not be"
            )

        action = "granted to" if should_be_present else "not granted to"
        return Outcome.ok(f"{role} {action} {', '.join(members)} on {target}")

    # No role: with present: false, assert the member appears in no binding at
    # all. Useful for allUsers / allAuthenticatedUsers checks.
    members_folded = _casefold_members(members)
    roles_with_member: dict[str, list[str]] = {}
    for role_name, role_members in granted.items():
        matching = [member for member in role_members if member.casefold() in members_folded]
        if matching:
            roles_with_member[role_name] = sorted(matching)

    if roles_with_member:
        detail = "\n".join(
            f"  {role_name}: {', '.join(role_members)}"
            for role_name, role_members in sorted(roles_with_member.items())
        )
        return Outcome.fail(
            f"{', '.join(members)} has bindings on {target}",
            detail="Bindings found:\n" + detail,
            hint="Remove the public or unauthorised principal from the IAM policy.",
        )

    return Outcome.ok(f"{', '.join(members)} has no bindings on {target}")


@check("gcp_service_account", "Assert a service account exists")
def gcp_service_account(ctx, params):
    missing = _missing_gcloud()
    if missing:
        return missing

    email = params.get("email") or params.get("service_account")
    if not email:
        email = ctx.get("service_agent")
    if not email:
        return Outcome.skip("needs config value 'service_agent'")

    project = _project(ctx, params)
    result = ctx.gcloud(
        ["iam", "service-accounts", "describe", str(email), "--format=json"],
        project=project,
        timeout=params.get("timeout") or 45,
    )
    if not result.ok:
        return _gcloud_failure(
            f"service account {email} was not found",
            result,
            hint=(
                "Enable aiplatform.googleapis.com and apply the Terraform "
                "service identity resource."
            ),
        )

    try:
        data = _load_json(result)
    except ValueError as exc:
        return Outcome.fail(str(exc), detail=result.stdout[:2000])

    disabled = bool(data.get("disabled", False)) if isinstance(data, dict) else False
    if params.get("disabled") is not None and disabled != bool(params["disabled"]):
        return Outcome.fail(
            f"service account is {'disabled' if disabled else 'enabled'}, "
            f"expected {'disabled' if params['disabled'] else 'enabled'}"
        )

    suffix = ", disabled" if disabled else ""
    return Outcome.ok(f"{email} exists{suffix}")


@check("gcp_bigquery_dataset", "Assert a BigQuery dataset exists")
def gcp_bigquery_dataset(ctx, params):
    dataset = params.get("dataset")
    if not dataset:
        return Outcome.fail("check is missing the 'dataset' param")
    if shutil.which("bq") is None:
        return Outcome.fail(
            "bq CLI not found",
            hint=(
                "The BigQuery CLI ships with the Google Cloud SDK; "
                "install it or use a plugin check."
            ),
        )

    project = _project(ctx, params)
    reference = (
        str(dataset) if ":" in str(dataset) else f"{project}:{dataset}" if project else str(dataset)
    )
    result = ctx.run(
        ["bq", "show", "--format=prettyjson", reference],
        timeout=params.get("timeout") or 60,
    )
    if not result.ok:
        return Outcome.fail(
            f"BigQuery dataset {reference} was not found or is not accessible",
            detail=result.detail(),
            hint="Check the dataset name and that your account can view it.",
        )

    try:
        data = _load_json(result)
    except ValueError as exc:
        return Outcome.fail(str(exc), detail=result.stdout[:2000])

    location = data.get("location") if isinstance(data, dict) else None
    expected_location = params.get("location")
    if expected_location and location:
        if str(location).casefold() != str(expected_location).casefold():
            return Outcome.fail(f"dataset is in {location}, expected {expected_location}")

    suffix = f" ({location})" if location else ""
    return Outcome.ok(f"{reference}{suffix}")


@check("gcp_bigquery_query", "Run a BigQuery query and assert on the result")
def gcp_bigquery_query(ctx, params):
    sql = params.get("sql")
    if not sql:
        return Outcome.fail("check is missing the 'sql' param")
    if shutil.which("bq") is None:
        return Outcome.fail(
            "bq CLI not found",
            hint=(
                "The BigQuery CLI ships with the Google Cloud SDK; "
                "install it or use a plugin check."
            ),
        )

    project = _project(ctx, params)
    max_rows = int(params.get("max_rows", 100))
    args = [
        "bq",
        "query",
        "--nouse_legacy_sql",
        "--format=json",
        f"--max_rows={max_rows}",
    ]
    if project:
        args.append(f"--project_id={project}")
    args.append(str(sql))

    result = ctx.run(args, timeout=params.get("timeout") or 120)
    if not result.ok:
        return Outcome.fail(
            "BigQuery query failed",
            detail=result.detail(),
            hint=(
                "Check that the BigQuery API is enabled and your account has job/user permissions."
            ),
        )

    try:
        rows = _load_json(result)
    except ValueError as exc:
        return Outcome.fail(str(exc), detail=result.stdout[:2000])
    if not isinstance(rows, list):
        return Outcome.fail("unexpected BigQuery output", detail=result.stdout[:2000])

    if params.get("expect_rows") is not None and len(rows) != int(params["expect_rows"]):
        return Outcome.fail(
            f"query returned {len(rows)} row(s), expected {int(params['expect_rows'])}",
            detail=result.stdout[:2000],
        )
    if params.get("min_rows") is not None and len(rows) < int(params["min_rows"]):
        return Outcome.fail(
            f"query returned {len(rows)} row(s), expected at least {int(params['min_rows'])}",
            detail=result.stdout[:2000],
        )

    if params.get("expect_value") is not None:
        if not rows:
            return Outcome.fail("query returned no rows, so there is no value to compare")
        first = rows[0]
        column = params.get("column")
        if isinstance(first, dict):
            actual = first.get(column) if column else next(iter(first.values()), None)
        else:
            actual = first
        if str(actual) != str(params["expect_value"]):
            return Outcome.fail(
                f"query returned {actual!r}, expected {params['expect_value']!r}",
                detail=result.stdout[:2000],
            )

    return Outcome.ok(f"query returned {len(rows)} row(s)")


@check("gcp_vertex_endpoints", "Assert Vertex AI endpoints exist in a region")
def gcp_vertex_endpoints(ctx, params):
    missing = _missing_gcloud()
    if missing:
        return missing

    project = _project(ctx, params)
    if not project:
        return Outcome.skip("needs config value 'project_id'")

    region = params.get("region") or ctx.get("region")
    if not region:
        return Outcome.skip("needs config value 'region'")

    result = ctx.gcloud(
        ["ai", "endpoints", "list", f"--region={region}", "--format=json"],
        project=project,
        timeout=params.get("timeout") or 60,
    )
    if not result.ok:
        return _gcloud_failure(
            f"could not list Vertex AI endpoints in {region}",
            result,
            hint="Enable aiplatform.googleapis.com and check roles/aiplatform.user.",
        )

    try:
        data = _load_json(result)
    except ValueError as exc:
        return Outcome.fail(str(exc), detail=result.stdout[:2000])
    if not isinstance(data, list):
        return Outcome.fail("unexpected Vertex AI endpoint output", detail=result.stdout[:2000])

    name_filter = params.get("name_contains")
    endpoints = [
        endpoint
        for endpoint in data
        if isinstance(endpoint, dict)
        and (
            not name_filter
            or str(name_filter).casefold() in str(endpoint.get("displayName", "")).casefold()
        )
    ]

    minimum = int(params.get("min_count", 0))
    if len(endpoints) < minimum:
        return Outcome.fail(
            f"{len(endpoints)} endpoint(s) match, expected at least {minimum}",
            detail=", ".join(str(item.get("displayName")) for item in endpoints) or "none",
        )

    if params.get("exact_count") is not None and len(endpoints) != int(params["exact_count"]):
        return Outcome.fail(
            f"{len(endpoints)} endpoint(s) found, expected {int(params['exact_count'])}"
        )

    names = ", ".join(str(item.get("displayName")) for item in endpoints)
    suffix = f" ({names})" if names else ""
    return Outcome.ok(f"{len(endpoints)} endpoint(s) in {region}{suffix}")


@check("gcp_subnet", "Assert a Compute Engine subnet exists and matches expectations")
def gcp_subnet(ctx, params):
    missing = _missing_gcloud()
    if missing:
        return missing

    raw_subnet = params.get("subnet") or ctx.get("psc_subnet")
    if not raw_subnet:
        return Outcome.skip("needs a subnet name or config value 'psc_subnet'")

    project = _project(ctx, params)
    region = params.get("region") or ctx.get("psc_region") or ctx.get("region")
    subnet = parse_subnet(raw_subnet, project=project, region=region)
    if not subnet.region:
        return Outcome.skip("needs config value 'region' (or a subnet self-link)")

    result = ctx.gcloud(
        [
            "compute",
            "networks",
            "subnets",
            "describe",
            subnet.name,
            f"--region={subnet.region}",
            "--format=json",
        ],
        project=subnet.project or project,
        timeout=params.get("timeout") or 45,
    )
    if not result.ok:
        return _gcloud_failure(
            f"subnet {subnet.name} was not found in {subnet.region}",
            result,
            hint="Check the subnet name, region and that you have compute.subnetworks.get.",
        )

    try:
        data = _load_json(result)
    except ValueError as exc:
        return Outcome.fail(str(exc), detail=result.stdout[:2000])
    if not isinstance(data, dict):
        return Outcome.fail("unexpected gcloud output for subnet describe")

    problems: list[str] = []

    expected_purpose = params.get("purpose")
    actual_purpose = data.get("purpose")
    if expected_purpose:
        if not actual_purpose:
            problems.append(f"has no purpose, expected {expected_purpose}")
        elif str(actual_purpose).casefold() != str(expected_purpose).casefold():
            problems.append(f"purpose is {actual_purpose}, expected {expected_purpose}")

    if params.get("private_ip_google_access") is not None:
        actual = bool(data.get("privateIpGoogleAccess", False))
        if actual != bool(params["private_ip_google_access"]):
            problems.append(
                f"private Google access is {'on' if actual else 'off'}, "
                f"expected {'on' if params['private_ip_google_access'] else 'off'}"
            )

    if params.get("network"):
        actual_network = last_segment(data.get("network", ""))
        expected_network = last_segment(params["network"])
        if actual_network.casefold() != expected_network.casefold():
            problems.append(f"is in network {actual_network}, expected {expected_network}")

    if params.get("ip_cidr_range"):
        actual_range = data.get("ipCidrRange")
        if str(actual_range) != str(params["ip_cidr_range"]):
            problems.append(f"has range {actual_range}, expected {params['ip_cidr_range']}")

    actual_region = data.get("region")
    if actual_region and last_segment(actual_region).casefold() != subnet.region.casefold():
        problems.append(f"is in region {last_segment(actual_region)}, expected {subnet.region}")

    if problems:
        return Outcome.fail(
            f"subnet {subnet.name}: " + "; ".join(problems),
            detail=result.stdout[:3000],
        )

    summary = f"{subnet.name} in {subnet.region}"
    if actual_purpose:
        summary += f" ({actual_purpose})"
    if "privateIpGoogleAccess" in data:
        summary += f", private Google access {'on' if data['privateIpGoogleAccess'] else 'off'}"
    return Outcome.ok(summary)


@check("gcp_network_attachment", "Assert a PSC network attachment exists and matches expectations")
def gcp_network_attachment(ctx, params):
    missing = _missing_gcloud()
    if missing:
        return missing

    raw_attachment = (
        params.get("network_attachment") or params.get("name") or ctx.get("psc_network_attachment")
    )
    if not raw_attachment:
        return Outcome.skip("needs config value 'psc_network_attachment'")

    project = _project(ctx, params)
    region = params.get("region") or ctx.get("psc_region") or ctx.get("region")
    attachment = parse_network_attachment(raw_attachment, project=project, region=region)
    if not attachment.region:
        return Outcome.skip("needs config value 'region' (or a network attachment self-link)")

    result = ctx.gcloud(
        [
            "compute",
            "network-attachments",
            "describe",
            attachment.name,
            f"--region={attachment.region}",
            "--format=json",
        ],
        project=attachment.project or project,
        timeout=params.get("timeout") or 45,
    )
    if not result.ok:
        return _gcloud_failure(
            f"network attachment {attachment.name} was not found in {attachment.region}",
            result,
            hint=(
                "Check the attachment name, region and that you have "
                "compute.networkAttachments.get."
            ),
        )

    try:
        data = _load_json(result)
    except ValueError as exc:
        return Outcome.fail(str(exc), detail=result.stdout[:2000])
    if not isinstance(data, dict):
        return Outcome.fail("unexpected gcloud output for network attachment describe")

    problems: list[str] = []

    expected_preference = params.get("connection_preference")
    actual_preference = data.get("connectionPreference")
    if (
        expected_preference
        and str(actual_preference).casefold() != str(expected_preference).casefold()
    ):
        problems.append(
            f"connection preference is {actual_preference}, expected {expected_preference}"
        )

    if params.get("subnet"):
        expected_subnet = parse_subnet(
            params["subnet"], project=project, region=attachment.region
        ).name
        actual_subnets = [last_segment(item) for item in data.get("subnetworks", []) if item]
        if expected_subnet.casefold() not in {item.casefold() for item in actual_subnets}:
            problems.append(
                f"uses subnet(s) {', '.join(actual_subnets) or 'none'}, expected {expected_subnet}"
            )

    if params.get("producer_accept_lists") is not None:
        raw_accept = params["producer_accept_lists"]
        expected_items = raw_accept if isinstance(raw_accept, (list, tuple, set)) else [raw_accept]
        expected = {str(item) for item in expected_items}
        actual = {str(item) for item in data.get("producerAcceptLists", [])}
        if expected != actual:
            problems.append(
                f"producer accept list is {sorted(actual) or 'empty'}, "
                f"expected {sorted(expected) or 'empty'}"
            )

    if params.get("network"):
        actual_network = last_segment(data.get("network", ""))
        expected_network = last_segment(params["network"])
        if actual_network.casefold() != expected_network.casefold():
            problems.append(f"is in network {actual_network}, expected {expected_network}")

    if problems:
        return Outcome.fail(
            f"network attachment {attachment.name}: " + "; ".join(problems),
            detail=result.stdout[:3000],
        )

    subnets = [last_segment(item) for item in data.get("subnetworks", []) if item]
    summary = f"{attachment.name} in {attachment.region}"
    if actual_preference:
        summary += f" ({actual_preference})"
    if subnets:
        summary += f", subnet(s): {', '.join(subnets)}"
    return Outcome.ok(summary)


def _post_json(url: str, payload: dict, token: str, timeout: float) -> object:
    """POST JSON with an OAuth token and parse the JSON response.

    Deliberately keeps the token out of every error message.
    """

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace") if exc.fp else ""
        raise RuntimeError(f"HTTP {exc.code}: {detail[:1000]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"request failed: {reason}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"could not parse response: {exc}") from exc


@check("gcp_iam_permissions", "Assert effective permissions for the calling identity")
def gcp_iam_permissions(ctx, params):
    # Resource Manager's projects.testIamPermissions evaluates permissions that
    # apply to the project resource. Resource-scoped permissions belong in a
    # resource-specific check such as gcp_iam_binding role absence.
    missing = _missing_gcloud()
    if missing:
        return missing

    project = _project(ctx, params)
    if not project:
        return Outcome.skip("needs config value 'project_id'")

    raw_permissions = params.get("permissions")
    if isinstance(raw_permissions, str):
        raw_permissions = [item.strip() for item in raw_permissions.split(",")]
    if not isinstance(raw_permissions, (list, tuple, set)) or not raw_permissions:
        return Outcome.fail("check needs a non-empty 'permissions' list")
    permissions = [str(item).strip() for item in raw_permissions if str(item).strip()]
    if not permissions:
        return Outcome.fail("check needs a non-empty 'permissions' list")

    expectation = str(params.get("expect", "absent")).strip().lower()
    if expectation in {"absent", "deny", "denied", "not_granted", "not-granted"}:
        expect_present = False
    elif expectation in {"present", "granted", "allow", "allowed"}:
        expect_present = True
    else:
        return Outcome.fail("expect must be 'absent' or 'present'")

    token_result = ctx.run(["gcloud", "auth", "print-access-token"], timeout=15)
    if not token_result.ok:
        return Outcome.fail(
            "could not get an access token from gcloud",
            detail=(token_result.stderr or token_result.error or "").strip()[:2000],
            hint="Authenticate with gcloud auth login / application-default login.",
        )
    token = token_result.stdout.strip()
    if not token:
        return Outcome.fail(
            "gcloud returned an empty access token",
            hint="Authenticate with gcloud auth login / application-default login.",
        )

    timeout = float(params.get("http_timeout") or 20)
    url = f"https://cloudresourcemanager.googleapis.com/v1/projects/{project}:testIamPermissions"
    try:
        payload = _post_json(url, {"permissions": permissions}, token, timeout)
    except RuntimeError as exc:
        return Outcome.fail(
            f"testIamPermissions failed for project {project}",
            detail=str(exc),
            hint="Check cloudresourcemanager.googleapis.com and that the caller can test IAM.",
        )

    granted_raw = payload.get("permissions", []) if isinstance(payload, dict) else None
    if not isinstance(granted_raw, list):
        return Outcome.fail("unexpected testIamPermissions response", detail=str(payload)[:2000])
    granted = [str(item) for item in granted_raw]

    if expect_present:
        not_granted = [item for item in permissions if item not in granted]
        if not_granted:
            return Outcome.fail(
                f"{len(not_granted)} of {len(permissions)} required permission(s) are missing",
                detail="Missing:\n" + "\n".join(f"  - {item}" for item in sorted(not_granted)),
            )
        return Outcome.ok(f"all {len(permissions)} required permission(s) are granted")

    if granted:
        return Outcome.fail(
            f"{len(granted)} permission(s) that should be absent are granted",
            detail="Granted:\n" + "\n".join(f"  - {item}" for item in sorted(granted)),
            hint="Remove the broad role from the workbench identity and re-run.",
        )

    return Outcome.ok(
        f"none of {len(permissions)} forbidden permission(s) are granted",
        detail=f"tested on project {project}",
    )
