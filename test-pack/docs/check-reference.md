# Check reference

Every type accepts the common check fields (`title`, `id`, `severity`, `tags`,
`timeout`, `enabled`, `hint`). `params` is documented per type.

Check-level `timeout` is passed to the type as the default command/query
timeout. A `timeout` inside `params` wins.

## Python

| Type | Params | Asserts |
| ---- | ------ | ------- |
| `python_version` | `version`, `min_version`, `max_version`, `exact_version`, `implementation` | Interpreter version and implementation |
| `package` | `name`, `import_name`, `version`, `min_version`, `max_version`, `exact_version`, `import_check` | Distribution installed, version matches, import succeeds |
| `python_import` | `module`, `attribute`, `name` | Module (and optional attribute) imports |

`version` accepts a comma-separated specifier such as `">=1.60,<2"`. The
checker uses `packaging` when available and a small fallback otherwise.
`import_name` defaults to `name` with `-` replaced by `_`; set it when the
import name differs (for example `scikit-learn` → `sklearn`).
`import_check: false` checks metadata/spec only, without executing the import.

## System

| Type | Params | Asserts |
| ---- | ------ | ------- |
| `command` | `command`, `expect_exit`, `stdout_contains`, `stdout_not_contains`, `stdout_regex`, `stderr_contains`, `env`, `cwd`, `shell`, `show_output`, `message` | Command result |
| `file` | `path`, `exists`, `kind`, `contains`, `not_contains`, `regex`, `min_bytes`, `max_bytes` | File/directory presence and content |
| `env` | `name`, `present`, `equals`, `contains`, `one_of`, `regex`, `secret` | Environment variable |
| `http` | `url`, `method`, `status`, `contains`, `body_regex`, `headers`, `body` | HTTP response |
| `http_blocked` | `url` or `urls`, `probe_timeout`, `blocked_statuses`, `headers` | URLs are **not** reachable |
| `gpu` | `min_count`, `name_contains`, `optional` | NVIDIA GPU visibility |
| `disk` | `path`, `writable`, `min_free_gb` | Path writable and free space |

Notes:

* `command`: a list runs without a shell; a string runs through the shell.
  If you pass a list with `shell: true`, the list is joined and quoted.
* `expect_exit` may be an int or a list of ints.
* `file` paths are relative to the pack root unless absolute. `~` expands.
* `env` masks values for names containing `SECRET`, `TOKEN`, `PASSWORD`,
  `CREDENTIAL` or `PRIVATE`, unless `secret: false` is set.
* `gpu` skips when `optional: true` and no GPU is present.
* `disk` creates and removes a temporary file when `writable: true`.

## Google Cloud

All GCP checks use `gcloud`; the Python Google SDK is not required. `project`
defaults to `project_id`, and most resource params default to the matching
config value.

| Type | Params | Asserts |
| ---- | ------ | ------- |
| `gcp_api_enabled` | `api` or `apis`, `project` | Service Usage enabled APIs |
| `gcp_bucket` | `bucket`, `location`, `uniform_access`, `versioning`, `public_access_prevention`, `project` | Bucket metadata |
| `gcp_kms_key` | `keyring`, `key`, `location`, `rotation_days`, `rotation_period`, `purpose`, `project` | KMS key metadata |
| `gcp_iam_binding` | `scope`, `role`, `member`/`members`, `present`, plus scope identifiers | IAM policy binding |
| `gcp_service_account` | `email`/`service_account`, `disabled`, `project` | Service account exists |
| `gcp_bigquery_dataset` | `dataset`, `location`, `project` | Dataset exists |
| `gcp_bigquery_query` | `sql`, `column`, `expect_value`, `expect_rows`, `min_rows`, `max_rows`, `project` | Query result |
| `gcp_vertex_endpoints` | `region`, `min_count`, `exact_count`, `name_contains`, `project` | Vertex endpoints exist |
| `gcp_subnet` | `subnet`, `region`, `network`, `purpose`, `private_ip_google_access`, `ip_cidr_range` | Compute subnet metadata |
| `gcp_network_attachment` | `network_attachment`/`name`, `region`, `subnet`, `connection_preference`, `producer_accept_lists`, `network` | PSC network attachment |
| `gcp_iam_permissions` | `permissions`, `expect` (`absent`/`present`), `project`, `http_timeout` | Effective permissions for the **calling** identity |

### IAM scopes

| `scope` | Identifiers | gcloud command used |
| ------- | ----------- | ------------------- |
| `project` | `project` | `projects get-iam-policy` |
| `bucket` | `bucket` | `storage buckets get-iam-policy` |
| `kms_key` | `keyring`, `key`, `location` | `kms keys get-iam-policy` |
| `subnet` | `subnet`, `region` | `compute networks subnets get-iam-policy` |
| `service_account` | `service_account` | `iam service-accounts get-iam-policy` |

`member` is a full IAM member string, for example
`serviceAccount:service-123@gcp-sa-aiplatform.iam.gserviceaccount.com` or
`user:someone@example.com`. Comparison is case-insensitive.

Set `present: false` to assert that a role is **not** granted. When
`present: false`, `role` may be omitted: the check then fails if the member
appears in **any** binding. This is how the public-bucket checks work:

```yaml
- title: Bucket is not public
  type: gcp_iam_binding
  params:
    scope: bucket
    bucket: "${bucket}"
    member: allUsers
    present: false
```

`gcp_iam_permissions` is different: it asks the Resource Manager
`testIamPermissions` API what the identity running the pack is effectively
allowed to do, including permissions inherited from folders and the
organisation. Use it for negative assertions:

```yaml
- title: Workbench identity cannot administer the project
  type: gcp_iam_permissions
  params:
    permissions:
      - resourcemanager.projects.setIamPolicy
      - resourcemanager.projects.delete
    expect: absent
```

The API only tests the caller's own permissions and only permissions that
apply to the **project** resource. It cannot answer "can this other user do
X?", and resource-scoped permissions (for example `storage.buckets.delete`)
belong in a resource-specific check such as `gcp_iam_binding` role absence.

### Resource name formats

The PSC checkers accept any of these forms:

```text
vertex-psc-attachment
regions/europe-west2/networkAttachments/vertex-psc-attachment
projects/my-project/regions/europe-west2/networkAttachments/vertex-psc-attachment
https://www.googleapis.com/compute/v1/projects/.../networkAttachments/...
```

Subnets accept the equivalent `subnetworks/` forms. If the project or region
is not in the value, it comes from `project` / `region` params or config.

### BigQuery

`gcp_bigquery_query` runs `bq query --nouse_legacy_sql --format=json`. The
default checks use `SELECT 1`, which creates a tiny job. `expect_value` is
compared as a string, so both `1` and `"1"` match `expect_value: "1"`.

## Jupyter

| Type | Params | Asserts |
| ---- | ------ | ------- |
| `jupyter_kernel` | `name` (default `python3`) | Kernel registered |
| `jupyter_extension` | `name`, `must_be_enabled` | JupyterLab extension state |

`jupyter_extension` parses `jupyter labextension list`. If the output format
changes in a future JupyterLab release, use a `command` check with a regex
instead.

## Plugin checks shipped with the pack

These live in `plugins/` and are loaded automatically. They require the
optional `gcp` extra (`pip install -e ".[gcp]"`).

| Type | Params | Asserts |
| ---- | ------ | ------- |
| `vertex_sdk_smoke` | `region` | Initialises the Vertex SDK and lists endpoints |
| `storage_roundtrip` | `bucket`, `prefix` | Writes, reads and deletes a tiny GCS object |
| `vertex_psc_sdk` | `network_attachment` | Installed SDK supports PSC interfaces on PipelineJob |
| `vertex_pipeline_psc` | `template_path`, `pipeline_root`, `network_attachment`, `region`, `service_account`, `dns_peering`, `wait`, `poll_seconds`, `cancel_on_timeout`, `display_name` | Submits and (optionally) waits for a real pipeline run using PSC-I |

`vertex_pipeline_psc` is disabled in the default checks because it creates a
Vertex AI Pipeline run. See [PSC networking](psc-networking.md) for how to
enable it safely.
