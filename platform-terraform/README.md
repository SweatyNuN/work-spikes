# platform-terraform

Provisions the core platform resources for a Vertex AI Workbench deployment:
required APIs, the Vertex service agent, CMEK/KMS, the pipeline bucket and IAM.

## Private Service Connect for Vertex AI Pipelines

PSC support is optional and off by default. Set `enable_psc = true` and point
`psc_network` at an existing VPC to create a `PRIVATE_SERVICE_CONNECT` subnet,
a network attachment and the Vertex service-agent IAM binding.

```hcl
enable_psc  = true
psc_network = "projects/my-project/global/networks/my-vpc"
```

The outputs `psc_network_attachment`, `psc_subnet` and `psc_region` feed the
PSC checks in [`../test-pack`](../test-pack). See
[test-pack/docs/psc-networking.md](../test-pack/docs/psc-networking.md) for the
full walkthrough, including a real pipeline-run test.

## Environment-specific values

`workbench_user_email` controls which human receives `roles/aiplatform.user`
and act-as access on the compute service account. It defaults to the original
developer account for backwards compatibility; set it per deployment.

```hcl
workbench_user_email = "data-science@example.com"
```

## Credentials

The Google provider reads `GOOGLE_CREDENTIALS` directly from the environment.
For local use, Application Default Credentials are simplest:

```bash
gcloud auth application-default login
```

Or export a service account key inline:

```bash
export GOOGLE_CREDENTIALS="$(cat key.json | jq -c)"
```

In CI, prefer Workload Identity Federation over long-lived keys.
