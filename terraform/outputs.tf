output "service_account_email" {
  description = "Created service account email address (Share your Google Sheet with this email)"
  value       = google_service_account.receipt_scanner.email
}

output "service_account_key_path" {
  description = "Saved path of the service account key"
  value       = local_file.service_account_key.filename
}
