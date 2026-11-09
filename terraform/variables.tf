variable "project_id" {
  description = "Google Cloud Project ID"
  type        = string
  default     = "apps-466614"
}

variable "region" {
  description = "Default Google Cloud region"
  type        = string
  default     = "asia-northeast1"
}

variable "service_account_id" {
  description = "Service Account ID"
  type        = string
  default     = "receipt-scanner"
}
