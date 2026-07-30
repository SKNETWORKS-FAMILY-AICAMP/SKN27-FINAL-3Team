# Pilot CodePipeline EC2 App Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Add an opt-in, manually approved CodePipeline deployment that rolls out only the immutable backend and frontend images for a dev commit to the Pilot EC2 instance.

**Architecture:** Keep the current source/build pipeline intact. When explicitly enabled, append a CodePipeline manual-approval stage and a dedicated release CodeBuild project. The release project derives the same 12-character Git tag as the build, sends a scoped SSM command to the configured instance, checks for pending migrations, restarts only backend and frontend, and restores the prior tag when health checks fail.

**Tech Stack:** Terraform AWS provider, AWS CodePipeline, CodeBuild, IAM, SSM Run Command, Bash, Docker Compose, pytest contract tests.

## Global Constraints

- pilot_app_release_enabled defaults to false; merging code must not add a deploy stage until a reviewed Terraform apply enables it.
- Deploy only backend and frontend; do not restart Caddy, Redis, ClamAV, Neo4j, workers, or Vision.
- Do not execute migrate, RAG/graph seed commands, Google OAuth smoke, or paid provider smoke. migrate --check is required and read-only.
- Deploy CodeBuild receives no runtime environment value, application secret, or database credential; it may read only the private pipeline source artifact needed for its CodePipeline input.
- The release uses the exact twelve-character lowercase commit tag; never use latest.
- Health-check failure restores the previous RELEASE_TAG and recreates only backend and frontend before returning a failed SSM command.
- Compose/Caddy/schema/data changes continue to use deploy/aws-pilot/Deploy-Pilot.ps1.

---

## File structure

- Modify: infra/terraform-pilot/variables.tf — explicit opt-in flag and validation.
- Modify: infra/terraform-pilot/codebuild.tf — release CodeBuild log group, role, least-privilege policy, and project.
- Modify: infra/terraform-pilot/codepipeline.tf — manual approval and deploy stages, plus CodePipeline permission for the release project.
- Create: buildspec.pilot-app-release.yml — invokes only the release runner from the Source artifact.
- Create: deploy/aws-pilot/Release-PilotApp-FromPipeline.sh — derives the immutable tag, submits/polls one SSM command, and returns its terminal status.
- Modify: deploy/aws-pilot/README.ko.md — operator instructions, exclusions, approval/rollback evidence locations.
- Modify: test/test_codebuild_pilot_contract.py — pipeline and runner contract coverage.
- Modify: test/test_aws_pilot_infrastructure.py — least-privilege IAM and app-only release invariants.

## Task 1: Add the opt-in deployment flag contract

**Files:**
- Modify: infra/terraform-pilot/variables.tf
- Modify: test/test_codebuild_pilot_contract.py

**Interfaces:**
- Produces: var.pilot_app_release_enabled, a boolean defaulting to false.
- Consumes: existing var.ci_enabled; later resources must use var.ci_enabled && var.pilot_app_release_enabled as their count condition.

- [ ] **Step 1: Write the failing contract test**

~~~python
def test_pilot_app_release_is_an_explicit_opt_in() -> None:
    variables = (ROOT / "infra" / "terraform-pilot" / "variables.tf").read_text(
        encoding="utf-8"
    )
    assert 'variable "pilot_app_release_enabled"' in variables
    assert 'default     = false' in variables
    assert "pilot_app_release_enabled requires ci_enabled." in variables
~~~

- [ ] **Step 2: Run the test to verify it fails**

Run: python -m pytest -q test/test_codebuild_pilot_contract.py::test_pilot_app_release_is_an_explicit_opt_in

Expected: FAIL because the flag does not exist.

- [ ] **Step 3: Add the variable**

~~~hcl
variable "pilot_app_release_enabled" {
  description = "Append manual approval and backend/frontend-only Pilot EC2 release stages to the CI pipeline."
  type        = bool
  default     = false

  validation {
    condition     = !var.pilot_app_release_enabled || var.ci_enabled
    error_message = "pilot_app_release_enabled requires ci_enabled."
  }
}
~~~

- [ ] **Step 4: Run the focused test to verify it passes**

Run: python -m pytest -q test/test_codebuild_pilot_contract.py::test_pilot_app_release_is_an_explicit_opt_in

Expected: PASS.

- [ ] **Step 5: Commit the isolated flag change**

~~~bash
git add infra/terraform-pilot/variables.tf test/test_codebuild_pilot_contract.py
git commit -m "feat: gate pipeline app releases explicitly"
~~~

## Task 2: Add manual approval and release CodeBuild infrastructure

**Files:**
- Modify: infra/terraform-pilot/codebuild.tf
- Modify: infra/terraform-pilot/codepipeline.tf
- Modify: test/test_codebuild_pilot_contract.py
- Modify: test/test_aws_pilot_infrastructure.py

**Interfaces:**
- Consumes: var.ci_enabled, var.pilot_app_release_enabled, aws_instance.app.id, existing aws_sns_topic.operational_alerts, and SourceArtifact.
- Produces: aws_codebuild_project.pilot_app_release[0], an approval stage named ApprovePilotAppRelease, and a deploy stage named DeployPilotAppRelease.

- [ ] **Step 1: Write failing Terraform topology and IAM contract tests**

Require all of the following assertions:

~~~python
assert 'resource "aws_codebuild_project" "pilot_app_release"' in codebuild
assert 'buildspec = "buildspec.pilot-app-release.yml"' in codebuild
assert 'name = "ApprovePilotAppRelease"' in pipeline
assert 'provider = "Manual"' in pipeline
assert 'name = "DeployPilotAppRelease"' in pipeline
assert 'ProjectName = aws_codebuild_project.pilot_app_release[0].name' in pipeline
assert '"ssm:SendCommand"' in codebuild
assert '"ssm:GetCommandInvocation"' in codebuild
assert "aws_instance.app.arn" in codebuild
assert "AWS-RunShellScript" in codebuild
assert "aws_sns_topic.operational_alerts.arn" in pipeline
~~~

Also assert that the deploy role has no ssm:GetParameter, ssm:PutParameter, database permission, iam:PassRole, or ECR push permission.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: python -m pytest -q test/test_codebuild_pilot_contract.py test/test_aws_pilot_infrastructure.py -k "app_release or codepipeline"

Expected: FAIL because no release project, approval stage, or scoped SSM policy exists.

- [ ] **Step 3: Implement the release CodeBuild resources and role**

Use a shared local gate:

~~~hcl
locals {
  pilot_app_release_enabled = var.ci_enabled && var.pilot_app_release_enabled
}
~~~

Create a 30-day release log group, a role trusted only by codebuild.amazonaws.com, and an inline policy containing only:

- CloudWatch logs:CreateLogStream and logs:PutLogEvents for the new log group.
- S3 GetObject, GetObjectVersion, GetBucketAcl, and GetBucketLocation for the existing private pipeline artifact bucket; no S3 write permission is needed because the deploy action has no output artifact.
- ssm:SendCommand for aws_instance.app.arn and the AWS-managed AWS-RunShellScript document ARN.
- ssm:GetCommandInvocation only as broad as AWS action authorization requires, in a dedicated read-only statement.

Create aws_codebuild_project.pilot_app_release with CODEPIPELINE source/artifacts, no privileged mode, and plaintext non-secret environment variables for region, Pilot instance ID, backend repository URL, and frontend repository URL.

- [ ] **Step 4: Implement optional pipeline stages**

Keep Source and Build unchanged. Add dynamic stages only when local.pilot_app_release_enabled is true:

~~~hcl
dynamic "stage" {
  for_each = local.pilot_app_release_enabled ? [1] : []
  content {
    name = "ApprovePilotAppRelease"
    action {
      name     = "ApproveImmutableAppImages"
      category = "Approval"
      owner    = "AWS"
      provider = "Manual"
      version  = "1"
      configuration = {
        NotificationArn = aws_sns_topic.operational_alerts.arn
        CustomData      = "Promotes backend/frontend images for the verified dev commit only; RAG, schema, paid smoke, and Vision are excluded."
      }
    }
  }
}
~~~

Add the following dynamic deploy stage using SourceArtifact as its input and the release project as its CodeBuild project. Extend the existing CodePipeline role policy so codebuild:StartBuild and codebuild:BatchGetBuilds include both CodeBuild project ARNs only when the release flag is enabled, and add sns:Publish limited to aws_sns_topic.operational_alerts.arn for the approval notification.

- [ ] **Step 5: Format and verify Terraform and focused tests**

~~~bash
terraform -chdir=infra/terraform-pilot fmt -check
terraform -chdir=infra/terraform-pilot init -backend=false -input=false
terraform -chdir=infra/terraform-pilot validate
python -m pytest -q test/test_codebuild_pilot_contract.py test/test_aws_pilot_infrastructure.py
~~~

Expected: formatting, validation, and focused tests PASS.

- [ ] **Step 6: Commit the infrastructure contract**

~~~bash
git add infra/terraform-pilot/codebuild.tf infra/terraform-pilot/codepipeline.tf test/test_codebuild_pilot_contract.py test/test_aws_pilot_infrastructure.py
git commit -m "feat: add approved pipeline app release stage"
~~~

## Task 3: Implement the app-only SSM release runner

**Files:**
- Create: buildspec.pilot-app-release.yml
- Create: deploy/aws-pilot/Release-PilotApp-FromPipeline.sh
- Modify: test/test_codebuild_pilot_contract.py

**Interfaces:**
- Consumes: AWS_DEFAULT_REGION, PILOT_INSTANCE_ID, BACKEND_REPOSITORY_URL, FRONTEND_REPOSITORY_URL, and CODEBUILD_RESOLVED_SOURCE_VERSION from CodeBuild.
- Produces: one AWS-RunShellScript command, terminal status polling, and nonzero exit on a failed or timed-out release.

- [ ] **Step 1: Write failing release-runner behavior tests**

~~~python
assert 'IMAGE_TAG="${CODEBUILD_RESOLVED_SOURCE_VERSION:0:12}"' in runner
assert '[[ "$IMAGE_TAG" =~ ^[0-9a-f]{12}$ ]]' in runner
assert "migrate --check" in runner
assert "docker compose pull backend frontend" in runner
assert "docker compose up -d --no-deps backend frontend" in runner
assert "curl --fail --silent --show-error" in runner
assert "rollback_app_release" in runner
assert "aws ssm send-command" in runner
assert "aws ssm get-command-invocation" in runner
assert "smoke_" not in runner
assert "load_legal" not in runner
assert "rag-loader" not in runner
assert "law-neo4j" not in runner
~~~

The buildspec test must require invocation of the runner and must reject Docker build/push commands.

- [ ] **Step 2: Run the tests to verify they fail**

Run: python -m pytest -q test/test_codebuild_pilot_contract.py -k "app_release"

Expected: FAIL because the runner and dedicated buildspec do not exist.

- [ ] **Step 3: Create the release buildspec**

~~~yaml
version: 0.2
phases:
  build:
    commands:
      - bash deploy/aws-pilot/Release-PilotApp-FromPipeline.sh
~~~

Do not install runtime secrets, run pytest, build Docker images, or push images in this release project.

- [ ] **Step 4: Create the Bash runner and remote release protocol**

Implement Release-PilotApp-FromPipeline.sh with set -euo pipefail and these exact boundaries:

1. Require the four non-secret environment variables and derive/validate the twelve-character lowercase tag.
2. Generate an SSM JSON request in a temporary file and remove it with a trap.
3. Send exactly one AWS-RunShellScript command to PILOT_INSTANCE_ID and poll get-command-invocation every ten seconds until Success, Failed, Cancelled, or TimedOut; cancel on the bounded timeout.
4. In the remote command, acquire /var/lock/skn27-pilot-maintenance.lock, resolve /opt/skn27-pilot/current, read the old RELEASE_TAG from .compose.env, and reject a missing or non-commit tag.
5. Define rollback_app_release before mutation. It restores the old tag in .compose.env, runs docker compose up -d --no-deps backend frontend, and exits with the original nonzero status.
6. Use an exported candidate RELEASE_TAG for docker compose run --rm --no-deps backend python backend/manage.py migrate --check; only continue when it succeeds.
7. Persist the candidate tag, pull/recreate only backend/frontend, then run local HTTPS live and ready checks with curl --resolve APP_DOMAIN:443:127.0.0.1.
8. Never invoke RAG, Neo4j, Redis, Caddy, worker, Vision, paid smoke, or schema-writing migration commands.

- [ ] **Step 5: Run focused runner tests to verify they pass**

Run: python -m pytest -q test/test_codebuild_pilot_contract.py -k "app_release"

Expected: PASS.

- [ ] **Step 6: Commit the release runner**

~~~bash
git add buildspec.pilot-app-release.yml deploy/aws-pilot/Release-PilotApp-FromPipeline.sh test/test_codebuild_pilot_contract.py
git commit -m "feat: add app-only pipeline release runner"
~~~

## Task 4: Document operation, activation, and full verification

**Files:**
- Modify: deploy/aws-pilot/README.ko.md
- Modify: test/test_aws_pilot_infrastructure.py

**Interfaces:**
- Consumes: the release project/stages from Task 2 and runner behavior from Task 3.
- Produces: an operator runbook that distinguishes app-only approved releases from the full manual release path.

- [ ] **Step 1: Write the failing documentation contract**

Add a test requiring the Pilot README to contain ApprovePilotAppRelease, pilot_app_release_enabled, migrate --check, rollback guidance, and explicit exclusions for RAG seed, paid smoke, Vision Worker, and Compose/Caddy changes.

- [ ] **Step 2: Run the test to verify it fails**

Run: python -m pytest -q test/test_aws_pilot_infrastructure.py -k "app_release"

Expected: FAIL because the runbook does not describe the new path.

- [ ] **Step 3: Update the Korean Pilot runbook**

Document these operator steps:

1. Confirm the Build stage succeeded for the intended commit.
2. Review the immutable backend/frontend tag and approve only an app-only release in CodePipeline.
3. Read the dedicated deploy CodeBuild and SSM command result.
4. Treat a failed migration check or health check as an unpromoted release; verify rollback output and retain the prior tag.
5. Use Deploy-Pilot.ps1 for RAG, schema/data, Compose/Caddy, or full release work instead.
6. Enable the path only with a reviewed Terraform plan setting both ci_enabled=true and pilot_app_release_enabled=true.

- [ ] **Step 4: Run full verification**

~~~bash
terraform -chdir=infra/terraform-pilot fmt -check
terraform -chdir=infra/terraform-pilot validate
python -m pytest -q test/test_aws_pilot_infrastructure.py test/test_aws_vision_worker_infrastructure.py test/test_codebuild_pilot_contract.py
python -c "import pathlib,yaml; yaml.safe_load(pathlib.Path('buildspec.pilot-app-release.yml').read_text(encoding='utf-8')); print('VALID_YAML')"
git diff --check
~~~

Expected: all commands PASS.

- [ ] **Step 5: Review the rendered Terraform change before any apply**

After merge, create a plan with ci_enabled=true and pilot_app_release_enabled=true. It may add the release CodeBuild project, release log group, release IAM role/policy, and the two optional pipeline stages. Stop and investigate if the plan changes EC2, RDS, existing ingress rules, runtime secrets, or unrelated IAM policies.

- [ ] **Step 6: Commit docs and final contracts**

~~~bash
git add deploy/aws-pilot/README.ko.md test/test_aws_pilot_infrastructure.py
git commit -m "docs: document approved pilot app releases"
~~~
