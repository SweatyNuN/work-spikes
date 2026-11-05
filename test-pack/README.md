# test-pack

A small, declarative readiness pack for a **Vertex AI Workbench** deployment.

Clone it into the workbench, run one command, and get a green/red answer about
whether the environment is actually usable: the right Python, the right
packages, the expected GCP resources, the right IAM, PSC networking for Vertex
Pipelines, and working integrations.

```bash
python -m pip install -r requirements.txt
python run.py
```

The pack is built for **dynamic UAT environments**: project IDs, regions,
buckets, KMS names and PSC attachments are discovered or supplied at run time,
never hardcoded in the checks. The same repo is the release gate for the
provisioning templates in [`../platform-terraform`](../platform-terraform).

> **Documentation:** [docs/](docs/README.md) contains the detailed guides.
> Start with [Getting started](docs/getting-started.md) if this is your first
> run, or [PSC networking](docs/psc-networking.md) if you are wiring PSC.

## Quick start

```bash
# From this directory
python -m pip install -r requirements.txt
python run.py

# Target another environment explicitly
python run.py --project-id my-uat-123 --region europe-west2

# Optional: create an environment-specific config.yml
python run.py --init

# Or install the package and use the console script
python -m pip install -e ".[dev]"
test-pack
```

Exit codes: `0` ready, `1` not ready/incomplete (or `--strict` found a
warning or critical skip), `2` the pack could not run.

## What it checks

| Category | Examples |
| -------- | -------- |
| Environment | Python version, pip, Jupyter, gcloud, writable persistent disk |
| Python packages | Vertex SDK, GCS, BigQuery, KMS, pandas, numpy, scikit-learn, JupyterLab, kfp |
| GCP APIs | Every API enabled by `platform-terraform/api.tf` |
| GCP infrastructure | Vertex service agent, CMEK key + rotation + IAM, pipeline bucket + IAM |
| PSC networking | PSC subnet, network attachment, Vertex agent network IAM, SDK support |
| User access | `roles/aiplatform.user`, act-as on the compute service account |
| Workbench runtime | `python3` kernel, JupyterLab extensions |
| Negative controls | Public web egress blocked, no project-admin permissions, no public project/bucket bindings, no KMS admin role |
| Integrations | Vertex SDK smoke test, BigQuery query, optional GCS round-trip, optional real pipeline run over PSC |

The default pack mirrors the Terraform in this repo. Rename or add checks
without touching the runner.

## How it works

```text
config.yml + environment
        │
        ▼
     values  ──────────────┐
        │                  │  ${project_id}, ${bucket}, ${env:HOME}
        ▼                  │
  checks/*.yml  ── runner ─┴─> console + JSON + JUnit
        │
        └── plugins/*.py (optional Python)
```

* **Checks are YAML.** A title, a type and a few parameters. No Python needed
  for the common cases.
* **One runner** owns config resolution, `gcloud` execution, timeouts, skip
  semantics and reporting.
* **Plugins** are the escape hatch for anything that needs the Python SDK or
  custom logic.

## Add a check

Create `checks/70_team.yml`:

```yaml
category: Team tooling

checks:
  - title: PyTorch is installed
    type: package
    params:
      name: torch
      import_name: torch
      version: ">=2.2"
    hint: pip install torch
```

```bash
python run.py --only "Team tooling"
```

See [Writing checks](docs/writing-checks.md) for recipes, and
[Check reference](docs/check-reference.md) for every type and parameter.

## Configuration

Values resolve as: built-in defaults → `config.yml` → `TESTPACK_*` env vars →
CLI flags.

```yaml
values:
  project_id: auto
  region: auto
  bucket: "bucket-name"
  expected_user: ""
```

* `auto` discovers project/region/number from environment, GCE metadata or
  `gcloud config`.
* `${...}` derives one value from another; `${env:NAME}` reads the process
  environment.
* Empty values skip dependent checks rather than failing them.

See [Configuration](docs/configuration.md) for the full value table, identity
caveats and CI examples.

## PSC for Vertex AI Pipelines

The Terraform now supports optional PSC-I resources (subnet, network
attachment, service-agent IAM), and the pack validates them:

```bash
# From platform-terraform
terraform apply -var 'enable_psc=true' -var 'psc_network=my-vpc'
terraform output -raw psc_network_attachment

# From test-pack
python run.py --only psc \
  --set psc_network_attachment="$PSC_ATTACHMENT" \
  --set psc_subnet=vertex-psc-subnet \
  --set psc_network=my-vpc
```

A real pipeline run over PSC is available as an opt-in check
(`integration.pipeline-psc`) using `examples/psc_pipeline.py`. It creates a
Vertex AI Pipeline run, so it is disabled by default. Full details, including
DNS peering and troubleshooting, are in
[PSC networking](docs/psc-networking.md).

## Documentation

| Page | Contents |
| ---- | -------- |
| [docs/README.md](docs/README.md) | Index, mental model, vocabulary |
| [Getting started](docs/getting-started.md) | Install, first run, reading output, first check |
| [Configuration](docs/configuration.md) | Values, auto discovery, precedence, identity |
| [Writing checks](docs/writing-checks.md) | YAML schema, recipes, skip semantics |
| [Check reference](docs/check-reference.md) | Every type and parameter |
| [Plugins](docs/plugins.md) | Custom Python checks and the context API |
| [PSC networking](docs/psc-networking.md) | Terraform + validation + real pipeline run |
| [CI](docs/ci.md) | Release gates, JSON/JUnit, Cloud Build/GitHub Actions |
| [Troubleshooting](docs/troubleshooting.md) | Common failures and fixes |
| [AGENTS.md](AGENTS.md) | Working guide for coding agents changing the pack |

## Why not pytest?

pytest is excellent for code-level tests and a poor fit for the primary
authoring experience here:

* The people adding checks are infrastructure and data people. A YAML entry is
  reviewable by anyone; a pytest function brings imports, fixtures, collection
  rules and parametrisation for what is usually one assertion.
* The hard parts are dynamic config, auto-discovery, cloud execution, consistent
  skip semantics and a readable report. Those live in the runner regardless of
  framework.
* The runner emits JUnit XML, so CI gets standard reporting without pytest.

The tradeoff is no fixtures or `pytest-xdist`. Plugins cover arbitrary Python,
and the runner's checkers can be reused as pytest fixtures if the pack ever
grows into hundreds of stateful checks.

## Layout

```text
test-pack/
├── run.py                    python run.py
├── pyproject.toml            packaging, dependencies, pytest/ruff config
├── config.example.yml        documented template; copy to config.yml
├── checks/                   the pack: one YAML file per category
├── plugins/                  optional Python checks
├── docs/                     long-form documentation
├── examples/psc_pipeline.py  minimal pipeline for the PSC integration test
├── testpack/                 the runner
└── tests/                    tests for the runner (pytest)
```

Files in `checks/` run in alphabetical order. Categories come from each file,
not the filename.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
```

The only runtime dependency is PyYAML. `google-cloud-aiplatform` and
`google-cloud-storage` are optional, used by the bundled plugins:
`python -m pip install -e ".[gcp]"`.
