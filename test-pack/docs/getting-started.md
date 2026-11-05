# Getting started

## Prerequisites

| Requirement | Why |
| ----------- | --- |
| Python 3.9+ | The runner itself |
| PyYAML | The only runtime dependency |
| `gcloud` | Built-in GCP checks and auto-discovery |
| A Vertex AI Workbench | For the default runtime checks (Jupyter, packages, disk) |
| Application Default Credentials | What `gcloud` and the Vertex SDK use |

Inside a workbench, `gcloud` and ADC are normally already configured. On a
laptop or in Cloud Shell, run:

```bash
gcloud auth login
gcloud auth application-default login
```

## Install and run

```bash
cd test-pack
python -m pip install -r requirements.txt
python run.py
```

`config.yml` is optional. Without it the pack uses `auto` discovery and the
resource names from `../platform-terraform`.

The pack is designed to run from this repo. If you install it non-editable
rather than with `-e`, run it from a directory that contains `checks/` or set
`TESTPACK_ROOT` to the pack directory.

To keep an environment-specific config file:

```bash
python run.py --init      # creates config.yml from config.example.yml
```

## Reading the output

```text
test-pack v1.2.0  Vertex AI Workbench readiness

  project         work-spikes-492917
  project number  754536297652
  region          europe-west2
  config          config.yml

Environment
  ✓ Python is 3.10 or newer                     Python 3.11.9 (CPython) satisfies >=3.10
  ✓ pip is available                            command exited 0
  ✗ Jupyter is available
      could not run command: executable not found: jupyter
      hint: This pack is meant to be run inside a Vertex AI Workbench instance.

----------------------------------------------------------------
  2 passed | 1 failed | 1 warning(s) | 2 skipped (1 critical) | 4.2s
  RESULT: NOT READY
```

| Symbol | Meaning |
| ------ | ------- |
| `✓` | Passed |
| `✗` | Critical failure: the deployment is not ready |
| `!` | Warning: visible, but does not block by default |
| `–` | Skipped: see the reason on the line |

Exit codes:

| Code | Meaning |
| ---- | ------- |
| `0` | Ready: no critical failures (warnings allowed) |
| `1` | Not ready, incomplete, or `--strict` found a warning/critical skip |
| `2` | The pack could not run (bad config/YAML, missing PyYAML, unwritable report) |

Two non-obvious rules:

* If **every** selected check is skipped, the result is `INCOMPLETE`, not
  `READY`.
* Critical checks that skip (usually because a config value is empty) are
  counted in the summary. `--strict` makes them fail the run, which is what a
  release gate should use.

## Add your first check

Create `checks/70_team.yml`:

```yaml
category: Team tooling
description: Extra requirements for the data science team.

checks:
  - title: PyTorch is installed
    type: package
    params:
      name: torch
      import_name: torch
      version: ">=2.2"
    hint: pip install torch

  - title: Internal CLI works
    type: command
    params:
      command: ["team-tool", "self-test"]
    tags: [team]
```

Run only this category:

```bash
python run.py --only "Team tooling" --verbose
```

If the file has a typo, the loader tells you the file, the check number and
the allowed keys. It never silently ignores a misspelled key.

## Common commands

```bash
python run.py                          # everything
python run.py --only gcp               # tag/type/category/id substring
python run.py --skip integration       # omit slow or mutating checks
python run.py --list                   # inspect the pack without running it
python run.py --verbose                # show details for passes too
python run.py --quiet                  # failures, warnings and summary only
python run.py --strict                 # release gate: warnings/skips fail
python run.py --json reports/result.json --junit reports/junit.xml
python run.py --project-id my-uat-123 --region europe-west2
python run.py --set bucket=my-bucket --set expected_user=me@example.com
```

Next: [Configuration](configuration.md) for dynamic environments, or
[Writing checks](writing-checks.md) for the full YAML vocabulary.
