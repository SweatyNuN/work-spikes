variable "GOOGLE_CREDENTIALS" {
  type      = string
  sensitive = true
}

provider "google" {
  project = "work-spikes"
  region  = "europe-west2" # or whatever region you use
}
