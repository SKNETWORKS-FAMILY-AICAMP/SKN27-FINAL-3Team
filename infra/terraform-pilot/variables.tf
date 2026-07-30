variable "aws_region" {
  description = "AWS region for the pilot."
  type        = string
  default     = "ap-northeast-2"
}

variable "ci_enabled" {
  description = "Create the source/build-only CodeBuild and CodePipeline resources."
  type        = bool
  default     = false
}

variable "github_connection_arn" {
  description = "Available CodeStar GitHub connection ARN used only when ci_enabled is true."
  type        = string
  default     = ""

  validation {
    condition     = !var.ci_enabled || can(regex("^arn:aws:codeconnections:", var.github_connection_arn)) || can(regex("^arn:aws:codestar-connections:", var.github_connection_arn))
    error_message = "ci_enabled requires an available GitHub connection ARN."
  }
}

variable "github_repository_full_name" {
  description = "GitHub owner/repository used by the source/build-only pipeline."
  type        = string
  default     = "SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team"
}

variable "github_dev_branch" {
  description = "Git branch that triggers the source/build-only pipeline."
  type        = string
  default     = "dev"
}

variable "frontend_google_client_id" {
  description = "Public Google OAuth client ID compiled into the frontend image; not a secret."
  type        = string
  default     = ""
}

variable "ci_log_retention_days" {
  description = "CloudWatch retention for CodeBuild logs."
  type        = number
  default     = 30
}

variable "project_name" {
  description = "Lowercase name prefix used for pilot resources."
  type        = string
  default     = "skn27-pilot"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,24}$", var.project_name))
    error_message = "project_name must contain 3-24 lowercase letters, digits, or hyphens."
  }
}

variable "instance_type" {
  description = "Single x86 EC2 instance type. ClamAV acceptance requires at least 8 GiB."
  type        = string
  default     = "t3a.large"

  validation {
    condition = contains([
      "m7i-flex.large",
      "t3a.large",
      "t3.large",
      "t3a.xlarge",
      "t3.xlarge",
    ], var.instance_type)
    error_message = "Use a validated x86 instance with at least 8 GiB: m7i-flex.large, t3a.large, t3.large, t3a.xlarge, or t3.xlarge."
  }
}

variable "root_volume_size_gib" {
  description = "Encrypted gp3 root volume size for images and ClamAV data."
  type        = number
  default     = 40
}

variable "docker_compose_version" {
  description = "Pinned Docker Compose plugin version installed by EC2 user data."
  type        = string
  default     = "v2.35.1"
}

variable "http_ingress_cidrs" {
  description = "Public client CIDRs allowed to reach Caddy on ports 80 and 443."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "database_name" {
  description = "PostgreSQL database name."
  type        = string
  default     = "law_db"
}

variable "database_username" {
  description = "RDS master username. The password is generated and rotated by RDS."
  type        = string
  default     = "skn27_admin"
}

variable "database_app_username" {
  description = "Least-privilege login used by the running application."
  type        = string
  default     = "skn27_app"

  validation {
    condition     = can(regex("^[a-z_][a-z0-9_]{2,30}$", var.database_app_username))
    error_message = "database_app_username must be a safe PostgreSQL identifier."
  }
}

variable "database_instance_class" {
  description = "Single-AZ pilot RDS size."
  type        = string
  default     = "db.t4g.micro"
}

variable "database_allocated_storage_gib" {
  description = "Initial encrypted gp3 RDS storage."
  type        = number
  default     = 20
}

variable "database_max_allocated_storage_gib" {
  description = "RDS autoscaling ceiling used as a cost guardrail."
  type        = number
  default     = 50
}

variable "database_backup_retention_days" {
  description = "RDS automated backup retention. AWS Free plan accounts require 1 day."
  type        = number
  default     = 7

  validation {
    condition     = var.database_backup_retention_days >= 1 && var.database_backup_retention_days <= 35
    error_message = "database_backup_retention_days must be between 1 and 35."
  }
}

variable "database_deletion_protection" {
  description = "Protect the database from accidental deletion. Set false only during an approved teardown."
  type        = bool
  default     = true
}

variable "database_skip_final_snapshot" {
  description = "Skip the final RDS snapshot. Keep false except for disposable test environments."
  type        = bool
  default     = false
}

variable "budget_limit_usd" {
  description = "Monthly AWS cost budget in USD."
  type        = number
  default     = 50

  validation {
    condition     = var.budget_limit_usd > 0
    error_message = "budget_limit_usd must be greater than zero."
  }
}

variable "budget_alert_email" {
  description = "Email that receives 50%, 80%, and 100% actual-spend alerts."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_alert_email))
    error_message = "budget_alert_email must be a valid email address."
  }
}

variable "runtime_env_parameter_name" {
  description = "SSM Standard SecureString name containing the complete Docker runtime env file."
  type        = string
  default     = "/skn27/pilot/runtime-env"

  validation {
    condition     = startswith(var.runtime_env_parameter_name, "/")
    error_message = "runtime_env_parameter_name must be an absolute SSM parameter path."
  }
}

variable "google_live_code_parameter_name" {
  description = "Short-lived SecureString used only by the optional #192 live Google exchange smoke."
  type        = string
  default     = "/skn27/pilot/live-smoke/google-authorization-code"

  validation {
    condition     = startswith(var.google_live_code_parameter_name, "/")
    error_message = "google_live_code_parameter_name must be an absolute SSM parameter path."
  }
}

variable "clean_object_expiration_days" {
  description = "Expiration for generated clean artifacts in the pilot bucket."
  type        = number
  default     = 90
}

variable "quarantine_expiration_days" {
  description = "Expiration for untrusted uploads in quarantine."
  type        = number
  default     = 7
}

variable "extra_tags" {
  description = "Additional non-secret resource tags."
  type        = map(string)
  default     = {}
}

variable "operational_alert_email" {
  description = "Optional email subscription for operational alarms. Confirmation is required."
  type        = string
  default     = ""

  validation {
    condition = (
      var.operational_alert_email == "" ||
      can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.operational_alert_email))
    )
    error_message = "operational_alert_email must be empty or a valid email address."
  }
}

variable "operational_log_retention_days" {
  description = "CloudWatch retention for privacy-safe operational health snapshots."
  type        = number
  default     = 30

  validation {
    condition     = contains([7, 14, 30, 60, 90], var.operational_log_retention_days)
    error_message = "operational_log_retention_days must be 7, 14, 30, 60, or 90."
  }
}

variable "operational_queue_age_threshold_seconds" {
  description = "Provisional oldest queued item alarm threshold; calibrate after load testing."
  type        = number
  default     = 300

  validation {
    condition     = var.operational_queue_age_threshold_seconds >= 60
    error_message = "operational_queue_age_threshold_seconds must be at least 60."
  }
}

variable "operational_stale_running_threshold_count" {
  description = "Provisional stale running item alarm threshold."
  type        = number
  default     = 0

  validation {
    condition     = var.operational_stale_running_threshold_count >= 0
    error_message = "operational_stale_running_threshold_count must not be negative."
  }
}

variable "operational_worker_failure_threshold_count" {
  description = "Provisional recent Worker failure alarm threshold."
  type        = number
  default     = 0

  validation {
    condition     = var.operational_worker_failure_threshold_count >= 0
    error_message = "operational_worker_failure_threshold_count must not be negative."
  }
}

variable "operational_provider_failure_threshold_count" {
  description = "Provisional recent provider failure alarm threshold."
  type        = number
  default     = 0

  validation {
    condition     = var.operational_provider_failure_threshold_count >= 0
    error_message = "operational_provider_failure_threshold_count must not be negative."
  }
}

variable "operational_legal_failure_threshold_count" {
  description = "Provisional legal freshness issue alarm threshold."
  type        = number
  default     = 0

  validation {
    condition     = var.operational_legal_failure_threshold_count >= 0
    error_message = "operational_legal_failure_threshold_count must not be negative."
  }
}

variable "operational_heartbeat_missing_periods" {
  description = "Number of missing one-minute monitor periods before alarm."
  type        = number
  default     = 3

  validation {
    condition     = var.operational_heartbeat_missing_periods >= 2
    error_message = "operational_heartbeat_missing_periods must be at least 2."
  }
}

variable "vision_worker_enabled" {
  description = "Create the private GPU Vision worker only after image, AMI, and budget approval."
  type        = bool
  default     = false

  validation {
    condition     = !var.vision_worker_enabled || var.vision_registry_enabled
    error_message = "vision_worker_enabled requires vision_registry_enabled."
  }
}

variable "vision_registry_enabled" {
  description = "Create only the immutable Vision ECR repository; it never creates GPU execution resources."
  type        = bool
  default     = false
}

variable "vision_worker_instance_type" {
  description = "GPU instance type reserved for the private Vision worker."
  type        = string
  default     = "g5.xlarge"

  validation {
    condition     = contains(["g5.xlarge"], var.vision_worker_instance_type)
    error_message = "vision_worker_instance_type must be the approved 24 GiB g5.xlarge pilot size."
  }
}

variable "vision_worker_ami_id" {
  description = "Private GPU-ready AMI containing Docker, NVIDIA drivers, and the approved model volume."
  type        = string
  default     = ""

  validation {
    condition = (
      !var.vision_worker_enabled ||
      can(regex("^ami-[0-9a-f]{8,17}$", var.vision_worker_ami_id))
    )
    error_message = "vision_worker_ami_id must be an explicit GPU-ready AMI ID when Vision is enabled."
  }
}

variable "vision_worker_image_tag" {
  description = "Immutable Vision worker image tag already pushed to the dedicated ECR repository."
  type        = string
  default     = ""

  validation {
    condition = (
      !var.vision_worker_enabled ||
      can(regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", var.vision_worker_image_tag))
    )
    error_message = "vision_worker_image_tag must be an immutable ECR tag when Vision is enabled."
  }
}

variable "vision_worker_model_volume_prepared" {
  description = "Explicit acknowledgement that the AMI or attached volume contains the approved Vision models."
  type        = bool
  default     = false

  validation {
    condition     = !var.vision_worker_enabled || var.vision_worker_model_volume_prepared
    error_message = "vision_worker_model_volume_prepared must be true before enabling the GPU worker."
  }
}

variable "vision_worker_allowed_hosts" {
  description = "Comma-separated approved S3 hosts allowed for signed Vision video downloads."
  type        = string
  default     = ""

  validation {
    condition     = !var.vision_worker_enabled || trimspace(var.vision_worker_allowed_hosts) != ""
    error_message = "vision_worker_allowed_hosts must be set before enabling the GPU worker."
  }
}

variable "vision_worker_checkpoint_path" {
  description = "Existing absolute VideoMAE checkpoint path on the prepared private GPU host."
  type        = string
  default     = "/vision-volume/models/videomae"
}

variable "vision_worker_qwen_model_id" {
  description = "Pinned Vision Qwen model identifier available from the prepared local cache."
  type        = string
  default     = "Qwen/Qwen3-VL-4B-Instruct"
}

variable "vision_worker_idle_minutes" {
  description = "Scheduled idle check interval. A worker stops only when no SQS message is visible or in flight."
  type        = number
  default     = 15

  validation {
    condition     = contains([5, 10, 15, 30], var.vision_worker_idle_minutes)
    error_message = "vision_worker_idle_minutes must be 5, 10, 15, or 30."
  }
}
