# ---------------------------------------------------
# 6. Private Service Connect for Vertex AI Pipelines
# ---------------------------------------------------
#
# Optional, off by default. When enable_psc = true, this creates:
#   * a subnet dedicated to PSC interfaces
#   * a network attachment that Vertex AI pipeline jobs can reference
#   * the IAM binding that lets the Vertex service agent use the subnet
#
# Pipeline jobs then pass the attachment in pscInterfaceConfig:
#   projects/PROJECT/regions/REGION/networkAttachments/NAME
#
# The VPC must already exist. Pass it via psc_network (name or self-link).

locals {
  psc_region = coalesce(var.psc_region, var.region)
}

resource "google_compute_subnetwork" "psc" {
  count = var.enable_psc ? 1 : 0

  name          = var.psc_subnet_name
  project       = var.project_id
  region        = local.psc_region
  network       = var.psc_network
  ip_cidr_range = var.psc_subnet_cidr
  purpose       = "PRIVATE_SERVICE_CONNECT"

  depends_on = [google_project_service.apis]

  lifecycle {
    precondition {
      condition     = length(var.psc_network) > 0
      error_message = "psc_network must be set to an existing VPC when enable_psc = true."
    }
  }
}

resource "google_compute_network_attachment" "vertex" {
  count = var.enable_psc ? 1 : 0

  name                  = var.psc_network_attachment_name
  project               = var.project_id
  region                = local.psc_region
  subnetworks           = [google_compute_subnetwork.psc[0].self_link]
  connection_preference = var.psc_connection_preference
  producer_accept_lists = (
    var.psc_connection_preference == "ACCEPT_MANUAL" ? var.psc_producer_accept_lists : null
  )

  depends_on = [google_compute_subnetwork.psc]
}

# The Vertex AI service agent needs to use the subnet for PSC interfaces.
resource "google_compute_subnetwork_iam_member" "vertex_psc_network_user" {
  count = var.enable_psc ? 1 : 0

  project    = var.project_id
  region     = local.psc_region
  subnetwork = google_compute_subnetwork.psc[0].name
  role       = "roles/compute.networkUser"
  member     = "serviceAccount:${local.vertex_service_agent}"

  depends_on = [google_project_service_identity.default]
}
