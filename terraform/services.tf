# 必要な Google API の有効化
resource "google_project_service" "sheets" {
  project                    = var.project_id
  service                    = "sheets.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "drive" {
  project                    = var.project_id
  service                    = "drive.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "generativelanguage" {
  project                    = var.project_id
  service                    = "generativelanguage.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}
