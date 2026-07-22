variable "aws_region" {
  description = "AWS region for the pilot."
  type        = string
  default     = "ap-northeast-2"
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
      "t3a.large",
      "t3.large",
      "t3a.xlarge",
      "t3.xlarge",
    ], var.instance_type)
    error_message = "Use a validated x86 instance with at least 8 GiB: t3a.large, t3.large, t3a.xlarge, or t3.xlarge."
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
