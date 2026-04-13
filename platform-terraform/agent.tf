# ---------------------------------------------------
# 2. Force create aiplatform service agent
# ---------------------------------------------------

# Create all project-level aiplatform.googleapis.com service agents
resource "google_project_service_identity" "default" {
  provider = google-beta

  project = var.project_id
  service = "aiplatform.googleapis.com"

  depends_on = [ google_project_service.apis ]
}
