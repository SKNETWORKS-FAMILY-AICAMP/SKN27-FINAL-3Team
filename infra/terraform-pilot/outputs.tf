output "instance_id" {
  description = "SSM target instance ID."
  value       = aws_instance.app.id
}

output "aws_region" {
  description = "Region used by deployment and teardown scripts."
  value       = var.aws_region
}

output "public_ip" {
  description = "Elastic IP to map in public DNS."
  value       = aws_eip.app.public_ip
}

output "database_identifier" {
  description = "RDS identifier used by the deployment script to discover the RDS-managed credential."
  value       = aws_db_instance.postgres.identifier
}

output "database_master_credential_arn" {
  description = "ARN only. Only the temporary database maintenance profile can read the rotating RDS master value."
  value       = aws_db_instance.postgres.master_user_secret[0].secret_arn
}

output "database_address" {
  description = "Private RDS endpoint used as POSTGRES_HOST."
  value       = aws_db_instance.postgres.address
}

output "database_port" {
  value = aws_db_instance.postgres.port
}

output "database_name" {
  value = var.database_name
}

output "database_username" {
  value = var.database_username
}

output "database_app_username" {
  value = var.database_app_username
}

output "app_database_credential_arn" {
  description = "ARN only. Secret contents are created by Maintain-PilotDatabase.ps1 and never enter Terraform state."
  value       = aws_secretsmanager_secret.app_database.arn
}

output "database_runtime_instance_profile_name" {
  value = aws_iam_instance_profile.app.name
}

output "database_runtime_role_name" {
  value = aws_iam_role.app.name
}

output "database_maintenance_instance_profile_name" {
  value = aws_iam_instance_profile.database_maintenance.name
}

output "database_maintenance_role_name" {
  value = aws_iam_role.database_maintenance.name
}

output "clean_bucket_name" {
  value = aws_s3_bucket.clean.id
}

output "quarantine_bucket_name" {
  value = aws_s3_bucket.quarantine.id
}

output "backend_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "frontend_repository_url" {
  value = aws_ecr_repository.frontend.repository_url
}

output "runtime_env_parameter_name" {
  description = "Name only; the SecureString value is never managed or output by Terraform."
  value       = var.runtime_env_parameter_name
}

output "google_live_code_parameter_name" {
  description = "Name only; the one-time authorization code is never managed or output by Terraform."
  value       = var.google_live_code_parameter_name
}
