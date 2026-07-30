from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import aws_vision_worker as worker


ROOT = Path(__file__).resolve().parents[1]


def _request() -> dict[str, str]:
    return {
        "schema_version": "vision-runpod-request-v1",
        "execution_id": "exec_aws_worker_1",
        "attachment_id": "att_aws_worker_1",
        "video_url": "https://private.example/video.mp4?signature=private",
        "content_type": "video/mp4",
    }


def test_worker_deletes_message_only_after_safe_handoff_persisted() -> None:
    events: list[str] = []
    persisted: list[dict] = []

    def run_job(request: dict) -> dict:
        events.append("run")
        assert request == _request()
        return {
            "vision_supervisor_handoff": {
                "schema_version": "vision-supervisor-handoff-v1",
                "status": "partial",
                "media_summary": {"summary": "collision candidate"},
                "source": {"video_url": request["video_url"]},
            }
        }

    def write_result(*, execution_id: str, output: dict) -> None:
        events.append("persist")
        assert execution_id == "exec_aws_worker_1"
        persisted.append(output)

    def delete_message(*, receipt_handle: str) -> None:
        events.append("ack")
        assert receipt_handle == "receipt-private"

    result = worker.process_message(
        {
            "Body": json.dumps(_request()),
            "ReceiptHandle": "receipt-private",
        },
        run_job=run_job,
        write_result=write_result,
        delete_message=delete_message,
    )

    assert result == "acknowledged"
    assert events == ["run", "persist", "ack"]
    assert persisted[0]["vision_supervisor_handoff"]["status"] == "partial"
    assert "signature=private" not in repr(persisted)


def test_run_once_receives_only_one_message_from_the_fifo_queue() -> None:
    received: list[dict] = []
    persisted: list[dict] = []
    deleted: list[str] = []

    def receive_message(**kwargs) -> dict:
        received.append(kwargs)
        return {
            "Messages": [
                {
                    "Body": json.dumps(_request()),
                    "ReceiptHandle": "receipt-1",
                }
            ]
        }

    def run_job(_request: dict) -> dict:
        return {
            "vision_supervisor_handoff": {
                "schema_version": "vision-supervisor-handoff-v1",
                "status": "complete",
            }
        }

    result = worker.run_once(
        worker.AwsVisionWorkerConfig(
            queue_url="https://sqs.ap-northeast-2.amazonaws.com/123/vision.fifo",
            result_bucket="vision-results",
        ),
        receive_message=receive_message,
        run_job=run_job,
        write_result=lambda **kwargs: persisted.append(kwargs),
        delete_message=lambda *, receipt_handle: deleted.append(receipt_handle),
    )

    assert result == "acknowledged"
    assert received == [
        {
            "QueueUrl": "https://sqs.ap-northeast-2.amazonaws.com/123/vision.fifo",
            "MaxNumberOfMessages": 1,
            "WaitTimeSeconds": 20,
            "VisibilityTimeout": 900,
        }
    ]
    assert persisted[0]["execution_id"] == "exec_aws_worker_1"
    assert deleted == ["receipt-1"]


def test_worker_config_requires_fifo_queue_and_result_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AWS_VISION_QUEUE_URL", raising=False)
    monkeypatch.delenv("AWS_VISION_RESULT_BUCKET", raising=False)

    with pytest.raises(worker.AwsVisionWorkerError):
        worker.AwsVisionWorkerConfig.from_environment()

    monkeypatch.setenv(
        "AWS_VISION_QUEUE_URL",
        "https://sqs.ap-northeast-2.amazonaws.com/123/vision.fifo",
    )
    monkeypatch.setenv("AWS_VISION_RESULT_BUCKET", "vision-results")

    assert worker.AwsVisionWorkerConfig.from_environment() == (
        worker.AwsVisionWorkerConfig(
            queue_url="https://sqs.ap-northeast-2.amazonaws.com/123/vision.fifo",
            result_bucket="vision-results",
        )
    )


def test_default_ports_persist_before_deleting_the_fifo_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    stored: list[dict] = []

    class Sqs:
        def receive_message(self, **kwargs) -> dict:
            events.append("receive")
            assert kwargs["MaxNumberOfMessages"] == 1
            return {
                "Messages": [
                    {
                        "Body": json.dumps(_request()),
                        "ReceiptHandle": "receipt-default",
                    }
                ]
            }

        def delete_message(self, **kwargs) -> None:
            events.append("delete")
            assert kwargs["ReceiptHandle"] == "receipt-default"

    class S3:
        def put_object(self, **kwargs) -> None:
            events.append("store")
            stored.append(kwargs)

    monkeypatch.setattr(worker, "_sqs_client", lambda: Sqs(), raising=False)
    monkeypatch.setattr(worker, "_s3_client", lambda: S3(), raising=False)
    monkeypatch.setattr(
        worker,
        "run_worker_job",
        lambda _request: {
            "vision_supervisor_handoff": {
                "schema_version": "vision-supervisor-handoff-v1",
                "status": "failed",
            }
        },
    )

    result = worker.run_once(
        worker.AwsVisionWorkerConfig(
            queue_url="https://sqs.ap-northeast-2.amazonaws.com/123/vision.fifo",
            result_bucket="vision-results",
        )
    )

    assert result == "acknowledged"
    assert events == ["receive", "store", "delete"]
    assert stored[0]["Bucket"] == "vision-results"
    assert stored[0]["Key"] == "vision/aws-queue/v1/exec_aws_worker_1.json"
    assert stored[0]["ServerSideEncryption"] == "AES256"


def test_aws_vision_worker_image_has_no_models_or_runtime_secrets() -> None:
    dockerfile_path = ROOT / "deploy" / "aws-vision" / "Dockerfile"
    requirements_path = ROOT / "deploy" / "aws-vision" / "requirements.txt"

    assert dockerfile_path.is_file()
    assert requirements_path.is_file()

    dockerfile = dockerfile_path.read_text(encoding="utf-8")
    requirements = requirements_path.read_text(encoding="utf-8")
    assert "python -u -m app.services.aws_vision_worker" in dockerfile
    assert "COPY ai " in dockerfile
    assert "COPY app " in dockerfile
    assert "COPY models" not in dockerfile
    assert "AWS_VISION_QUEUE_URL=" not in dockerfile
    assert "VISION_TRAINED_CLASSIFIER_CHECKPOINT=" not in dockerfile
    assert "boto3" in requirements
