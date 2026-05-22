variable "config_file" {
  description = "Path to the JSON configuration that drives OSMH resources."
  type        = string
  default     = "config/osmh_config.json"
}

variable "region" {
  description = "OCI region to apply. Resources in the JSON are filtered by this region."
  type        = string
  default     = null
}

variable "tenancy_ocid" {
  description = "Optional tenancy OCID for OCI provider authentication and JSON config override."
  type        = string
  default     = null
}

variable "user_ocid" {
  description = "Optional OCI user OCID for API key authentication."
  type        = string
  default     = null
  sensitive   = true
}

variable "fingerprint" {
  description = "Optional OCI API key fingerprint."
  type        = string
  default     = null
  sensitive   = true
}

variable "private_key_path" {
  description = "Optional path to the OCI API private key."
  type        = string
  default     = null
  sensitive   = true
}

variable "private_key_password" {
  description = "Optional passphrase for the OCI API private key."
  type        = string
  default     = null
  sensitive   = true
}

variable "osmh_compartment_id" {
  description = "Optional override for the compartment where OSMH resources are created."
  type        = string
  default     = null
}

variable "enable_identity" {
  description = "Optional override for creating IAM dynamic group and policy."
  type        = bool
  default     = null
}

variable "enable_source_creation" {
  description = "Whether to create OSMH software sources from config. When false, existing software sources are looked up by the configured lookup/display name."
  type        = bool
  default     = null
}
