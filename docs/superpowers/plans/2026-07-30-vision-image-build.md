# Vision ECR and CodeBuild Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox ( - [ ] ) syntax for tracking.

**Goal:** Add a disabled-by-default CodeBuild build path for the Vision image and
separate the ECR registry from GPU worker creation.

**Architecture:** A source-only CodePipeline invokes privileged CodeBuild. The
buildspec always builds backend and frontend, and conditionally builds Vision when
Terraform supplies an ECR repository URI. Terraform has independent CI, registry,
and GPU worker switches.

**Tech Stack:** Terraform, AWS CodeBuild/CodePipeline/ECR, Docker, pytest.

## Global Constraints

- No Terraform apply, ECR push, CodeBuild execution, or GPU launch.
- ci_enabled, vision_registry_enabled, and vision_worker_enabled default to
  false.
- Images use a commit-derived immutable tag and never latest.

### Task 1: Reintroduce CI foundation on current dev

**Files:**
- Create: buildspec.pilot.yml, infra/terraform-pilot/codebuild.tf,
  infra/terraform-pilot/codepipeline.tf
- Modify: infra/terraform-pilot/variables.tf, outputs.tf
- Test: test/test_codebuild_pilot_contract.py

- [ ] Write a failing contract test requiring a disabled CI switch and
  CodeBuild/CodePipeline source-to-build path.
- [ ] Run the focused pytest command and verify the missing buildspec fails.
- [ ] Add the source-only pipeline and privileged CodeBuild project with
  least-privilege ECR push permissions.
- [ ] Re-run the focused test.

### Task 2: Split Vision registry and build it conditionally

**Files:**
- Modify: infra/terraform-pilot/vision_worker.tf,
  infra/terraform-pilot/variables.tf, buildspec.pilot.yml
- Test: test/test_codebuild_pilot_contract.py,
  test/test_aws_vision_worker_infrastructure.py

- [ ] Write failing tests requiring vision_registry_enabled=false, worker
  dependency validation, and conditional Vision image build/push.
- [ ] Run focused tests and verify they fail.
- [ ] Gate only the ECR repository/lifecycle policy with the registry flag; keep
  queue, endpoints, Lambda, and GPU host on the worker flag.
- [ ] Build/push deploy/aws-vision/Dockerfile only when the repository URI is
  non-empty.
- [ ] Re-run focused tests.

### Task 3: Verify disabled defaults

- [ ] Run Terraform fmt check.
- [ ] Run Terraform validate.
- [ ] Run the focused CI, Vision, and Pilot infrastructure tests.
- [ ] Run git diff check.
