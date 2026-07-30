from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_buildspec_conditionally_builds_immutable_vision_image() -> None:
    buildspec = (ROOT / "buildspec.pilot.yml").read_text(encoding="utf-8")

    assert "CODEBUILD_RESOLVED_SOURCE_VERSION" in buildspec
    assert "test/test_aws_vision_worker_infrastructure.py" in buildspec
    assert "deploy/aws-vision/Dockerfile" in buildspec
    assert 'test -n "$VISION_REPOSITORY_URI"' in buildspec
    assert 'docker push "$VISION_REPOSITORY_URI:$IMAGE_TAG"' in buildspec
    assert "latest" not in buildspec


def test_buildspec_installs_pytest_before_running_ci_contract_tests() -> None:
    buildspec = (ROOT / "buildspec.pilot.yml").read_text(encoding="utf-8")

    install_command = 'python -m pip install --disable-pip-version-check "pytest==9.1.1"'
    test_command = "python -m pytest -q test/test_aws_pilot_infrastructure.py"

    assert install_command in buildspec
    assert test_command in buildspec
    assert buildspec.index(install_command) < buildspec.index(test_command)


def test_terraform_keeps_ci_and_vision_registry_independently_disabled() -> None:
    codebuild = (
        ROOT / "infra" / "terraform-pilot" / "codebuild.tf"
    ).read_text(encoding="utf-8")
    variables = (
        ROOT / "infra" / "terraform-pilot" / "variables.tf"
    ).read_text(encoding="utf-8")
    vision = (
        ROOT / "infra" / "terraform-pilot" / "vision_worker.tf"
    ).read_text(encoding="utf-8")

    assert 'variable "ci_enabled"' in variables
    assert 'variable "vision_registry_enabled"' in variables
    assert 'resource "aws_codebuild_project" "pilot"' in codebuild
    assert "VISION_REPOSITORY_URI" in codebuild
    assert "count = var.vision_registry_enabled ? 1 : 0" in vision
    assert (
        "!var.vision_worker_enabled || var.vision_registry_enabled"
        in variables
    )


def test_pilot_app_release_is_an_explicit_opt_in() -> None:
    variables = (
        ROOT / "infra" / "terraform-pilot" / "variables.tf"
    ).read_text(encoding="utf-8")

    assert 'variable "pilot_app_release_enabled"' in variables
    assert 'default     = false' in variables
    assert "pilot_app_release_enabled requires ci_enabled." in variables


def test_codebuild_role_can_read_and_write_pipeline_artifacts() -> None:
    codebuild = (
        ROOT / "infra" / "terraform-pilot" / "codebuild.tf"
    ).read_text(encoding="utf-8")

    assert '"ReadWritePipelineArtifacts"' in codebuild
    assert '"s3:GetObject"' in codebuild
    assert '"s3:GetObjectVersion"' in codebuild
    assert '"s3:PutObject"' in codebuild
    assert '"s3:GetBucketAcl"' in codebuild
    assert '"s3:GetBucketLocation"' in codebuild
    assert "aws_s3_bucket.pipeline_artifacts[0].arn" in codebuild


def test_pilot_app_release_requires_manual_approval_and_scoped_ssm_access() -> None:
    codebuild = (
        ROOT / "infra" / "terraform-pilot" / "codebuild.tf"
    ).read_text(encoding="utf-8")
    pipeline = (
        ROOT / "infra" / "terraform-pilot" / "codepipeline.tf"
    ).read_text(encoding="utf-8")

    assert 'resource "aws_codebuild_project" "pilot_app_release"' in codebuild
    assert 'buildspec = "buildspec.pilot-app-release.yml"' in codebuild
    assert 'name = "ApprovePilotAppRelease"' in pipeline
    assert 'provider = "Manual"' in pipeline
    assert 'name = "DeployPilotAppRelease"' in pipeline
    assert (
        "ProjectName = aws_codebuild_project.pilot_app_release[0].name"
        in pipeline
    )
    assert "aws_sns_topic.operational_alerts.arn" in pipeline

    policy_start = codebuild.index(
        'data "aws_iam_policy_document" "pilot_app_release"'
    )
    policy_end = codebuild.index(
        'resource "aws_iam_role_policy" "pilot_app_release"', policy_start
    )
    release_policy = codebuild[policy_start:policy_end]
    assert '"ssm:SendCommand"' in release_policy
    assert '"ssm:GetCommandInvocation"' in release_policy
    assert "aws_instance.app.arn" in release_policy
    assert "AWS-RunShellScript" in release_policy
    assert '"s3:GetObject"' in release_policy
    assert '"s3:GetObjectVersion"' in release_policy
    assert '"s3:GetBucketAcl"' in release_policy
    assert '"s3:GetBucketLocation"' in release_policy
    assert "aws_s3_bucket.pipeline_artifacts[0].arn" in release_policy
    for forbidden in (
        "ssm:GetParameter",
        "ssm:PutParameter",
        "rds:",
        "iam:PassRole",
        "ecr:PutImage",
    ):
        assert forbidden not in release_policy


def test_app_release_runner_only_promotes_immutable_app_images() -> None:
    runner_path = ROOT / "deploy" / "aws-pilot" / "Release-PilotApp-FromPipeline.sh"
    buildspec_path = ROOT / "buildspec.pilot-app-release.yml"

    assert runner_path.is_file()
    assert buildspec_path.is_file()
    runner = runner_path.read_text(encoding="utf-8")
    buildspec = buildspec_path.read_text(encoding="utf-8")

    assert 'IMAGE_TAG="${CODEBUILD_RESOLVED_SOURCE_VERSION:0:12}"' in runner
    assert '[[ "$IMAGE_TAG" =~ ^[0-9a-f]{12}$ ]]' in runner
    assert "migrate --check" in runner
    assert '"${compose[@]}" pull backend frontend' in runner
    assert '"${compose[@]}" up -d --no-deps backend frontend' in runner
    assert "curl --fail --silent --show-error" in runner
    assert "rollback_app_release" in runner
    assert "aws ssm send-command" in runner
    assert "aws ssm get-command-invocation" in runner
    for forbidden in (
        "smoke_",
        "load_legal",
        "rag-loader",
        "law-neo4j",
        "redis",
        "caddy",
        "vision",
        "docker compose down",
    ):
        assert forbidden not in runner.lower()

    assert "bash deploy/aws-pilot/Release-PilotApp-FromPipeline.sh" in buildspec
    assert "docker build" not in buildspec
    assert "docker push" not in buildspec
    assert "pytest" not in buildspec
