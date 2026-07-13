output "cloudfront_domain" {
  value = aws_cloudfront_distribution.app.domain_name
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "app_bucket" {
  value = aws_s3_bucket.objects.id
}

output "quarantine_bucket" {
  value = aws_s3_bucket.quarantine.id
}

output "database_endpoint" {
  value     = aws_db_instance.main.address
  sensitive = true
}

