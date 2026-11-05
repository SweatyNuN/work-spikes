# Writing checks

A check is a YAML entry. You do not need to write Python to add a requirement,
unless the assertion genuinely needs code (then see [Plugins](plugins.md)).

## File anatomy

```yaml
category: Data tooling
description: Extra libraries the team relies on.

defaults:
  severity: warning
  tags: [data]

checks:
  - id: data.torch
    title: PyTorch is installed
    type: package
    params:
      name: torch
      import_name: torch
      version: ">=2.2"
    severity: critical       # overrides defaults for this check
    tags: [data, ml]         # overrides defaults for this check
    timeout: 120
    hint: pip install torch
```

* Files run in alphabetical order. Numeric prefixes (`00_`, `10_`) keep the
  report stable.
* `category` comes from the file, not the filename.
* An `id` is optional; it is derived from the title. IDs must be unique across
  the whole pack. Give explicit IDs to checks that CI or dashboards reference.
* Unknown keys are rejected with the file, check number and allowed keys.

## Check fields

| Field | Required | Notes |
| ----- | -------- | ----- |
| `title` | yes | Human-readable; becomes the derived id |
| `type` | yes | A type from [Check reference](check-reference.md) or a plugin |
| `params` | no | Type-specific settings |
| `id` | no | Stable identifier (`[A-Za-z0-9_.:-]+`) |
| `severity` | no | `critical` (default) or `warning` |
| `tags` | no | String or list; used by `--only` / `--skip` |
| `timeout` | no | Seconds; default from `testpack.default_timeout` |
| `enabled` | no | `false` documents a check without running it |
| `hint` | no | Suggested fix, shown on failure |

File-level `defaults` accepts only `severity`, `tags`, `timeout` and `enabled`.

## Severity, skips and readiness

| Outcome | Critical severity | Warning severity |
| ------- | ----------------- | ---------------- |
| Pass | green | green |
| Fail | **NOT READY** (exit 1) | yellow, does not block |
| Skip | visible; counted as a critical skip | visible |

Rules that prevent false greens:

* If every selected check is skipped → `INCOMPLETE` (exit 1).
* `--strict` treats warning failures **and critical skips** as failures.
* `enabled: false` skips are intentional and never count as critical skips.

Use warnings for "nice to have" tools (for example `kfp`). Use critical for
things that make the environment unusable or violate the platform contract.

## Values and conditional skips

Any `${...}` is resolved from config at run time:

```yaml
params:
  bucket: "${bucket}"
  member: "user:${expected_user}"
```

If a referenced value is missing or empty, the check is **skipped** with
`needs config value '...'`. That is how user-specific checks avoid failing in
service-account contexts.

Use a default when the parameter is optional:

```yaml
params:
  network: "${psc_network:-}"          # empty string, not a skip
  preference: "${psc_connection_preference:-ACCEPT_AUTOMATIC}"
```

Also available: `${env:NAME}` and `${env:NAME:-fallback}`.

## Recipes

### Python package

```yaml
- title: XGBoost
  type: package
  params:
    name: xgboost
    import_name: xgboost
    version: ">=2.0"
```

`name` is the pip distribution; `import_name` is what you would `import`.
The check verifies both metadata and that the import works. Set
`import_check: false` for a package whose import is very expensive.

### Shell command

```yaml
- title: DuckDB CLI works
  type: command
  params:
    command: ["duckdb", "--version"]
    stdout_contains: "v1."
```

A list runs without a shell; a string runs through the shell. You can assert
`expect_exit` (int or list), `stdout_contains`, `stdout_not_contains`,
`stdout_regex` and `stderr_contains`. `show_output: true` appends the first
line of stdout to the pass message.

### File or environment variable

```yaml
- title: Team bootstrap script is present
  type: file
  params:
    path: "${HOME}/bootstrap.sh"
    contains: "gcloud auth application-default login"

- title: Workbench region is exported
  type: env
  params:
    name: GOOGLE_CLOUD_REGION
    equals: "${region}"
```

### HTTP endpoint

```yaml
- title: Metadata server is reachable
  type: http
  params:
    url: "http://metadata.google.internal/computeMetadata/v1/project/project-id"
    headers:
      Metadata-Flavor: Google
    status: 200
```

### GCP infrastructure

```yaml
- title: Pipeline bucket exists with uniform access
  type: gcp_bucket
  params:
    bucket: "${bucket}"
    location: "${region}"
    uniform_access: true

- title: CMEK key rotates every 30 days
  type: gcp_kms_key
  params:
    keyring: "${kms_keyring}"
    key: "${kms_key}"
    location: "${kms_location}"
    rotation_days: 30

- title: Service agent can encrypt with the key
  type: gcp_iam_binding
  params:
    scope: kms_key
    keyring: "${kms_keyring}"
    key: "${kms_key}"
    location: "${kms_location}"
    role: roles/cloudkms.cryptoKeyEncrypterDecrypter
    member: "serviceAccount:${service_agent}"

- title: Notebooks API is enabled
  type: gcp_api_enabled
  params:
    api: notebooks.googleapis.com
```

### PSC networking

```yaml
- title: PSC subnet exists
  type: gcp_subnet
  params:
    subnet: "${psc_subnet:-}"
    region: "${psc_region:-}"
    purpose: PRIVATE_SERVICE_CONNECT

- title: PSC network attachment exists
  type: gcp_network_attachment
  params:
    network_attachment: "${psc_network_attachment:-}"
    subnet: "${psc_subnet:-}"
    connection_preference: "${psc_connection_preference:-ACCEPT_AUTOMATIC}"

- title: Vertex agent can use the subnet
  type: gcp_iam_binding
  params:
    scope: subnet
    subnet: "${psc_subnet:-}"
    region: "${psc_region:-}"
    role: roles/compute.networkUser
    member: "serviceAccount:${service_agent}"
```

See [PSC networking](psc-networking.md) for the full setup.

### Jupyter, GPU, disk

```yaml
- title: python3 kernel is installed
  type: jupyter_kernel
  params:
    name: python3

- title: JupyterLab extension is enabled
  type: jupyter_extension
  params:
    name: jupyterlab-git
    must_be_enabled: true

- title: A GPU is visible
  type: gpu
  params:
    min_count: 1
    name_contains: T4
    optional: false

- title: Home has free space
  type: disk
  params:
    path: "~"
    writable: true
    min_free_gb: 5
```

## Test a new check

```bash
python run.py --list                     # is it loaded, with the right type?
python run.py --only data.torch --verbose
python run.py --only "Data tooling"
```

If a check is skipped, add `--verbose` and read the reason. The most common
cause is an unset value in a `${...}` reference.

## YAML gotchas

* A plain string containing `: ` (colon-space) must be quoted:
  `description: "The contract: agent, key and bucket."`
* Quote version constraints (`">=3.10"`), otherwise YAML may read them as
  punctuation.
* `params` is a mapping. Use block style for readability; inline style works
  but is harder to review.
* Do not duplicate `id`s across files. The loader names both locations when it
  finds a duplicate.

Next: [Check reference](check-reference.md) to pick a type.
