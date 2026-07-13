from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_MAIN = (ROOT / "infra/terraform/main.tf").read_text(encoding="utf-8")


def _terraform_block(block_type: str, name: str) -> str:
    resource_type, resource_name = name.rsplit(".", 1)
    marker = f'{block_type} "{resource_type}" "{resource_name}"'
    start = TERRAFORM_MAIN.index(marker)
    opening_brace = TERRAFORM_MAIN.index("{", start)
    depth = 0
    for index in range(opening_brace, len(TERRAFORM_MAIN)):
        character = TERRAFORM_MAIN[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return TERRAFORM_MAIN[start : index + 1]
    raise AssertionError(f"unterminated Terraform block: {marker}")


def test_compose_runs_file_scan_worker_after_clamav_is_healthy() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    clamav = services["clamav"]
    assert clamav["healthcheck"]["test"] == [
        "CMD-SHELL",
        "clamdscan --ping 1 || exit 1",
    ]

    worker = services["file-scan-worker"]
    assert worker["image"] == services["backend"]["image"]
    assert "process_uploaded_file_scans --loop" in worker["command"]
    assert worker["restart"] == "unless-stopped"
    assert worker["depends_on"]["clamav"]["condition"] == "service_healthy"
    assert worker["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert worker["environment"]["FILE_SCAN_PROVIDER"] == "clamav"
    assert worker["environment"]["FILE_SCAN_CLAMAV_HOST"] == "clamav"
    assert "100" in worker["environment"]["FILE_RETENTION_PURGE_LIMIT"]


def test_compose_shares_mock_object_storage_without_collapsing_bucket_names() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    mount = "object_storage_data:/app/backend/media/mock_object_storage"

    assert mount in services["backend"]["volumes"]
    assert mount in services["agent-worker"]["volumes"]
    assert mount in services["file-scan-worker"]["volumes"]
    assert "object_storage_data" in compose["volumes"]

    environment = services["backend"]["environment"]
    assert environment["OBJECT_STORAGE_QUARANTINE_BUCKET"]
    assert (
        environment["OBJECT_STORAGE_QUARANTINE_BUCKET"]
        != environment["OBJECT_STORAGE_BUCKET"]
    )
    scanner_environment = services["file-scan-worker"]["environment"]
    for secret_name in (
        "GOOGLE_CLIENT_SECRET",
        "OPENAI_API_KEY",
        "SUPERVISOR_LLM_API_KEY",
        "OAUTH_TOKEN_SECRET",
        "REDIS_URL",
    ):
        assert secret_name not in scanner_environment


def test_terraform_quarantine_bucket_is_private_kms_encrypted_and_short_lived() -> None:
    encryption = _terraform_block(
        "resource",
        "aws_s3_bucket_server_side_encryption_configuration.quarantine",
    )
    assert "bucket = aws_s3_bucket.quarantine.id" in encryption
    assert 'sse_algorithm     = "aws:kms"' in encryption
    assert "kms_master_key_id = aws_kms_key.data.arn" in encryption

    public_access = _terraform_block(
        "resource",
        "aws_s3_bucket_public_access_block.quarantine",
    )
    for setting in (
        "block_public_acls",
        "block_public_policy",
        "ignore_public_acls",
        "restrict_public_buckets",
    ):
        assert re.search(rf"{setting}\s*=\s*true", public_access)

    lifecycle = _terraform_block(
        "resource",
        "aws_s3_bucket_lifecycle_configuration.quarantine",
    )
    assert "bucket = aws_s3_bucket.quarantine.id" in lifecycle
    assert "expiration { days = 7 }" in lifecycle
    assert "noncurrent_version_expiration" not in lifecycle
    assert 'resource "aws_s3_bucket_versioning" "quarantine"' not in TERRAFORM_MAIN

    staging_lifecycle = _terraform_block(
        "resource",
        "aws_s3_bucket_lifecycle_configuration.objects",
    )
    assert "bucket = aws_s3_bucket.objects.id" in staging_lifecycle
    assert "depends_on = [aws_s3_bucket_versioning.objects]" in staging_lifecycle
    assert 'filter { prefix = "staging/" }' in staging_lifecycle
    assert "expiration { days = 1 }" in staging_lifecycle
    assert "noncurrent_version_expiration { noncurrent_days = 1 }" in staging_lifecycle


def test_terraform_wires_quarantine_bucket_to_ecs_with_scoped_iam() -> None:
    environment = TERRAFORM_MAIN[TERRAFORM_MAIN.index("common_environment = [") :]
    assert (
        '{ name = "OBJECT_STORAGE_QUARANTINE_BUCKET", '
        "value = aws_s3_bucket.quarantine.id }"
    ) in environment
    assert TERRAFORM_MAIN.count(
        '{ name = "OBJECT_STORAGE_PREFIX", value = "canonical" }'
    ) >= 2

    iam_policy = _terraform_block("resource", "aws_iam_role_policy.app_data")
    assert '"${aws_s3_bucket.objects.arn}/canonical/uploads/*"' in iam_policy
    assert 'Action   = ["s3:GetObject"]' in iam_policy
    assert '"${aws_s3_bucket.objects.arn}/canonical/reports/*"' in iam_policy
    assert 'Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]' in iam_policy
    assert '"${aws_s3_bucket.objects.arn}/staging/canonical/reports/*"' in iam_policy
    assert '"s3:DeleteObjectVersion"' in iam_policy
    assert 'Action   = ["s3:ListBucketVersions"]' in iam_policy
    assert '"s3:prefix" = ["staging/canonical/reports/*"]' in iam_policy
    assert '"${aws_s3_bucket.quarantine.arn}/canonical/uploads/*"' in iam_policy
    assert 'Action   = ["s3:PutObject"]' in iam_policy
    assert '"${aws_s3_bucket.objects.arn}/*"' not in iam_policy
    assert '"s3:*"' not in iam_policy
    assert 'Resource = ["*"]' not in iam_policy

    scanner_policy = _terraform_block(
        "resource",
        "aws_iam_role_policy.scanner_object_promotion",
    )
    assert '"${aws_s3_bucket.quarantine.arn}/canonical/uploads/*"' in scanner_policy
    assert 'Action   = ["s3:GetObject", "s3:DeleteObject"]' in scanner_policy
    assert '"${aws_s3_bucket.objects.arn}/canonical/uploads/*"' in scanner_policy
    assert (
        'Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", '
        '"s3:DeleteObjectVersion"]'
    ) in scanner_policy
    assert 'Action   = ["s3:ListBucketVersions"]' in scanner_policy
    assert '"s3:prefix" = ["canonical/uploads/*"]' in scanner_policy
    assert '"${aws_s3_bucket.objects.arn}/*"' not in scanner_policy
    assert '"s3:*"' not in scanner_policy
    assert 'Resource = ["*"]' not in scanner_policy

    scanner_task = _terraform_block("resource", "aws_ecs_task_definition.scanner")
    assert re.search(
        r"task_role_arn\s*=\s*aws_iam_role\.ecs_scanner_task\.arn",
        scanner_task,
    )
    assert "environment = local.scanner_environment" in scanner_task
    assert "secrets     = local.scanner_secrets" in scanner_task
    assert '"--purge-limit", "100"' in scanner_task
    for secret_name in (
        "GOOGLE_CLIENT_SECRET",
        "SUPERVISOR_LLM_API_KEY",
        "APP_JWT_SECRET",
    ):
        assert secret_name not in scanner_task

    outputs = (ROOT / "infra/terraform/outputs.tf").read_text(encoding="utf-8")
    assert 'output "quarantine_bucket"' in outputs
    assert "value = aws_s3_bucket.quarantine.id" in outputs


def test_environment_templates_document_separate_quarantine_storage() -> None:
    local_env = (ROOT / ".env.example").read_text(encoding="utf-8")
    production_env = (ROOT / ".env.production.example").read_text(encoding="utf-8")
    guide = (ROOT / "docs/ops/production-env.md").read_text(encoding="utf-8")

    for content in (local_env, production_env, guide):
        assert "OBJECT_STORAGE_QUARANTINE_BUCKET" in content
        assert "FILE_UPLOAD_MAX_BYTES" in content
        assert "FILE_SCAN_CLAIM_STALE_AFTER_SECONDS" in content
        assert "FILE_SCAN_RETRY_BACKOFF_SECONDS" in content
        assert "FILE_RETENTION_PURGE_LIMIT" in content
        assert "FILE_MAX_ATTACHMENTS_PER_REQUEST" in content
        assert "REPORT_STAGING_CLEANUP_LIMIT" in content
    assert "7 days" in guide
    assert "SSE-KMS" in guide
    assert "must be different from `OBJECT_STORAGE_BUCKET`" in guide
    assert "purge_expired_uploads" in guide
    assert "DeleteObjectVersion" in guide
    assert "ListBucketVersions" in guide
