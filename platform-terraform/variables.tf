variable "project_id" {
  type    = string
  default = "work-spikes-492917"
}

variable "project_number" {
  type    = string
  default = "754536297652"
}

variable "region" {
  type    = string
  default = "europe-west2"
}

variable "workbench_user_email" {
  description = "Human user who receives workbench IAM access."
  type        = string
  default     = "alex.bastable@gmail.com"
}

# ---------------------------------------------------
# Private Service Connect (optional)
# ---------------------------------------------------

variable "enable_psc" {
  description = "Create a PSC subnet and network attachment for Vertex AI Pipelines."
  type        = bool
  default     = false
}

variable "psc_network" {
  description = "Existing VPC network name or self-link. Required when enable_psc = true."
  type        = string
  default     = ""
}

variable "psc_region" {
  description = "Region for the PSC resources. Defaults to var.region."
  type        = string
  default     = null
}

variable "psc_subnet_name" {
  description = "Name of the subnet dedicated to PSC interfaces."
  type        = string
  default     = "vertex-psc-subnet"
}

variable "psc_subnet_cidr" {
  description = "CIDR range for the PSC subnet."
  type        = string
  default     = "10.10.0.0/24"
}

variable "psc_network_attachment_name" {
  description = "Name of the PSC network attachment."
  type        = string
  default     = "vertex-psc-attachment"
}

variable "psc_connection_preference" {
  description = "ACCEPT_AUTOMATIC or ACCEPT_MANUAL."
  type        = string
  default     = "ACCEPT_AUTOMATIC"

  validation {
    condition     = contains(["ACCEPT_AUTOMATIC", "ACCEPT_MANUAL"], var.psc_connection_preference)
    error_message = "psc_connection_preference must be ACCEPT_AUTOMATIC or ACCEPT_MANUAL."
  }
}

variable "psc_producer_accept_lists" {
  description = "Producer projects accepted when psc_connection_preference is ACCEPT_MANUAL."
  type        = list(string)
  default     = []
}
