# PSC networking for Vertex AI Pipelines

This page covers the **Private Service Connect interface (PSC-I)** path used
by Vertex AI Pipelines. It has two halves:

1. `platform-terraform/psc.tf` creates the subnet, network attachment and IAM
   binding.
2. `test-pack` validates that wiring and can submit a real pipeline run that
   uses it.

PSC-I is different from VPC peering. With peering you pass a `network` to the
pipeline job; with PSC-I you pass a `psc_interface_config.network_attachment`.
Do not set both on the same job.

## What gets created

```text
VPC network (existing)
  └── subnet: purpose = PRIVATE_SERVICE_CONNECT
        └── network attachment
              └── used by Vertex AI PipelineJob.pscInterfaceConfig
```

The Vertex AI service agent is granted `roles/compute.networkUser` on the
subnet. No public IPs are involved.

## Terraform

### Variables

| Variable | Default | Notes |
| -------- | ------- | ----- |
| `enable_psc` | `false` | Turns the resources on |
| `psc_network` | `""` | Existing VPC name or self-link; **required** when enabled |
| `psc_region` | `null` | Defaults to `var.region` |
| `psc_subnet_name` | `vertex-psc-subnet` | |
| `psc_subnet_cidr` | `10.10.0.0/24` | Pick a range outside your other subnets |
| `psc_network_attachment_name` | `vertex-psc-attachment` | |
| `psc_connection_preference` | `ACCEPT_AUTOMATIC` | `ACCEPT_AUTOMATIC` or `ACCEPT_MANUAL` |
| `psc_producer_accept_lists` | `[]` | Used only for `ACCEPT_MANUAL` |

Example `terraform.tfvars`:

```hcl
project_id  = "my-uat-123"
region      = "europe-west2"
enable_psc  = true
psc_network = "projects/my-uat-123/global/networks/my-vpc"
# Optional:
# psc_region            = "europe-west2"
# psc_subnet_cidr       = "10.10.0.0/24"
# psc_subnet_name       = "vertex-psc-subnet"
# psc_connection_preference = "ACCEPT_AUTOMATIC"
```

Apply:

```bash
cd platform-terraform
terraform init
terraform apply
```

The PSC resources are skipped entirely when `enable_psc = false`, so existing
deployments are unaffected.

### Outputs

```bash
terraform output -raw psc_network_attachment
# projects/my-uat-123/regions/europe-west2/networkAttachments/vertex-psc-attachment

terraform output -raw psc_subnet
# vertex-psc-subnet

terraform output -raw psc_region
# europe-west2
```

### IAM

`psc.tf` grants the Vertex AI service agent
(`service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com`)
`roles/compute.networkUser` on the PSC subnet. If your organization manages
IAM separately, remove that resource and grant the role yourself.

For DNS peering, the Vertex AI service agent also needs `roles/dns.peer` on
the project that hosts the target Cloud DNS zone. That binding is not created
by this Terraform because the target project is environment-specific.

## Test pack configuration

Feed the Terraform outputs into `config.yml`:

```yaml
values:
  psc_network_attachment: projects/my-uat-123/regions/europe-west2/networkAttachments/vertex-psc-attachment
  psc_subnet: vertex-psc-subnet
  psc_network: my-vpc
  psc_region: europe-west2
  psc_connection_preference: ACCEPT_AUTOMATIC
```

Or pass them without editing the file:

```bash
python run.py \
  --set psc_network_attachment="$PSC_ATTACHMENT" \
  --set psc_subnet=vertex-psc-subnet \
  --set psc_network=my-vpc
```

Values may be bare names, region-scoped names, full resource names or URLs.
The region is taken from the value when present, otherwise from
`psc_region`/`region`.

### What the checks assert

| Check | Asserts |
| ----- | ------- |
| `psc.subnet` | Subnet exists, is in the right region/network, has `purpose: PRIVATE_SERVICE_CONNECT` |
| `psc.network-attachment` | Attachment exists, points at the subnet, uses the expected connection preference |
| `psc.vertex-network-user` | Service agent has `roles/compute.networkUser` on the subnet |
| `psc.sdk` | Installed `google-cloud-aiplatform` exposes PSC on `PipelineJob` |

All four skip when their config values are empty. That means a
non-PSC deployment stays green, while a PSC deployment gets real assertions as
soon as the values are set.

```bash
python run.py --only psc
```

Use `--strict` in the release gate if PSC is mandatory: it turns the
"empty config" skips into failures, so a missing attachment cannot be
mistaken for a pass.

## Real pipeline run over PSC

The infrastructure checks prove configuration. Only a real run proves the
whole path. `integration.pipeline-psc` submits a pipeline job with
`psc_interface_config` and waits for it.

It is **disabled by default** because it creates a Vertex AI Pipeline run (and
possibly image pulls and compute).

### 1. Compile a tiny pipeline

```bash
python -m pip install kfp
cd test-pack
python examples/psc_pipeline.py          # writes psc_pipeline.json
gcloud storage cp psc_pipeline.json gs://my-bucket/test-pack/psc_pipeline.json
```

### 2. Configure

```yaml
values:
  pipeline_template: gs://my-bucket/test-pack/psc_pipeline.json
  pipeline_root: gs://my-bucket/pipeline-root
  psc_network_attachment: projects/my-uat-123/regions/europe-west2/networkAttachments/vertex-psc-attachment
  psc_region: europe-west2
  # pipeline_service_account: sa-pipelines@my-uat-123.iam.gserviceaccount.com
```

### 3. Enable the check

In `checks/60_integrations.yml`, set `enabled: true` on
`integration.pipeline-psc` and run:

```bash
python run.py --only integration.pipeline-psc --verbose
```

Options:

| Param | Default | Meaning |
| ----- | ------- | ------- |
| `wait` | `true` | Wait for the run to finish; `false` only proves submission |
| `timeout` | `1800` | Check-level timeout in seconds |
| `poll_seconds` | `15` | State poll interval |
| `cancel_on_timeout` | `true` | Cancel the run if the wait times out |
| `service_account` | unset | Run-as service account for the pipeline |
| `dns_peering` | `[]` | List of `{domain, target_project, target_network}` |

Example DNS peering:

```yaml
dns_peering:
  - domain: "internal.example.com."
    target_project: my-dns-project
    target_network: my-vpc
```

The plugin sets the proto field directly:

```python
job._gca_resource.psc_interface_config = PscInterfaceConfig(
    network_attachment="projects/.../networkAttachments/..."
)
```

The 2.x high-level SDK wrapper does not expose this argument yet. See
[Plugins](plugins.md#a-note-on-the-psc-pipeline-plugin).

## Requirements and caveats

* **Same region.** The network attachment and the pipeline job must be in the
  same region.
* **Existing VPC.** `psc_network` must be an existing network; this Terraform
  does not create one.
* **Subnet purpose.** PSC interfaces use a subnet with
  `purpose = PRIVATE_SERVICE_CONNECT`. Do not reuse a general-purpose subnet.
* **IAM.** The Vertex AI service agent needs `roles/compute.networkUser` on the
  subnet. Without it, job creation fails with a permission error.
* **Feature availability.** PSC-I availability can depend on project
  allowlisting and region. If the API rejects `pscInterfaceConfig`, confirm the
  feature is available for the project before changing the tests.
* **Image pulls.** The pipeline's container images must be reachable by Vertex.
  PSC-I provides the workload's VPC connectivity; it does not make an
  unreachable image registry reachable.
* **Cost.** The real run check creates a pipeline job and runs at least one
  task. Keep it out of the fast/default path.

## Troubleshooting

| Symptom | Likely cause |
| ------- | ------------ |
| `network attachment ... was not found` | Wrong name/region, or Terraform not applied |
| `PSC subnet exists` fails with purpose mismatch | Subnet was created as a normal subnet; create a dedicated one |
| `Vertex service agent can use the PSC subnet` fails | `roles/compute.networkUser` missing on the subnet |
| Pipeline submit: `PermissionDenied` | Service agent IAM, or the caller cannot act as the run-as account |
| Pipeline submit: `InvalidArgument` mentioning PSC | Feature not available/allowlisted, wrong attachment format, or attachment in another region |
| Pipeline runs but tasks cannot reach your VPC | Attachment/subnet mismatch, firewall rules, or DNS (use `dns_peering`) |
| SDK check fails | `google-cloud-aiplatform` too old; upgrade it |
