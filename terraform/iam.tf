# サービスアカウントの作成
resource "google_service_account" "receipt_scanner" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "Receipt Scanner Service Account"
  description  = "Service account for receipt-scanner to append data to Google Sheets"
}

# サービスアカウントキーの発行
resource "google_service_account_key" "receipt_scanner_key" {
  service_account_id = google_service_account.receipt_scanner.name
}

# Vertex AI ユーザーロールの付与 (Gemini 呼び出し権限)
resource "google_project_iam_member" "receipt_scanner_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.receipt_scanner.email}"
}

# 発行した秘密鍵JSONを credentials/service_account.json として保存
resource "local_file" "service_account_key" {
  content         = base64decode(google_service_account_key.receipt_scanner_key.private_key)
  filename        = "${path.module}/../credentials/service_account.json"
  file_permission = "0600"
}
