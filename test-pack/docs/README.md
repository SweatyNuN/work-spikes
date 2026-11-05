# test-pack documentation

This folder is the long-form documentation for the workbench readiness pack.
`README.md` at the pack root is the short version; these pages are the
reference you keep coming back to.

## Start with your role

| You are… | Read |
| -------- | ---- |
| Running the pack for the first time | [Getting started](getting-started.md) |
| Wiring it into a UAT project or pipeline | [Configuration](configuration.md), then [CI](ci.md) |
| Adding or changing a requirement | [Writing checks](writing-checks.md) |
| Looking up a check parameter | [Check reference](check-reference.md) |
| Writing Python for a custom assertion | [Plugins](plugins.md) |
| Setting up PSC for Vertex Pipelines | [PSC networking](psc-networking.md) |
| Fixing a red or skipped result | [Troubleshooting](troubleshooting.md) |

## The mental model

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

Four ideas explain most of the tool:

1. **Values** are dynamic inputs (project ID, region, bucket, PSC attachment).
   They come from defaults, `config.yml`, environment variables and CLI flags.
2. **Checks** are declarative requirements in YAML. A check has a `title`, a
   `type`, optional `params`, and a `severity`. Files in `checks/` run in
   filename order.
3. **Check types** are the built-in behaviours (`package`, `command`,
   `gcp_bucket`, `gcp_network_attachment`, …). They are documented in
   [Check reference](check-reference.md).
4. **Plugins** are the escape hatch. A Python function decorated with
   `@check("name")` becomes a new check type. Everything the built-in types
   can do is available to plugins through `ctx`.

## Running it

Three ways, all equivalent:

```bash
# From the pack directory, no install step beyond PyYAML
python run.py

# As an editable install, from anywhere
python -m pip install -e ".[dev]"
test-pack

# From another directory that contains its own checks/
TESTPACK_ROOT=/path/to/test-pack test-pack
```

`TESTPACK_ROOT` wins over auto-discovery. Otherwise the runner uses the
current directory if it contains `checks/`, then the directory containing the
installed package.

## Vocabulary

| Term | Meaning |
| ---- | ------- |
| **value** | A named input available as `${name}` in config and checks |
| **check** | One YAML entry: a requirement and how to test it |
| **check type** | The implementation used by a check (`package`, `command`, …) |
| **plugin** | A Python module in `plugins/` registering custom check types |
| **severity** | `critical` (red, blocks readiness) or `warning` (yellow) |
| **skip** | A check that did not run, with a visible reason |
| **blocked skip** | A critical check skipped for missing config; visible, and fails `--strict` |
| **INCOMPLETE** | Nothing was actually verified because every selected check skipped |
