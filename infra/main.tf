// GCP deployment for the tracker (README §3): Cloud Run for the API and worker,
// Cloud SQL for Postgres, Memorystore for Redis, GCS for documents.
//
// This is the deployment skeleton, not a turnkey apply: it has never been run against a
// real project, image tags are variables, and the Pub/Sub topic that v2's Gmail watch
// needs is deliberately absent until Phase 5. Review before applying.
//
//   terraform init && terraform apply -var project_id=… -var image_tag=…

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.30"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" { type = string }
variable "region" { type = string, default = "us-central1" }
variable "image_tag" { type = string, default = "latest" }
variable "db_tier" { type = string, default = "db-f1-micro" }

locals {
  repo      = "${var.region}-docker.pkg.dev/${var.project_id}/job-tracker"
  api_image = "${local.repo}/api:${var.image_tag}"
  worker_image = "${local.repo}/worker:${var.image_tag}"
}

// ── container registry ────────────────────────────────────────────────────
resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = "job-tracker"
  format        = "DOCKER"
}

// ── database ──────────────────────────────────────────────────────────────
resource "google_sql_database_instance" "postgres" {
  name             = "job-tracker-pg"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier              = var.db_tier
    availability_type = "ZONAL"
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
    }
  }

  deletion_protection = true
}

resource "google_sql_database" "app" {
  name     = "job_tracker"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "app" {
  name     = "jobtracker"
  instance = google_sql_database_instance.postgres.name
  password = google_secret_manager_secret_version.db_password.secret_data
}

// ── network + redis ───────────────────────────────────────────────────────
resource "google_compute_network" "vpc" {
  name                    = "job-tracker"
  auto_create_subnetworks = true
}

resource "google_vpc_access_connector" "serverless" {
  name          = "job-tracker-vpc"
  region        = var.region
  network       = google_compute_network.vpc.name
  ip_cidr_range = "10.8.0.0/28"
}

resource "google_redis_instance" "queue" {
  name               = "job-tracker-redis"
  tier               = "BASIC"
  memory_size_gb     = 1
  region             = var.region
  authorized_network = google_compute_network.vpc.id
}

// ── secrets ───────────────────────────────────────────────────────────────
resource "google_secret_manager_secret" "jwt_secret" {
  secret_id = "job-tracker-jwt-secret"
  replication { auto {} }
}

resource "google_secret_manager_secret" "db_password" {
  secret_id = "job-tracker-db-password"
  replication { auto {} }
}

// Values are set out of band (`gcloud secrets versions add`) so they never enter state.
data "google_secret_manager_secret_version" "jwt_secret" {
  secret = google_secret_manager_secret.jwt_secret.id
}

data "google_secret_manager_secret_version" "db_password" {
  secret = google_secret_manager_secret.db_password.id
}

// ── documents (resume / cover-letter versions) ────────────────────────────
resource "google_storage_bucket" "documents" {
  name                        = "${var.project_id}-job-tracker-docs"
  location                    = var.region
  uniform_bucket_level_access = true
  versioning { enabled = true }
}

// ── services ──────────────────────────────────────────────────────────────
locals {
  database_url = join("", [
    "postgresql+psycopg://jobtracker:",
    data.google_secret_manager_secret_version.db_password.secret_data,
    "@/job_tracker?host=/cloudsql/",
    google_sql_database_instance.postgres.connection_name,
  ])
  redis_url = "redis://${google_redis_instance.queue.host}:${google_redis_instance.queue.port}/0"
}

resource "google_cloud_run_v2_service" "api" {
  name     = "job-tracker-api"
  location = var.region

  template {
    // Scales to zero; the SSE hub is per-process, which is why sessions are
    // stateless and events fan out through Redis in this configuration.
    scaling {
      min_instance_count = 0
      max_instance_count = 4
    }

    vpc_access {
      connector = google_vpc_access_connector.serverless.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance { instances = [google_sql_database_instance.postgres.connection_name] }
    }

    containers {
      image = local.api_image

      env {
        name  = "DATABASE_URL"
        value = local.database_url
      }
      env {
        name  = "REDIS_URL"
        value = local.redis_url
      }
      env {
        name  = "JWT_SECRET"
        value = data.google_secret_manager_secret_version.jwt_secret.secret_data
      }
      env {
        name  = "ENVIRONMENT"
        value = "production"
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      resources {
        limits = { cpu = "1", memory = "1Gi" }
      }

      startup_probe {
        http_get { path = "/healthz" }
        initial_delay_seconds = 5
        failure_threshold     = 10
      }
    }
  }
}

resource "google_cloud_run_v2_service" "worker" {
  name     = "job-tracker-worker"
  location = var.region

  template {
    // The worker pulls from Redis rather than serving traffic, so it stays warm.
    scaling {
      min_instance_count = 1
      max_instance_count = 2
    }

    vpc_access {
      connector = google_vpc_access_connector.serverless.id
      egress    = "ALL_TRAFFIC" // it fetches job postings from the open internet
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance { instances = [google_sql_database_instance.postgres.connection_name] }
    }

    containers {
      image = local.worker_image

      env {
        name  = "DATABASE_URL"
        value = local.database_url
      }
      env {
        name  = "REDIS_URL"
        value = local.redis_url
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      resources {
        limits = { cpu = "1", memory = "2Gi" } // headroom for the Playwright tier
      }
    }
  }
}

output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}
