# Plugins

Use a plugin when the assertion needs code: the Python SDK, a non-trivial
computation, a library call, or state that is awkward to express as a command.
If a `command` or `python_import` check can express it, prefer the YAML check —
it is easier to review and needs no code.

## Registering a check type

Create `plugins/my_checks.py`:

```python
from testpack.models import Outcome
from testpack.registry import check


@check("team_tooling_smoke", "Run the team's internal validation helper")
def team_tooling_smoke(ctx, params):
    project = ctx.get("project_id")
    if not project:
        return Outcome.skip("needs config value 'project_id'")

    result = ctx.run(
        ["team-tool", "self-test", "--project", project],
        timeout=params.get("timeout") or 60,
    )
    if not result.ok:
        return Outcome.fail(
            "team-tool self-test failed",
            detail=result.detail(),
            hint="Check the internal package version and its configuration.",
        )

    return Outcome.ok("team-tool self-test passed")
```

Then use it like any built-in type:

```yaml
- title: Internal tooling self-test
  type: team_tooling_smoke
  tags: [team]
```

Plugins are imported in filename order before checks are loaded. A plugin that
raises at import time stops the run with a message naming the file. A plugin
that raises **inside a check** becomes a failed check with a traceback (shown
with `--verbose`), so one bad plugin cannot take down the pack.

Check type names must be unique. A duplicate is rejected at load time.

## Outcome

Return exactly one of:

```python
Outcome.ok("message", detail="optional detail")
Outcome.fail("message", detail="...", hint="suggested fix")
Outcome.skip("why it did not run", hint="optional")
```

`detail` is shown for failures and with `--verbose`. `hint` is shown for
failures. Keep `message` short; put command output and raw payloads in
`detail`.

Raise nothing for an expected failure. Exceptions are treated as bugs in the
check, not as environment failures.

## Context API

| Helper | Purpose |
| ------ | ------- |
| `ctx.get("key")` | Resolved config value, or `None` if missing |
| `ctx.values.get("key")` | Resolved value; raises `MissingValue` |
| `ctx.values.resolved()` | All resolvable values as a dict |
| `ctx.run(command, timeout=..., cwd=..., env=..., shell=...)` | Run a command; never raises for non-zero exit or timeout |
| `ctx.gcloud(args, project=..., timeout=...)` | Run gcloud with `--project` appended |
| `ctx.resolve_path(value)` | Expand `~` and resolve relative to the pack root |
| `ctx.default_timeout` | Default timeout in seconds |

`ctx.run` returns `CommandResult`:

| Attribute | Meaning |
| --------- | ------- |
| `.ok` | Exit 0, not timed out, no launch error |
| `.returncode` | Exit code (`124` on timeout, `127` if not found) |
| `.stdout`, `.stderr` | Captured text |
| `.timed_out` | Timeout flag |
| `.error` | Launch error, if any |
| `.detail()` | Formatted command, exit code, stdout and stderr |

## Testing plugins

Plugins are ordinary Python. Test them with pytest by constructing a small
stub context (see `tests/test_gcp_checkers.py` for an example), or inject a
fake `CommandResult` through `Context.run` using monkeypatch. You do not need
a live cloud project to test the parsing and branching.

## Bundled plugins

| File | Checks | Dependency |
| ---- | ------ | ---------- |
| `plugins/vertex_ai.py` | `vertex_sdk_smoke` | `google-cloud-aiplatform` |
| `plugins/storage_roundtrip.py` | `storage_roundtrip` | `google-cloud-storage` |
| `plugins/vertex_pipeline_psc.py` | `vertex_psc_sdk`, `vertex_pipeline_psc` | `google-cloud-aiplatform` |

Install the optional dependency set with:

```bash
python -m pip install -e ".[gcp]"
```

## A note on the PSC pipeline plugin

In the 2.x SDK, `aiplatform.PipelineJob` does not yet accept
`psc_interface_config` as a constructor argument, even though the underlying
proto field exists. `vertex_pipeline_psc` therefore sets the field on
`job._gca_resource` before `submit()`. This is a deliberate, localised use of a
private attribute; `vertex_psc_sdk` verifies the proto field is present before
the real test runs. If a future SDK adds a public argument, the plugin is the
only place that needs to change.
