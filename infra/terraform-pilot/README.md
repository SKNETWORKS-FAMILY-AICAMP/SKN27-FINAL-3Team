# Low-cost AWS pilot Terraform

This directory is intentionally independent from `infra/terraform`. It creates
one public x86 EC2 host, one private Single-AZ PostgreSQL RDS instance, two
private S3 buckets, two ECR repositories, and an AWS Budget. It does not create
NAT Gateway, ALB, ECS/Fargate, ElastiCache, CloudFront,
Kibana, or Neo4j.

Terraform creates infrastructure only. It does not store the application env
value. `deploy/aws-pilot/Deploy-Pilot.ps1` writes that value to the named SSM
Standard SecureString after infrastructure has been reviewed and applied.
Terraform 1.11 or newer is required for the native S3 `use_lockfile` backend.

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
Copy-Item backend.hcl.example backend.hcl
# Edit the email; never put credentials in terraform.tfvars.
terraform init -backend-config=backend.hcl
terraform fmt -check
terraform validate
terraform plan -out pilot.tfplan
# Review the plan, then apply it explicitly in a separate approval step.
terraform apply pilot.tfplan
```

Create the encrypted, versioned state bucket outside this stack with
`Initialize-StateBackend.ps1`; this avoids a state-bucket lifecycle cycle. The
RDS-managed master credential is available only to the temporary maintenance
profile. `Maintain-PilotDatabase.ps1` creates the separate least-privilege app
credential without putting either secret value in Terraform state or output.
