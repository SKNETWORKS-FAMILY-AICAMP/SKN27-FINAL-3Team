# AWS production infrastructure

Terraform provisions the approved two-AZ ECS, RDS PostgreSQL/pgvector, Redis,
S3, CloudFront, WAF and operations baseline for staging or
production. Configure the remote state backend separately so credentials and
account-specific bucket names never enter source control.

```powershell
terraform -chdir=infra/terraform init -backend-config=backend-staging.hcl
terraform -chdir=infra/terraform plan -var-file=staging.tfvars
```

The JSON secret referenced by `app_secret_arn` must contain
`DJANGO_SECRET_KEY`, `APP_JWT_SECRET`, `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, and `SUPERVISOR_LLM_API_KEY`. ECS receives these values
through Secrets Manager; do not place them in `tfvars` or Terraform state.

