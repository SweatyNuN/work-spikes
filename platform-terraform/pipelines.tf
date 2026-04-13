# ---------------------------------------------------
# 5. IAM permissions for vertex
# ---------------------------------------------------
resource "google_project_iam_member" "alex_vertex_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"

  member = "user:alex.bastable@gmail.com"

  depends_on = [
    google_storage_bucket_iam_binding.vertex_bucket_sa
  ]
}

resource "google_service_account_iam_member" "allow_user_impersonation_compute_default" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
  role               = "roles/iam.serviceAccountUser"
  member             = "user:alex.bastable@gmail.com"

  depends_on = [ google_project_iam_member.alex_vertex_user ]
}
