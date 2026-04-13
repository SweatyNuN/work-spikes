# ---------------------------------------------------
# 1. Enable API's
# ---------------------------------------------------

locals {
  vertex_required_apis = [
    # Core
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "compute.googleapis.com",
    "storage.googleapis.com",
    "cloudkms.googleapis.com",

    # Vertex AI
    "aiplatform.googleapis.com",

    # Workbench / Notebooks
    "notebooks.googleapis.com",

    # Pipelines / Training / Deployment
    "artifactregistry.googleapis.com",
    "containerregistry.googleapis.com",
    #"cloudbuild.googleapis.com",
    #"run.googleapis.com",
    #"eventarc.googleapis.com",

    # Data access
    "bigquery.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.vertex_required_apis)
  project            = var.project_id
  service            = each.key

  # Prevent yourself from disabling api's by accident and breaking the terraform
  disable_on_destroy = false
}
