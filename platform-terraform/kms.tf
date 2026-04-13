# ---------------------------------------------------
# 3. Create CMEK (KMS Key)
# ---------------------------------------------------

resource "google_kms_key_ring" "vertex" {
  name     = "vertex-keyring"
  location = var.region
  project  = var.project_id

  depends_on = [google_project_service_identity.default]
}

resource "google_kms_crypto_key" "vertex" {
  name            = "vertex-cmek"
  key_ring        = google_kms_key_ring.vertex.id
  rotation_period = "2592000s" # 30 days

  depends_on = [google_kms_key_ring.vertex]
}

resource "google_kms_crypto_key_iam_binding" "vertex_sa_cmek" {
  crypto_key_id = google_kms_crypto_key.vertex.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"

  members = [
    "serviceAccount:${local.vertex_service_agent}"
  ]

  depends_on = [google_kms_crypto_key.vertex]
}
