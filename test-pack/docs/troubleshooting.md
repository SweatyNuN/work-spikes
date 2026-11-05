# Troubleshooting

## The pack will not start

### `error: PyYAML is required`

```bash
python -m pip install -r requirements.txt
# or
python -m pip install -e ".[dev]"
```

### `error: config file not found: ...`

`--config` or `TESTPACK_CONFIG` points at a missing file. Either fix the path
or run without it (the built-in defaults work for the Terraform in this repo).

### `unexpected top-level key(s)`

`config.yml` accepts only `testpack:` and `values:`. Move your custom keys
under `values:`.

### `unknown check type '...'`

The type is misspelled, or it comes from a plugin that failed to load. The
error lists every available type. Run `--list` after fixing the plugin.

### `could not load plugin ...`

A plugin raised during import. Run that file directly for the traceback:

```bash
python -c "import sys; sys.path.insert(0, '.'); import plugins.my_checks"
```

Common causes: a missing SDK, or a check name already registered by another
plugin.

### `no checks matched the --only/--skip filters`

The selector matched nothing. Check `--list`; selection is exact for ids,
tags, types and categories, and substring-only for ids.

## GCP checks fail

### `gcloud CLI not found`

Install the Google Cloud SDK. Inside a workbench it should already be present.
You can skip these checks with `--skip gcp` while working on local checks.

### `PermissionDenied` / `was not found or is not accessible`

The identity running the pack cannot see the resource. Remember that `gcloud`
uses the machine/service account identity, not the human user:

* Running inside a workbench uses the workbench VM service account.
* Running in Cloud Shell/locally uses your account.

Grant read access to whichever identity should run the gate.

### `Required Google Cloud APIs are enabled` fails

The failure detail lists the missing APIs and a ready-to-run
`gcloud services enable ...` command. Waiting for propagation can take a
minute on a fresh project.

### User IAM checks are skipped

`expected_user` is empty. Set it in `config.yml` or with
`--set expected_user=you@example.com`. `expected_user: auto` uses the active
gcloud account and ignores service accounts.

## Skips and readiness

### `RESULT: INCOMPLETE`

Every selected check was skipped. This usually means:

* `--only` selected a category whose config values are empty, or
* `enabled: false` on everything selected.

It is deliberately not green.

### A critical check is skipped

Look at the reason on the line. The common one is
`needs config value 'x'`. Either provide the value or mark the check as
`enabled: false` if it does not apply. `--strict` turns these into failures.

### `--strict` fails but the normal run is green

That is the intended behaviour. `--strict` treats warnings and critical skips
as failures. Either resolve them or do not use `--strict` for that
environment.

## Python and Jupyter checks

### `could not run command: executable not found: python`

Some images only expose `python3`. Change the YAML command to `python3` (or
`sys.executable` in a plugin).

### `package is installed but cannot be imported`

The distribution metadata exists but the import fails. The detail contains the
import error. This is a real base-image problem; rebuild or reinstall the
package.

### `jupyter command not found`

You are probably running outside a workbench. The runtime checks are meant to
run inside the instance; use `--skip workbench` on a laptop.

### `jupyter_extension` cannot parse the output

JupyterLab's text output is not a stable API. Replace the check with a
`command` type and a `stdout_regex`, or update the built-in checker.

## PSC-specific

| Symptom | Fix |
| ------- | --- |
| PSC checks all skip | Set `psc_network_attachment`, `psc_subnet` and `psc_region` |
| `PSC subnet exists` fails on purpose | Use a subnet with `purpose = PRIVATE_SERVICE_CONNECT` |
| `Vertex service agent can use the PSC subnet` fails | Grant `roles/compute.networkUser` on the subnet |
| `network attachment was not found` | Check region and the name/self-link format |
| Pipeline submit `InvalidArgument` | Confirm PSC-I availability for the project and that the attachment is in the same region |
| Pipeline task cannot reach VPC services | Check firewall rules and DNS; configure `dns_peering` |
| SDK check fails | Upgrade `google-cloud-aiplatform` |

See [PSC networking](psc-networking.md) for the full setup.

## Timeouts

Check-level `timeout` is the default for commands, gcloud calls, HTTP and the
pipeline wait. A `timeout` in `params` overrides it. If a cold `gcloud storage`
call is slow, raise the specific check's timeout rather than the global one.

## Report files

### `could not write JSON/JUnit`

The target directory is not writable. Use a path under the workspace (for
example `reports/result.json`) rather than a system directory. The pack
creates missing parent directories but cannot bypass filesystem permissions.

## Getting more detail

```bash
python run.py --only <selector> --verbose
```

`--verbose` shows full failure details, plugin tracebacks, resolved titles and
per-check timings. It never prints secret config values, but command output is
shown verbatim — be careful when sharing logs from an environment where
commands print credentials.
