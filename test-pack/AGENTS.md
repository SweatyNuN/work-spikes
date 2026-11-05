# AGENTS.md — working in test-pack

This file is for coding agents (and humans) changing the workbench readiness
pack. Read it before touching the runner, checks, plugins, docs or the related
Terraform.

## What this project is

`test-pack` is a **declarative readiness checker**, not a conventional pytest
project. Requirements live in `checks/*.yml`. A small Python runner resolves
environment-specific values, executes each check, and produces a console
report plus JSON/JUnit. Python is only needed for the runner itself and for
optional plugin checks.

The pack is cloned into a deployed Vertex AI Workbench, run, and used as the
release gate for the Terraform in `../platform-terraform`.

## Golden rules

1. **Prefer YAML.** If a requirement can be expressed with an existing check
   type, add a YAML check. Only add Python when the assertion needs code.
2. **Keep runtime dependencies at PyYAML.** The built-in checkers use the
   standard library plus `gcloud`. SDKs belong in optional extras or inside
   plugin functions (lazy imports).
3. **Never commit `config.yml` or generated reports.** They are
   environment-specific. Use `config.example.yml` as the template.
4. **Checkers return `Outcome`.** Do not raise for an expected failure. Return
   `Outcome.ok`, `Outcome.fail` or `Outcome.skip`. Exceptions are treated as
   bugs in the check.
5. **A skip is not a pass.** A critical skip is surfaced and fails `--strict`.
   If every selected check skips, the result is `INCOMPLETE`, not `READY`.
6. **Keep docs in sync.** Behavior changes belong in `README.md` and the
   relevant file under `docs/`.
7. **Bump the version** in `testpack/__init__.py` for user-visible changes
   (`pyproject.toml` reads it dynamically).
8. **Do not run mutating or live cloud checks by default.** The GCS round-trip
   and real PSC pipeline run are disabled for a reason.

## Where things live

| Path | Purpose |
| ---- | ------- |
| `run.py` | Developer entry point: `python run.py` |
| `testpack/cli.py` | Argument parsing, selection, exit codes, report wiring |
| `testpack/config.py` | Defaults, `config.yml` loading, auto-discovery, `Values`, root detection |
| `testpack/interpolate.py` | `${value}`, `${value:-default}`, `${env:NAME}` |
| `testpack/loader.py` | YAML validation, duplicate IDs, plugin imports |
| `testpack/runner.py` | Selection, interpolation, execution, failure wrapping |
| `testpack/registry.py` | `@check("name")` registry |
| `testpack/models.py` | `CheckSpec`, `Outcome`, `Result` |
| `testpack/context.py` | `Context.run`, `Context.gcloud`, command results |
| `testpack/report.py` | Console, JSON and JUnit output; readiness summary |
| `testpack/gcp_names.py` | Network attachment/subnet resource-name parsing |
| `testpack/checkers/` | Built-in check types (Python, system, GCP, Jupyter) |
| `checks/` | The actual pack: one YAML file per category, filename order |
| `plugins/` | Optional Python check types, auto-loaded |
| `tests/` | Runner and parser tests (pytest) |
| `docs/` | Long-form documentation |
| `examples/` | Example pipeline for the PSC integration check |
| `../platform-terraform/` | Provisioning templates validated by this pack |

## How it runs

Normal use:

```bash
python -m pip install -r requirements.txt
python run.py
```

Development:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev,gcp]"
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

`.[dev]` installs pytest/ruff; `.[gcp]` is needed for the bundled Vertex/GCS
plugins and their tests. CI often only needs `requirements.txt`.

The `test-pack` console script and `python run.py` are equivalent. The root
directory (containing `checks/` and `plugins/`) is discovered from
`TESTPACK_ROOT`, the current directory, or the installed package location.

## Data flow

```text
defaults -> config.yml -> TESTPACK_* env -> CLI overrides
                         |
                         v
                  Values (${...})
                         |
checks/*.yml -> loader -> runner -> checker(ctx, params) -> Outcome
                         |
                         +-> plugins/*.py
                         |
                         v
              console + JSON + JUnit + exit code
```

Config precedence is implemented in `testpack/config.py`; keep
`DEFAULT_VALUES`, `config.example.yml` and `docs/configuration.md` aligned.

## Adding a YAML check (most common task)

1. Add an entry to an existing `checks/*.yml` or create a new file with a
   numeric prefix (for example `checks/70_team.yml`).
2. Use a type from `docs/check-reference.md`.
3. Give it a unique `id` if CI or dashboards will reference it.
4. Use `${value}` from config. For genuinely optional values use
   `${value:-}` so an empty value does not skip the whole check.
5. Validate:

```bash
python run.py --list
python run.py --only <id-or-category> --verbose
```

Schema reminders:

- Required: `title`, `type`.
- Optional: `id`, `params`, `severity`, `tags`, `timeout`, `enabled`, `hint`.
- File-level `defaults` supports only `severity`, `tags`, `timeout`, `enabled`.
- Unknown keys are rejected on purpose. Do not silence that.
- Quote plain strings containing `: ` and version constraints.

## Adding a check type (Python)

1. Put built-in types in the matching module under `testpack/checkers/`.
   New modules must be imported from `testpack/checkers/__init__.py`.
2. Use the decorator and return `Outcome`:

```python
from ..models import Outcome
from ..registry import check


@check("my_check", "Assert something the built-ins cannot")
def my_check(ctx, params):
    value = params.get("value")
    if not value:
        return Outcome.skip("needs a 'value' param")
    result = ctx.run(["some-tool", value], timeout=params.get("timeout") or 30)
    if not result.ok:
        return Outcome.fail("some-tool failed", detail=result.detail())
    return Outcome.ok("some-tool passed")
```

3. If the type needs an optional SDK, put it in `plugins/` instead, and import
   the SDK **inside the function**. Plugins are loaded automatically.
4. Use `ctx.run` / `ctx.gcloud` so timeouts, capture and error handling stay
   consistent.
5. Add tests. Parser-style tests with a stub context and synthetic JSON are the
   norm; see `tests/test_gcp_checkers.py`. Do not require a live GCP project.
6. Document the type and its params in `docs/check-reference.md`. If it is a
   plugin, also update `docs/plugins.md`.

Check names are global. Duplicate registration is a load error.

## Timing and params

- The loader stores the check-level `timeout`.
- `runner.run_one` injects it into `params` as `timeout` unless the check
  already set one.
- Checkers that run commands should use `params.get("timeout") or default`.
- Do not add ad-hoc global timeouts in checkers.

## Outcome and report semantics

| Situation | Behavior |
| --------- | -------- |
| Check returns `Outcome.fail`, severity critical | `NOT READY`, exit 1 |
| Check returns `Outcome.fail`, severity warning | yellow, does not block unless `--strict` |
| Check returns `Outcome.skip` | visible reason; count depends on severity |
| Missing `${value}` during interpolation | runner converts it to a skip |
| Check raises | failed check with traceback under `--verbose` |
| All selected checks skip | `INCOMPLETE`, exit 1 |
| `--strict` with a warning or critical skip | exit 1 |

`report.py` is the single source of truth for JSON/JUnit shapes and readiness.
If you change the summary, update `docs/ci.md` and any tests that inspect it.

## GCP checks

- Built-in GCP checks shell out to `gcloud`; no Python SDK is required.
- Most resource params default to matching config values (for example
  `bucket`, `keyring`, `kms_location`, `project`).
- The identity is the machine running the pack. Inside a workbench this is the
  VM service account, not the human user. Do not "fix" a permission failure by
  changing the check until you have confirmed which identity is running.
- Prefer parser tests with realistic `gcloud --format=json` payloads. The
  sandbox/dev machine usually cannot reach GCP.
- Use `gcp_names.py` for subnets and network attachments. Do not reimplement
  resource-name parsing.

## PSC networking

PSC support is end-to-end:

| Layer | Files |
| ----- | ----- |
| Terraform | `../platform-terraform/psc.tf`, `variables.tf`, `outputs.tf` |
| Checks | `checks/35_psc_networking.yml` |
| Check types | `gcp_subnet`, `gcp_network_attachment`, `gcp_iam_binding` scope `subnet` |
| Plugins | `plugins/vertex_pipeline_psc.py` |
| Example | `examples/psc_pipeline.py` |
| Docs | `docs/psc-networking.md` |

Important constraints:

- PSC resources are optional and **off by default** (`enable_psc = false`).
  Keep it that way so existing deployments do not change.
- The VPC is existing; the Terraform only creates the PSC subnet and network
  attachment.
- The subnet purpose is `PRIVATE_SERVICE_CONNECT`; do not reuse a general
  subnet.
- The Vertex service agent needs `roles/compute.networkUser` on the subnet.
- In `google-cloud-aiplatform` 2.x, the high-level `PipelineJob` wrapper does
  not accept `psc_interface_config`. The plugin sets it on
  `job._gca_resource` before `submit()`. `vertex_psc_sdk` verifies the proto
  field exists. Keep that workaround localised; do not spread private-attribute
  access through the codebase.
- `integration.pipeline-psc` creates a real Vertex AI Pipeline run. Keep it
  disabled unless explicitly asked to exercise it.
- PSC-I availability can depend on project allowlisting/region. Report that as
  a caveat, do not encode a workaround.

## Terraform guardrails

- Provider project/region now come from `var.project_id` / `var.region`.
- Do not reintroduce a `GOOGLE_CREDENTIALS` Terraform variable; the provider
  reads the env var directly. Prefer ADC or Workload Identity Federation.
- `workbench_user_email` controls human IAM access and defaults to the
  original developer account. Keep the default for backwards compatibility.
- Keep PSC resources behind `count = var.enable_psc ? 1 : 0` and use `one(...)`
  in outputs.
- If `terraform` is available, run `terraform fmt -recursive` and
  `terraform validate`. If it is not, say so explicitly in the final summary.

## Testing conventions

- Tests use `sys.executable`, not `python`/`python3`, because the executable
  name is not portable.
- Synthetic gcloud JSON is preferred over live calls.
- PSC plugin tests are skipped when the optional `gcp` extra is not installed.
- Add tests for parsing, branching and skip behavior, not just happy paths.
- Do not add tests that mutate cloud state or submit pipeline jobs.

## Docs conventions

- `README.md` is the overview; `docs/` is the source of truth.
- Update the relevant doc whenever you change config keys, check params,
  readiness semantics, PSC behavior or developer commands.
- Keep examples copy-pasteable and consistent with `config.example.yml`.
- The docs index is `docs/README.md`.

## Common pitfalls

| Pitfall | Correct approach |
| ------- | ---------------- |
| Unquoted YAML `: ` | Quote the string |
| Optional value skips whole check | Use `${value:-}` and guard in code |
| Duplicate check id across files | Loader rejects it; make ids unique |
| Check type added but not registered | Built-ins: import module in `checkers/__init__.py`. Plugins: auto-loaded |
| Heavy SDK imported at plugin import time | Import inside the check function |
| `python` in tests | Use `sys.executable` |
| Treating a skip as success | Check `critical_skipped` / `INCOMPLETE` semantics |
| Committing `config.yml` | It is gitignored; use the example |
| Putting secrets in config | Use `${env:NAME}` |
| Adding runtime dependencies | Use optional extras in `pyproject.toml` |
| Editing generated files | Never edit `.venv`, `*.egg-info`, `__pycache__`, `reports/` |
| Running live/mutating checks | Leave them disabled unless asked |

## Definition of done

Before handing work back:

- [ ] `pytest` passes.
- [ ] `ruff check .` and `ruff format --check .` pass.
- [ ] `test-pack --list` (or `python run.py --list`) loads all checks.
- [ ] New checks/types have tests and docs.
- [ ] New config keys exist in `DEFAULT_VALUES`, `config.example.yml` and
      `docs/configuration.md`.
- [ ] Version bumped for user-visible changes.
- [ ] No `config.yml`, reports, caches or `.venv` artifacts are left behind.
- [ ] If Terraform changed, `terraform fmt`/`validate` was run or explicitly
      called out as not run.
- [ ] Final summary states what was validated and what could only be tested in
      UAT (especially live GCP and PSC pipeline runs).
