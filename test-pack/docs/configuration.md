# Configuration

The same pack must work against a different project, region and set of
resource names every time UAT is rebuilt. Configuration is how that happens.

## Precedence

Later wins:

1. Built-in defaults (mirroring `../platform-terraform`)
2. `config.yml` (or the file passed to `--config` / `TESTPACK_CONFIG`)
3. `TESTPACK_*` environment variables
4. CLI flags (`--project-id`, `--set key=value`, …)

`config.yml` is gitignored in this repo. Never commit environment-specific
resource names, and never put secrets in it (use `${env:...}`).

## File shape

```yaml
testpack:
  checks_dir: checks
  plugins_dir: plugins
  default_timeout: 60

values:
  project_id: auto
  region: auto
  bucket: "bucket-name"
```

* `testpack` is runner configuration.
* `values` is your namespace. Anything in it is available as `${name}`.
* Unknown top-level keys are rejected with a clear error.

Generate a starting file with:

```bash
python run.py --init
```

## Value kinds

| Kind | Example | Behaviour |
| ---- | ------- | --------- |
| Literal | `region: europe-west2` | Used as-is |
| Discovered | `project_id: auto` | Resolved from env, metadata or gcloud |
| Derived | `bucket: "${project_id}-fucket"` | Other values substituted |
| Environment | `expected_user: "${env:DS_USER}"` | Read from the process environment |
| Optional override | `network: "${psc_network:-}"` | Empty fallback instead of an error |

Empty strings count as missing for `${...}`. That is deliberate: checks that
depend on an unset value are **skipped**, not failed. Use `:-` when a value is
genuinely optional.

### Auto discovery

`auto` resolves in this order:

| Key | Order |
| --- | ----- |
| `project_id` | `GOOGLE_CLOUD_PROJECT`, `GCLOUD_PROJECT`, `CLOUDSDK_CORE_PROJECT`, GCE metadata, `gcloud config` |
| `project_number` | `GOOGLE_CLOUD_PROJECT_NUMBER`, GCE metadata, `gcloud projects describe` |
| `region` | `GOOGLE_CLOUD_REGION`, `CLOUDSDK_COMPUTE_REGION`, `gcloud config`, derived from the zone |
| `zone` | `GOOGLE_CLOUD_ZONE`, `CLOUDSDK_COMPUTE_ZONE`, GCE metadata, `gcloud config` |
| `expected_user` | `gcloud config get-value account` (service accounts are ignored) |

This is why `python run.py` needs no arguments inside a workbench: the
metadata server supplies the project and zone.

## Built-in values

| Value | Default | Used by |
| ----- | ------- | ------- |
| `project_id` | `auto` | Most GCP checks |
| `project_number` | `auto` | Service agent and compute service account names |
| `region` | `auto` | Bucket/KMS/subnet defaults |
| `zone` | `auto` | Informational / your own checks |
| `bucket` | `${project_id}-fucket` | `gcp_bucket`, IAM, pipeline root |
| `kms_keyring` | `vertex-keyring` | KMS checks |
| `kms_key` | `vertex-cmek` | KMS checks |
| `kms_location` | `${region}` | KMS checks |
| `service_agent` | `service-${project_number}@gcp-sa-aiplatform.iam.gserviceaccount.com` | Service agent and IAM checks |
| `compute_service_account` | `${project_number}-compute@developer.gserviceaccount.com` | User IAM check |
| `expected_user` | `""` | User IAM checks (empty = skip) |
| `psc_network_attachment` | `""` | PSC checks and pipeline test |
| `psc_subnet` | `""` | PSC checks |
| `psc_network` | `""` | Optional PSC network assertion |
| `psc_region` | `${region}` | PSC checks |
| `psc_connection_preference` | `ACCEPT_AUTOMATIC` | PSC attachment check |
| `pipeline_template` | `""` | Real PSC pipeline run (optional) |
| `pipeline_root` | `gs://${bucket}/pipeline-root` | Real PSC pipeline run |
| `pipeline_service_account` | `""` | Real PSC pipeline run (optional) |

Override any of them without editing the file:

```bash
python run.py --set bucket=uat-data-bucket --set kms_key=vertex-cmek-v2
python run.py --project-id my-uat-123 --region europe-west2
```

## Environment variables

| Variable | Effect |
| -------- | ------ |
| `TESTPACK_PROJECT_ID` | Overrides `project_id` |
| `TESTPACK_PROJECT_NUMBER` | Overrides `project_number` |
| `TESTPACK_REGION` | Overrides `region` |
| `TESTPACK_ZONE` | Overrides `zone` |
| `TESTPACK_CONFIG` | Default config file when `--config` is absent |
| `TESTPACK_ROOT` | Directory containing `checks/` and `plugins/` |
| `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_REGION` | Inputs to `auto` discovery |
| `NO_COLOR` | Disable ANSI colour |

Use `${env:NAME}` inside `config.yml` for everything else. That keeps secrets
out of the file:

```yaml
values:
  expected_user: "${env:DS_USER}"
  # Required value with no safe default:
  # pipeline_service_account: "${env:PIPELINE_SA}"
```

## Directory and root resolution

The runner needs a directory containing `checks/` and `plugins/`. It picks:

1. `TESTPACK_ROOT`, if set
2. the current working directory, if it contains `checks/`
3. the directory containing the installed package (the repo for editable
   installs)

`--checks-dir` and `--plugins-dir` override the individual directories.

## Who runs the checks?

`gcloud` uses the identity of the machine running the pack. Inside a
workbench that is the workbench VM's service account, **not** the human user.

* Run it **inside the workbench** to validate the runtime users get.
* Run it from **Cloud Shell or your laptop as yourself** to prove a specific
  person can read/use the resources.
* The user-IAM checks read policy bindings; they do not impersonate the user.

Consequence: a restricted workbench service account can make infrastructure
checks fail even when the resources are correct. Grant it read access (or run
the pack from a context that has it).

> The Terraform variable `workbench_user_email` grants access, and the test
> pack's `expected_user` asserts it. Keep them in sync.

## Example: UAT project

```yaml
testpack:
  default_timeout: 90

values:
  project_id: my-uat-123
  project_number: "456789012345"
  region: europe-west2
  zone: europe-west2-a

  bucket: my-uat-data-bucket
  kms_keyring: vertex-keyring
  kms_key: vertex-cmek
  expected_user: data-science@example.com

  # PSC (from terraform output)
  psc_network_attachment: projects/my-uat-123/regions/europe-west2/networkAttachments/vertex-psc-attachment
  psc_subnet: vertex-psc-subnet
  psc_network: my-vpc
  psc_region: europe-west2
```

## Example: CI override

No config file, everything passed in:

```bash
python run.py \
  --project-id "$PROJECT_ID" \
  --region "$REGION" \
  --set bucket="$PIPELINE_BUCKET" \
  --set expected_user="$DS_USER" \
  --set psc_network_attachment="$PSC_ATTACHMENT" \
  --strict \
  --json reports/result.json
```

Next: [Writing checks](writing-checks.md).
