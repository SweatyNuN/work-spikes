# CI and release gates

The pack is designed to be the last step in a provisioning pipeline: apply
Terraform, run the checks, publish the report, and only then release the
template to users.

## What CI should run

```bash
python -m pip install -r requirements.txt
python run.py \
  --project-id "$PROJECT_ID" \
  --region "$REGION" \
  --strict \
  --json reports/result.json \
  --junit reports/junit.xml
```

`--strict` is the important flag for a release gate. It makes warnings and
critical skips fail, so "we could not check it" is not mistaken for "it is
fine".

`requirements.txt` only installs PyYAML. If you use the bundled GCP plugins,
install the extra:

```bash
python -m pip install -e ".[gcp]"
```

## Exit codes

| Code | Meaning |
| ---- | ------- |
| `0` | Ready |
| `1` | Critical failure, `INCOMPLETE`, or a `--strict` warning/skip |
| `2` | The pack could not run (bad config/YAML, missing dependency, report write failure) |

## Selecting checks in a pipeline

```bash
python run.py --only gcp --only psc          # platform checks only
python run.py --skip integration             # skip slow/mutating checks
python run.py --skip slow                    # tags work too
```

Selection matches an exact id, an id substring, a tag, a type or a category.
If nothing matches, the pack exits `2` instead of reporting a vacuous success.

## Reports

### JSON

Stable shape for dashboards and drift diffs:

```json
{
  "tool": "test-pack",
  "version": "1.2.0",
  "generated_at": "2026-11-05T21:00:00+00:00",
  "config": { "project_id": "...", "region": "..." },
  "summary": {
    "total": 34,
    "passed": 29,
    "failed": 0,
    "warnings": 1,
    "skipped": 4,
    "critical_skipped": 3,
    "incomplete": false,
    "ready": true,
    "duration_s": 21.4
  },
  "checks": [
    {
      "id": "gcp.kms-key",
      "title": "Vertex CMEK key exists with 30-day rotation",
      "type": "gcp_kms_key",
      "category": "GCP infrastructure",
      "severity": "critical",
      "tags": ["gcp", "kms"],
      "status": "pass",
      "message": "vertex-keyring/vertex-cmek in europe-west2, rotation 30.0 days",
      "detail": "",
      "hint": "",
      "duration_s": 0.42,
      "source": "30_gcp_infrastructure.yml"
    }
  ]
}
```

Values whose key looks like a secret are redacted as `***`.

A useful release practice: store the JSON as a build artifact and diff it
between releases. A package version, API state or IAM binding drifting shows
up as a line change even when the run is still green.

### JUnit XML

```bash
python run.py --junit reports/junit.xml
```

Each check becomes a test case; failures and warnings become `<failure>`,
skips become `<skipped>`. Most CI dashboards consume this without any custom
integration.

## Cloud Build example

```yaml
steps:
  - name: python:3.11
    entrypoint: bash
    args:
      - -c
      - |
        pip install -r test-pack/requirements.txt
        python test-pack/run.py \
          --project-id "$PROJECT_ID" \
          --region "$_REGION" \
          --strict \
          --json reports/result.json \
          --junit reports/junit.xml
    env:
      - GOOGLE_CLOUD_PROJECT=$PROJECT_ID

artifacts:
  objects:
    location: "gs://${PROJECT_ID}-build-artifacts/test-pack/"
    paths:
      - reports/result.json
      - reports/junit.xml
```

Notes:

* Run in a step that has Application Default Credentials. The Cloud Build
  service account needs read access to the resources being checked (and
  `roles/iam.securityReviewer` or equivalent if you check project IAM).
* Pass PSC values from Terraform outputs if PSC is part of the deployment.
* Keep `--strict` on the release branch; it is intentionally noisy about
  unverified critical requirements.

## GitHub Actions example

```yaml
jobs:
  readiness:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
          service_account: ${{ secrets.WIF_SERVICE_ACCOUNT }}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r test-pack/requirements.txt
      - run: |
          python test-pack/run.py \
            --project-id "${{ vars.GCP_PROJECT_ID }}" \
            --region "${{ vars.GCP_REGION }}" \
            --strict \
            --json reports/result.json \
            --junit reports/junit.xml
      - if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-pack-report
          path: reports/
```

## Release checklist

1. `terraform plan` / `terraform apply` succeeds.
2. `python run.py --strict` is green in the deployed workbench.
3. PSC checks are configured (or explicitly excluded) if the deployment uses
   PSC.
4. `reports/result.json` is archived with the release.
5. Any skipped critical checks are understood and documented.

If a check is flaky, fix it or mark it `severity: warning` with a reason. Do
not weaken `--strict`; that is the mechanism that keeps unverified
requirements visible.

Next: [Troubleshooting](troubleshooting.md).
