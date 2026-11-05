output "psc_network_attachment" {
  description = "Full resource name of the PSC network attachment, or null when PSC is disabled."
  value       = one(google_compute_network_attachment.vertex[*].id)
}

output "psc_subnet" {
  description = "Name of the PSC subnet, or null when PSC is disabled."
  value       = one(google_compute_subnetwork.psc[*].name)
}

output "psc_region" {
  description = "Region of the PSC resources, or null when PSC is disabled."
  value       = var.enable_psc ? local.psc_region : null
}
