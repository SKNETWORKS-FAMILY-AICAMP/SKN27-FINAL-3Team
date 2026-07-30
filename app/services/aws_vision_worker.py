"""Private SQS worker for the on-demand AWS Vision provider."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ai.vision.runpod_worker import run_worker_job
from app.services.runpod_vision_client import SAFE_IDENTIFIER
from app.services.vision_media_analysis_adapter import HANDOFF_STATUSES, _safe_worker_handoff


RESULT_PREFIX = "vision/aws-queue/v1"


class AwsVisionWorkerError(RuntimeError):
    """Safe worker error that intentionally contains no request details."""


@dataclass(frozen=True)
class AwsVisionWorkerConfig:
    queue_url: str
    result_bucket: str
    result_prefix: str = RESULT_PREFIX

    @classmethod
    def from_environment(cls) -> "AwsVisionWorkerConfig":
        queue_url = os.getenv("AWS_VISION_QUEUE_URL", "").strip()
        result_bucket = os.getenv("AWS_VISION_RESULT_BUCKET", "").strip()
        result_prefix = os.getenv("AWS_VISION_RESULT_PREFIX", RESULT_PREFIX).strip("/")
        if not queue_url.startswith("https://") or not queue_url.endswith(".fifo"):
            raise AwsVisionWorkerError("vision_worker_configuration_invalid")
        if not result_bucket or not result_prefix:
            raise AwsVisionWorkerError("vision_worker_configuration_invalid")
        return cls(
            queue_url=queue_url,
            result_bucket=result_bucket,
            result_prefix=result_prefix,
        )


RunJob = Callable[[dict[str, Any]], dict[str, Any]]
WriteResult = Callable[..., None]
DeleteMessage = Callable[..., None]


def process_message(
    message: dict[str, Any],
    *,
    run_job: RunJob = run_worker_job,
    write_result: WriteResult,
    delete_message: DeleteMessage,
) -> str:
    """Persist one sanitized handoff before acknowledging its SQS message."""

    request = _message_request(message)
    receipt_handle = str(message.get("ReceiptHandle") or "").strip()
    if not receipt_handle:
        raise AwsVisionWorkerError("vision_worker_message_invalid")

    output = _safe_result(run_job(request))
    write_result(execution_id=request["execution_id"], output=output)
    delete_message(receipt_handle=receipt_handle)
    return "acknowledged"


def run_once(
    config: AwsVisionWorkerConfig,
    *,
    receive_message: Callable[..., dict[str, Any]] | None = None,
    run_job: RunJob | None = None,
    write_result: WriteResult | None = None,
    delete_message: DeleteMessage | None = None,
) -> str:
    """Receive and process at most one FIFO message."""

    receive_message = receive_message or _default_receive_message
    run_job = run_job or run_worker_job
    write_result = write_result or _default_write_result(config)
    delete_message = delete_message or _default_delete_message(config)
    response = receive_message(
        QueueUrl=config.queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=20,
        VisibilityTimeout=900,
    )
    messages = response.get("Messages") if isinstance(response, dict) else None
    if not isinstance(messages, list) or not messages:
        return "idle"
    return process_message(
        messages[0],
        run_job=run_job,
        write_result=write_result,
        delete_message=delete_message,
    )


def main() -> None:
    config = AwsVisionWorkerConfig.from_environment()
    while True:
        run_once(config)


def _message_request(message: Any) -> dict[str, Any]:
    if not isinstance(message, dict):
        raise AwsVisionWorkerError("vision_worker_message_invalid")
    try:
        request = json.loads(str(message.get("Body") or ""))
    except json.JSONDecodeError:
        raise AwsVisionWorkerError("vision_worker_message_invalid") from None
    if not isinstance(request, dict):
        raise AwsVisionWorkerError("vision_worker_message_invalid")
    execution_id = str(request.get("execution_id") or "").strip()
    if not SAFE_IDENTIFIER.fullmatch(execution_id):
        raise AwsVisionWorkerError("vision_worker_message_invalid")
    return request


def _safe_result(value: Any) -> dict[str, Any]:
    handoff = _safe_worker_handoff(value)
    if (
        handoff.get("handoff_schema_version") == "vision-supervisor-handoff-v1"
        and handoff.get("status") in HANDOFF_STATUSES
    ):
        return {
            "vision_supervisor_handoff": {
                "schema_version": handoff["handoff_schema_version"],
                "status": handoff["status"],
                "media_summary": handoff["media_summary"],
                "event_candidates": handoff["event_candidates"],
                "visual_evidence": {
                    "key_frames": handoff["key_frames"],
                    "evidence_candidates": handoff["evidence_candidates"],
                    "detected_object_summary": handoff["detected_object_summary"],
                },
                "model_analysis": {
                    "trained_accident_prediction": handoff[
                        "trained_accident_prediction"
                    ],
                    "qwen": handoff["qwen"],
                },
                "not_determined_by_vision": handoff[
                    "not_determined_by_vision"
                ],
                "limitations": handoff["limitations"],
            }
        }
    return {
        "vision_supervisor_handoff": {
            "schema_version": "vision-supervisor-handoff-v1",
            "status": "failed",
            "media_summary": {},
            "event_candidates": [],
            "visual_evidence": {
                "key_frames": [],
                "evidence_candidates": [],
                "detected_object_summary": {},
            },
            "model_analysis": {
                "trained_accident_prediction": {},
                "qwen": {},
            },
            "not_determined_by_vision": [
                "fault_ratio",
                "liable_party",
                "traffic_violation",
                "final_accident_type",
            ],
            "limitations": [
                "Vision result is unavailable; no fault or legal conclusion was produced."
            ],
        }
    }


def _default_receive_message(**kwargs: Any) -> dict[str, Any]:
    return _sqs_client().receive_message(**kwargs)


def _default_write_result(config: AwsVisionWorkerConfig) -> WriteResult:
    def write_result(*, execution_id: str, output: dict[str, Any]) -> None:
        _s3_client().put_object(
            Bucket=config.result_bucket,
            Key=f"{config.result_prefix}/{execution_id}.json",
            Body=json.dumps(output, ensure_ascii=True, separators=(",", ":")).encode(
                "utf-8"
            ),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )

    return write_result


def _default_delete_message(config: AwsVisionWorkerConfig) -> DeleteMessage:
    def delete_message(*, receipt_handle: str) -> None:
        _sqs_client().delete_message(
            QueueUrl=config.queue_url,
            ReceiptHandle=receipt_handle,
        )

    return delete_message


def _sqs_client() -> Any:
    import boto3

    return boto3.client("sqs")


def _s3_client() -> Any:
    import boto3

    return boto3.client("s3")


if __name__ == "__main__":
    main()
