from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_buildspec_conditionally_builds_immutable_vision_image() -> None:
    buildspec = (ROOT / "buildspec.pilot.yml").read_text(encoding="utf-8")
    immutable_builder = (
        ROOT / "deploy" / "aws-pilot" / "Build-And-Push-ImmutableImages.sh"
    )

    assert "test/test_aws_vision_worker_infrastructure.py" in buildspec
    assert "bash deploy/aws-pilot/Build-And-Push-ImmutableImages.sh" in buildspec
    assert immutable_builder.is_file()

    builder = immutable_builder.read_text(encoding="utf-8")
    assert "CODEBUILD_RESOLVED_SOURCE_VERSION" in builder
    assert "aws ecr describe-images" in builder
    assert '--image-ids "imageTag=$IMAGE_TAG"' in builder
    assert 'docker push "$BACKEND_REPOSITORY_URL:$IMAGE_TAG"' in builder
    assert 'docker push "$FRONTEND_REPOSITORY_URL:$IMAGE_TAG"' in builder
    assert 'test -n "${VISION_REPOSITORY_URI:-}"' in builder
    assert 'docker push "$VISION_REPOSITORY_URI:$IMAGE_TAG"' in builder
    assert "Skipping existing immutable image" in builder
    assert "latest" not in buildspec


def test_frontend_build_requires_google_client_id() -> None:
    builder = (
        ROOT / "deploy" / "aws-pilot" / "Build-And-Push-ImmutableImages.sh"
    ).read_text(encoding="utf-8")

    assert (
        "AWS_DEFAULT_REGION BACKEND_REPOSITORY_URL FRONTEND_REPOSITORY_URL "
        "VITE_GOOGLE_CLIENT_ID CODEBUILD_RESOLVED_SOURCE_VERSION"
    ) in builder


def test_terraform_rejects_ci_without_frontend_google_client_id() -> None:
    variables = (ROOT / "infra" / "terraform-pilot" / "variables.tf").read_text(
        encoding="utf-8"
    )
    variable_start = variables.index('variable "frontend_google_client_id"')
    variable_end = variables.index('\n}\n', variable_start) + 2
    google_client_id_variable = variables[variable_start:variable_end]

    assert "!var.ci_enabled || trimspace(var.frontend_google_client_id) != \"\"" in google_client_id_variable
    assert "ci_enabled requires frontend_google_client_id." in google_client_id_variable


def test_codebuild_preflights_immutable_ecr_tags_with_explicit_lookup_failures() -> None:
    codebuild = (
        ROOT / "infra" / "terraform-pilot" / "codebuild.tf"
    ).read_text(encoding="utf-8")
    builder = (
        ROOT / "deploy" / "aws-pilot" / "Build-And-Push-ImmutableImages.sh"
    ).read_text(encoding="utf-8")

    policy_start = codebuild.index('data "aws_iam_policy_document" "codebuild"')
    policy_end = codebuild.index('resource "aws_iam_role_policy" "codebuild"', policy_start)
    build_policy = codebuild[policy_start:policy_end]

    assert '"ecr:DescribeImages"' in build_policy
    assert "ImageNotFoundException" in builder
    assert "Unable to determine immutable image state" in builder


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
    assert '"ssm:CancelCommand"' in release_policy
    assert 'data "aws_instance" "pilot_app_release_target"' in codebuild
    assert "data.aws_instance.pilot_app_release_target[0].arn" in release_policy
    assert "aws_instance.app.arn" not in release_policy
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


def test_build_codebuild_role_has_no_ssm_release_permissions() -> None:
    codebuild = (
        ROOT / "infra" / "terraform-pilot" / "codebuild.tf"
    ).read_text(encoding="utf-8")

    build_start = codebuild.index('data "aws_iam_policy_document" "codebuild"')
    build_end = codebuild.index(
        'resource "aws_iam_role_policy" "codebuild"', build_start
    )
    build_policy = codebuild[build_start:build_end]

    for forbidden in (
        "ssm:SendCommand",
        "ssm:GetCommandInvocation",
        "ssm:CancelCommand",
    ):
        assert forbidden not in build_policy


def test_app_release_uses_layered_ssm_and_codebuild_timeouts() -> None:
    codebuild = (
        ROOT / "infra" / "terraform-pilot" / "codebuild.tf"
    ).read_text(encoding="utf-8")
    runner = (
        ROOT / "deploy" / "aws-pilot" / "Release-PilotApp-FromPipeline.sh"
    ).read_text(encoding="utf-8")

    release_start = codebuild.index(
        'resource "aws_codebuild_project" "pilot_app_release"'
    )
    release_project = codebuild[release_start:]

    assert "build_timeout  = 40" in release_project
    assert "queued_timeout = 30" in release_project
    assert "readonly ssm_timeout_seconds=1500" in runner
    assert "readonly polling_timeout_seconds=1680" in runner
    assert '"TimeoutSeconds": int(ssm_timeout_seconds)' in runner


def test_app_release_collects_timeout_evidence_before_cancelling_ssm() -> None:
    runner = (
        ROOT / "deploy" / "aws-pilot" / "Release-PilotApp-FromPipeline.sh"
    ).read_text(encoding="utf-8")

    timeout_branch = runner.index("SSM command exceeded")
    evidence = runner.index("StandardOutputContent", timeout_branch)
    cancel = runner.index("aws ssm cancel-command", evidence)
    cancel_result = runner.index("SSM_CANCEL_STATUS=", cancel)

    assert timeout_branch < evidence < cancel < cancel_result


def test_pilot_app_release_does_not_depend_on_the_managed_ec2_resource() -> None:
    codebuild = (
        ROOT / "infra" / "terraform-pilot" / "codebuild.tf"
    ).read_text(encoding="utf-8")

    release_start = codebuild.index('data "aws_instance" "pilot_app_release_target"')
    release_config = codebuild[release_start:]
    assert "data.aws_instance.pilot_app_release_target[0].id" in release_config
    assert "aws_instance.app.id" not in release_config
    assert "aws_instance.app.arn" not in release_config


def test_app_release_runner_restarts_all_services_that_execute_the_backend_image() -> None:
    runner_path = ROOT / "deploy" / "aws-pilot" / "Release-PilotApp-FromPipeline.sh"
    buildspec_path = ROOT / "buildspec.pilot-app-release.yml"

    assert runner_path.is_file()
    assert buildspec_path.is_file()
    runner = runner_path.read_text(encoding="utf-8")
    buildspec = buildspec_path.read_text(encoding="utf-8")

    assert 'IMAGE_TAG="${CODEBUILD_RESOLVED_SOURCE_VERSION:0:12}"' in runner
    assert '[[ "$IMAGE_TAG" =~ ^[0-9a-f]{12}$ ]]' in runner
    assert (
        'PILOT_BACKEND_IP="${PILOT_MIGRATION_CHECK_IP:-172.31.0.11}" '
        'RELEASE_TAG="$target_tag" "${compose[@]}" run --rm --no-deps backend '
        'python backend/manage.py migrate --check'
    ) in runner
    assert "migrate --check" in runner
    runtime_services = "backend frontend agent-worker file-scan-worker ops-monitor"
    assert f'"${{compose[@]}}" pull {runtime_services}' in runner
    assert f'"${{compose[@]}}" rm -sf {runtime_services}' in runner
    assert '"${compose[@]}" up -d --no-deps backend frontend' in runner
    assert '"${compose[@]}" up -d --no-deps agent-worker file-scan-worker ops-monitor' in runner
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


def test_app_release_runner_snapshots_images_under_actual_previous_release_tag() -> None:
    runner = (
        ROOT / "deploy" / "aws-pilot" / "Release-PilotApp-FromPipeline.sh"
    ).read_text(encoding="utf-8")

    assert '[[ "$previous_tag" =~ ^[0-9a-f]{12}$ ]]' in runner
    assert "pipeline-rollback-" not in runner
    assert '"${compose[@]}" ps -q "$service"' in runner
    assert "docker inspect --format '{{.Image}}'" in runner
    assert 'docker tag "$image_id" "$repository:$previous_tag"' in runner
    assert 'snapshot_rollback_image backend "$backend_repository"' in runner
    assert 'snapshot_rollback_image frontend "$frontend_repository"' in runner
    assert 'RELEASE_TAG=$previous_tag' in runner
    assert "Current release tag is not an immutable" in runner
    assert "StandardOutputContent" in runner
    assert "StandardErrorContent" in runner


def test_app_release_runner_overrides_frontend_image_ref_for_release_and_rollback() -> None:
    runner = (
        ROOT / "deploy" / "aws-pilot" / "Release-PilotApp-FromPipeline.sh"
    ).read_text(encoding="utf-8")

    assert 'frontend_image_ref="$frontend_repository:$target_tag"' in runner
    assert 'rollback_frontend_image_ref="$frontend_repository:$previous_tag"' in runner
    runtime_services = "backend frontend agent-worker file-scan-worker ops-monitor"
    assert (
        f'FRONTEND_IMAGE_REF="$frontend_image_ref" "${{compose[@]}}" pull {runtime_services}'
        in runner
    )
    assert (
        f'FRONTEND_IMAGE_REF="$frontend_image_ref" "${{compose[@]}}" rm -sf {runtime_services}'
        in runner
    )
    assert (
        'FRONTEND_IMAGE_REF="$frontend_image_ref" "${compose[@]}" up -d --no-deps backend frontend'
        in runner
    )
    assert (
        'FRONTEND_IMAGE_REF="$frontend_image_ref" "${compose[@]}" up -d --no-deps agent-worker file-scan-worker ops-monitor'
        in runner
    )
    assert (
        f'FRONTEND_IMAGE_REF="$rollback_frontend_image_ref" "${{compose[@]}}" rm -sf {runtime_services} >/dev/null 2>&1'
        in runner
    )
    assert (
        'FRONTEND_IMAGE_REF="$rollback_frontend_image_ref" "${compose[@]}" up -d --no-deps backend frontend'
        in runner
    )
    assert (
        'FRONTEND_IMAGE_REF="$rollback_frontend_image_ref" "${compose[@]}" up -d --no-deps agent-worker file-scan-worker ops-monitor'
        in runner
    )


def test_app_release_reports_complete_or_incomplete_rollback() -> None:
    runner = (
        ROOT / "deploy" / "aws-pilot" / "Release-PilotApp-FromPipeline.sh"
    ).read_text(encoding="utf-8")

    rollback_start = runner.index("rollback_app_release()")
    rollback_end = runner.index("trap rollback_app_release ERR", rollback_start)
    rollback = runner[rollback_start:rollback_end]

    assert "rollback_failures=()" in rollback
    assert "ROLLBACK_STATUS=complete" in rollback
    assert "ROLLBACK_STATUS=incomplete" in rollback
    for step in (
        "restore_tag",
        "restore_previous_evidence",
        "remove_runtime_services",
        "start_frontend_backend",
        "start_workers",
        "cleanup_seed_and_evidence",
    ):
        assert step in rollback


def test_app_release_verifies_descriptor_and_switches_candidate_evidence_atomically() -> None:
    runner = (
        ROOT / "deploy" / "aws-pilot" / "Release-PilotApp-FromPipeline.sh"
    ).read_text(encoding="utf-8")

    descriptor = runner.index("legal-operational-evidence-source.env")
    descriptor_parse = runner.index("while IFS='=' read -r key value", descriptor)
    download = runner.index("aws s3 cp", descriptor_parse)
    digest = runner.index("sha256sum -c -", download)
    manifest = runner.index("verify_production_rag_seed_manifest", digest)
    build = runner.index("build_legal_operational_evidence", manifest)
    validation = runner.index("etl.legal.validate_run_summary", build)
    stop = runner.index('"${compose[@]}" rm -sf', validation)
    promote = runner.index(
        'mv -f "$candidate_evidence_tmp" "$shared_evidence_file"',
        stop,
    )
    gate = runner.index(
        "observe_operational_health --once --gate-mode transaction",
        promote,
    )
    disarm = runner.index("trap - ERR", gate)
    cleanup = runner.index("cleanup_seed_and_evidence", disarm)

    assert descriptor < descriptor_parse < download < digest < manifest
    assert manifest < build < validation < stop < promote < gate
    assert gate < disarm < cleanup
    for token in (
        "shared_evidence_existed",
        "release_evidence_existed",
        "restore_previous_evidence",
        "candidate_evidence_file",
        "cleanup_seed_and_evidence",
    ):
        assert token in runner
    for forbidden in (
        "allow-paid-provider-call",
        "load_review_case_pgvector_seed",
        "load_production_rag_seed",
        "load_legal_graph_seed",
    ):
        assert forbidden not in runner


def test_app_release_gates_target_image_on_active_precedent_seed() -> None:
    runner = (
        ROOT / "deploy" / "aws-pilot" / "Release-PilotApp-FromPipeline.sh"
    ).read_text(encoding="utf-8")

    runtime_version = runner.index("PRECEDENT_NEWPLUSPLUS_SEED_VERSION")
    pull = runner.index('"${compose[@]}" pull', runtime_version)
    seed_verify = runner.index("verify_precedent_newplusplus_seed", pull)
    readiness = runner.index("verify_pgvector_rag_readiness", seed_verify)
    container_replace = runner.index('"${compose[@]}" rm -sf', readiness)
    evidence_promote = runner.index(
        'mv -f "$candidate_evidence_tmp" "$shared_evidence_file"',
        container_replace,
    )

    assert runtime_version < pull < seed_verify < readiness
    assert readiness < container_replace < evidence_promote
    assert (
        'python backend/manage.py verify_precedent_newplusplus_seed '
        '--expected-seed-version "$PRECEDENT_NEWPLUSPLUS_SEED_VERSION" '
        '--format json'
    ) in runner
    assert "python backend/manage.py verify_pgvector_rag_readiness --format json" in runner
    assert "PRECEDENT_SEED_LINES" in runner
    assert "^sha256:[0-9a-f]{64}$" in runner
