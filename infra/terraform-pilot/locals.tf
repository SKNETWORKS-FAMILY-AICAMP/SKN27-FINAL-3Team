data "aws_caller_identity" "current" {}

locals {
  name_prefix = var.project_name
  tags = merge(
    {
      Project     = "SKN27-FINAL-3Team"
      Environment = "pilot"
      CostProfile = "low-cost-single-ec2"
      ManagedBy   = "terraform"
    },
    var.extra_tags,
  )
}
