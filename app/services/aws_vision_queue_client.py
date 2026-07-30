"""Privacy-safe client for the on-demand AWS Vision FIFO queue."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.services.runpod_vision_client import (
    RUNPOD_REQUEST_SCHEMA_VERSION,
    SAFE_IDENTIFIER,
)


REMOTE_ERROR_CODES = {
    "vision_remote_execution_failed",
    "vision_remote_timeout",
    "vision_remote_unavailable",
    "vision_remote_invalid_response",
}
DEFAULT_TIMEOUT_SECONDS = 900.0
DEFAULT_POLL_INTERVAL_SECONDS = 2.0


class AwsVisionQueueError(RuntimeError):
    """Stable provider error that never includes queue or object details."""

    def __init__(self, code: str):
        safe_code = code if code in REMOTE_ERROR_CODES else "vision_remote_unavailable"
        super().__init__(safe_code)
        self.code = safe_code


@dataclass(frozen=True)
class AwsVisionQueueConfig:
    queue_url: str
    result_bucket: str
    result_prefix: str = "vision/aws-queue/v1"
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS

    def __post_init__(self) -> None:
        parsed = urlsplit(self.queue_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.path.endswith(".fifo")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or not self.result_bucket
            or self.timeout_seconds <= 0
            or self.poll_interval_seconds <= 0
        ):
            raise AwsVisionQueueError("vision_remote_unavailable")

    @classmethod
    def from_environment(cls) -> AwsVisionQueueConfig:
        return cls(
            queue_url=os.getenv("AWS_VISION_QUEUE_URL", "").strip(),
            result_bucket=os.getenv("AWS_VISION_RESULT_BUCKET", "").strip(),
            result_prefix=os.getenv(
                "AWS_VISION_RESULT_PREFIX", "vision/aws-queue/v1"
            ).strip(),
            timeout_seconds=_positive_float(
                "AWS_VISION_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS
            ),
            poll_interval_seconds=_positive_float(
                "AWS_VISION_POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS
            ),
        )


@dataclass(frozen=True)
class AwsVisionQueueResult:
    execution_id: str
    output: dict[str, Any]


Submit = Callable[..., dict[str, Any]]
ReadResult = Callable[..., dict[str, Any] | None]


class AwsVisionQueueClient:
    def __init__(
        self,
        config: AwsVisionQueueConfig,
        *,
        submit: Submit | None = None,
        read_result: ReadResult | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._submit = submit or _default_submit
        self._read_result = read_result or _default_read_result
        self._sleep = sleep
        self._clock = clock

    def run(self, request: dict[str, Any]) -> AwsVisionQueueResult:
        safe_request = _validated_request(request)
        execution_id = safe_request["execution_id"]
        try:
            response = self._submit(
                QueueUrl=self._config.queue_url,
                MessageBody=json.dumps(
                    safe_request, ensure_ascii=True, separators=(",", ":")
                ),
                MessageDeduplicationId=execution_id,
                MessageGroupId="vision",
            )
        except Exception:
            raise AwsVisionQueueError("vision_remote_unavailable") from None
        if not isinstance(response, dict) or not str(response.get("MessageId") or ""):
            raise AwsVisionQueueError("vision_remote_invalid_response")

        started_at = self._clock()
        while self._clock() - started_at < self._config.timeout_seconds:
            try:
                output = self._read_result(
                    bucket=self._config.result_bucket,
                    key=_result_key(self._config.result_prefix, execution_id),
                )
            except Exception:
                raise AwsVisionQueueError("vision_remote_unavailable") from None
            if output is None:
                self._sleep(self._config.poll_interval_seconds)
                continue
            if not _is_safe_handoff(output):
                raise AwsVisionQueueError("vision_remote_invalid_response")
            return AwsVisionQueueResult(execution_id=execution_id, output=output)
        raise AwsVisionQueueError("vision_remote_timeout")


def _validated_request(request: Any) -> dict[str, str]:
    if not isinstance(request, dict):
        raise AwsVisionQueueError("vision_remote_invalid_response")
    fields = ("execution_id", "attachment_id", "video_url", "content_type")
    if request.get("schema_version") != RUNPOD_REQUEST_SCHEMA_VERSION:
        raise AwsVisionQueueError("vision_remote_invalid_response")
    if any(not isinstance(request.get(name), str) or not request[name] for name in fields):
        raise AwsVisionQueueError("vision_remote_invalid_response")
    if not SAFE_IDENTIFIER.fullmatch(request["execution_id"]) or not SAFE_IDENTIFIER.fullmatch(
        request["attachment_id"]
    ):
        raise AwsVisionQueueError("vision_remote_invalid_response")
    parsed = urlsplit(request["video_url"])
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise AwsVisionQueueError("vision_remote_invalid_response")
    return {
        "schema_version": RUNPOD_REQUEST_SCHEMA_VERSION,
        **{name: request[name] for name in fields},
    }


def _result_key(prefix: str, execution_id: str) -> str:
    return f"{prefix.strip('/')}/{execution_id}.json"


def _is_safe_handoff(value: Any) -> bool:
    handoff = value.get("vision_supervisor_handoff") if isinstance(value, dict) else None
    return isinstance(handoff, dict) and handoff.get("status") in {
        "complete",
        "partial",
        "failed",
    }


def _default_submit(**kwargs) -> dict[str, Any]:
    import boto3

    return boto3.client("sqs").send_message(**kwargs)


def _default_read_result(*, bucket: str, key: str) -> dict[str, Any] | None:
    import boto3
    from botocore.exceptions import ClientError

    try:
        response = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if str(exc.response.get("Error", {}).get("Code") or "") in {
            "NoSuchKey",
            "404",
        }:
            return None
        raise
    raw = response["Body"].read(1_048_577)
    if len(raw) > 1_048_576:
        raise AwsVisionQueueError("vision_remote_invalid_response")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AwsVisionQueueError("vision_remote_invalid_response") from None
    return decoded if isinstance(decoded, dict) else None


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        raise AwsVisionQueueError("vision_remote_unavailable") from None
    if value <= 0:
        raise AwsVisionQueueError("vision_remote_unavailable")
    return value
