# Vision ECR and CodeBuild Separation Design

## Goal

Build and publish the private Vision worker image without creating a GPU worker,
then require an explicit later approval to create the GPU queue, controller, and
EC2 host.

## Design

- Reintroduce the unmerged CodeBuild and source-only CodePipeline foundation on
  the latest dev branch. Both remain disabled by default through ci_enabled.
- Split the Vision ECR repository from runtime infrastructure with
  vision_registry_enabled=false. Enabling it creates only the immutable ECR
  repository and lifecycle policy; it does not create SQS, Lambda, VPC endpoints,
  or a GPU instance.
- Keep vision_worker_enabled=false as the execution switch. Validation requires
  the registry to be enabled before the worker can be enabled.
- Extend the buildspec to run the existing contract tests, build backend and
  frontend as before, and build/push the Vision image only when
  VISION_REPOSITORY_URI is present. Every image uses the commit-derived tag;
  no mutable latest tag is pushed.

## Safety and rollout

1. Merge this branch with both flags still false: no AWS resource or billing
   change.
2. After a CodeStar connection is approved, enable ci_enabled and
   vision_registry_enabled only. This creates CI and the repository but no GPU.
3. Let CodeBuild publish the immutable Vision image.
4. In a separately approved change, supply a prepared GPU AMI, model volume,
   image tag, and set vision_worker_enabled=true.

## Verification

- Contract tests prove the buildspec conditionally builds the Vision image and
  Terraform keeps the registry and GPU worker independently gated.
- Terraform validate proves the disabled default configuration is valid.
- No Terraform apply, CodeBuild execution, ECR push, or GPU launch is part of
  this change.
