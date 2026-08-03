from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TERRAFORM = ROOT / "infra" / "terraform-pilot"


def test_vision_worker_infrastructure_is_disabled_until_explicitly_enabled() -> None:
    vision = TERRAFORM / "vision_worker.tf"
    variables = (TERRAFORM / "variables.tf").read_text(encoding="utf-8")

    assert vision.is_file()
    source = vision.read_text(encoding="utf-8")
    assert 'variable "vision_worker_enabled"' in variables
    assert "default     = false" in variables
    assert 'resource "aws_sqs_queue" "vision_worker"' in source
    assert 'resource "aws_sqs_queue" "vision_worker_dlq"' in source
    assert 'resource "aws_lambda_function" "vision_worker_start"' in source
    assert 'resource "aws_lambda_function" "vision_worker_idle_stop"' in source
    assert 'resource "aws_instance" "vision_worker"' in source
    assert "count = var.vision_worker_enabled ? 1 : 0" in source


def test_vision_worker_has_no_public_ip_and_uses_least_privilege_ports() -> None:
    source = (TERRAFORM / "vision_worker.tf").read_text(encoding="utf-8")
    worker_policy = source[
        source.index('data "aws_iam_policy_document" "vision_worker" {') :
        source.index('resource "aws_iam_role_policy" "vision_worker" {')
    ]

    assert "associate_public_ip_address = false" in source
    assert 'resource "aws_vpc_security_group_ingress_rule" "vision_worker"' not in source
    assert "sqs:ReceiveMessage" in worker_policy
    assert "sqs:DeleteMessage" in worker_policy
    assert "s3:GetObject" in worker_policy
    assert "s3:PutObject" in worker_policy
    assert "logs:PutLogEvents" in worker_policy
    assert "ec2:StartInstances" in source
    assert "ec2:StopInstances" in source


def test_pilot_application_role_can_read_only_safe_vision_result_records() -> None:
    iam = (TERRAFORM / "iam.tf").read_text(encoding="utf-8")

    assert "ReadVisionQueueResults" in iam
    assert '"s3:GetObject"' in iam
    assert "vision/aws-queue/v1/*" in iam
    assert "SendVisionQueueJobs" in iam
    assert '"sqs:SendMessage"' in iam
    assert "var.vision_worker_enabled" in iam


def test_vision_worker_mounts_prepared_models_read_only_and_stays_offline() -> None:
    user_data = (TERRAFORM / "vision_worker_user_data.sh.tftpl").read_text(
        encoding="utf-8"
    )

    assert "test -f '${checkpoint_path}/config.json'" in user_data
    assert "test -f '${checkpoint_path}/model.safetensors'" in user_data
    assert "test -f '${checkpoint_path}/pytorch_model.bin'" in user_data
    assert "test -d /vision-volume/huggingface/hub" in user_data
    assert (
        "--mount type=bind,source=/vision-volume,target=/vision-volume,readonly"
        in user_data
    )
    assert "-e HF_HUB_OFFLINE='1'" in user_data
    assert "-e TRANSFORMERS_OFFLINE='1'" in user_data
