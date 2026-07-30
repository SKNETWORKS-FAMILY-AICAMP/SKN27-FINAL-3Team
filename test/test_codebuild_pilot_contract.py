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
