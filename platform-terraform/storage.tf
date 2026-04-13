# ---------------------------------------------------
# 4. Create GCS bucket for Vertex Pipelines
# ---------------------------------------------------
resource "google_storage_bucket" "vertex_bucket" {
  name          = "${var.project_id}-fucket"
  location      = var.region
  force_destroy = false

  uniform_bucket_level_access = true

  depends_on = [google_kms_crypto_key_iam_binding.vertex_sa_cmek]
}

resource "google_storage_bucket_iam_binding" "vertex_bucket_sa" {
  bucket = google_storage_bucket.vertex_bucket.name
  role   = "roles/storage.editor"

  members = [
    "serviceAccount:${local.vertex_service_agent}"
  ]

  depends_on = [google_storage_bucket.vertex_bucket]
}
