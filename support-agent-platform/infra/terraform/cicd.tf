# ─────────────────────────────────────────────────────────────────────────────
# CI/CD IAM — Cloud Build runs as the Compute Engine default service account on
# new projects. Grant it least-privilege roles to: read the uploaded source,
# push images to Artifact Registry, and write build logs.
# (Formalized into a dedicated CI service account in the later CI phase.)
# ─────────────────────────────────────────────────────────────────────────────

data "google_project" "current" {
  project_id = var.project_id
}

locals {
  cloudbuild_sa = "serviceAccount:${data.google_project.current.number}-compute@developer.gserviceaccount.com"
  cloudbuild_roles = [
    "roles/storage.objectViewer",    # read the source tarball in the staging bucket
    "roles/artifactregistry.writer", # push built images
    "roles/logging.logWriter",       # write build logs
  ]
}

resource "google_project_iam_member" "cloudbuild" {
  for_each = toset(local.cloudbuild_roles)
  project  = var.project_id
  role     = each.value
  member   = local.cloudbuild_sa

  depends_on = [module.project]
}
