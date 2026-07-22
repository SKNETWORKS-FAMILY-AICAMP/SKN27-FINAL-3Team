variable "aws_region" {
  description = "AWS region for regional resources."
  type        = string
  default     = "ap-northeast-2"
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "staging"

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production"
  }
}

variable "domain_name" {
  description = "Single public hostname served by CloudFront."
  type        = string
}

variable "hosted_zone_id" {
  description = "Route53 hosted zone id for domain_name."
  type        = string
}

variable "cloudfront_certificate_arn" {
  description = "ACM certificate ARN in us-east-1 for CloudFront."
  type        = string
}

variable "alb_certificate_arn" {
  description = "ACM certificate ARN in aws_region for the private CloudFront origin hostname."
  type        = string
}

variable "api_origin_domain_name" {
  description = "Regional API origin hostname covered by alb_certificate_arn."
  type        = string
}

variable "alert_email" {
  description = "Operations email subscribed to the alarm topic."
  type        = string
}

variable "app_image" {
  description = "Immutable ECR image URI used by API and workers."
  type        = string
}

variable "app_secret_arn" {
  description = "Secrets Manager JSON secret containing Django, JWT, Google and OpenAI values."
  type        = string
}

variable "github_repository" {
  description = "GitHub Actions OIDC subject repository in owner/name form."
  type        = string
}
