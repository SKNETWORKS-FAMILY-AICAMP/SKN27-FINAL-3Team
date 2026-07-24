"""Minimal privacy-safe client for RunPod queue-based Vision jobs."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


RUNPOD_API_BASE_URL = "https://api.runpod.ai/v2"
RUNPOD_REQUEST_SCHEMA_VERSION = "vision-runpod-request-v1"
REMOTE_ERROR_CODES = {
    "vision_remote_execution_failed",
    "vision_remote_cancelled",
    "vision_remote_timeout",
    "vision_remote_unavailable",
    "vision_remote_invalid_response",
}
RUNNING_STATUSES = {"IN_QUEUE", "IN_PROGRESS"}
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RESPONSE_BYTES = 1_048_576
MAX_CONSECUTIVE_POLL_NETWORK_FAILURES = 1


class RunPodVisionError(RuntimeError):
    """Stable failure that never carries provider payloads or credentials."""

    def __init__(self, code: str):
        safe_code = code if code in REMOTE_ERROR_CODES else "vision_remote_unavailable"
        super().__init__(safe_code)
        self.code = safe_code


@dataclass(frozen=True)
class RunPodVisionConfig:
    endpoint_id: str
    api_key: str = field(repr=False)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if not SAFE_IDENTIFIER.fullmatch(self.endpoint_id) or not self.api_key:
            raise RunPodVisionError("vision_remote_unavailable")
        if (
            self.timeout_seconds <= 0
            or self.poll_interval_seconds <= 0
            or self.http_timeout_seconds <= 0
            or self.max_response_bytes <= 0
        ):
            raise RunPodVisionError("vision_remote_unavailable")

    @classmethod
    def from_environment(cls) -> RunPodVisionConfig:
        return cls(
            endpoint_id=os.getenv("RUNPOD_VISION_ENDPOINT_ID", "").strip(),
            api_key=os.getenv("RUNPOD_API_KEY", "").strip(),
            timeout_seconds=_positive_float_environment(
                "RUNPOD_VISION_TIMEOUT_SECONDS",
                DEFAULT_TIMEOUT_SECONDS,
            ),
            poll_interval_seconds=_positive_float_environment(
                "RUNPOD_VISION_POLL_INTERVAL_SECONDS",
                DEFAULT_POLL_INTERVAL_SECONDS,
            ),
            http_timeout_seconds=_positive_float_environment(
                "RUNPOD_VISION_HTTP_TIMEOUT_SECONDS",
                DEFAULT_HTTP_TIMEOUT_SECONDS,
            ),
            max_response_bytes=_positive_int_environment(
                "RUNPOD_VISION_MAX_RESPONSE_BYTES",
                DEFAULT_MAX_RESPONSE_BYTES,
            ),
        )


@dataclass(frozen=True)
class RunPodVisionResult:
    job_id: str
    output: dict[str, Any]


Transport = Callable[..., dict[str, Any]]


class RunPodVisionClient:
    def __init__(
        self,
        config: RunPodVisionConfig,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._config = config
        self._transport = transport or _default_transport
        self._sleep = sleep
        self._clock = clock

    def run(
        self,
        request: dict[str, Any],
        *,
        existing_job_id: str = "",
        on_job_submitted: Callable[[str], None] | None = None,
    ) -> RunPodVisionResult:
        safe_request = _validated_request(request)
        job_id = _validated_identifier(existing_job_id)
        if not job_id:
            job_id = self._submit(safe_request)
            if on_job_submitted is not None:
                on_job_submitted(job_id)

        started_at = self._clock()
        consecutive_network_failures = 0
        while True:
            if self._clock() - started_at >= self._config.timeout_seconds:
                raise RunPodVisionError("vision_remote_timeout")
            try:
                status_payload = self._request_json(
                    method="GET",
                    url=f"{self._base_url()}/status/{job_id}",
                    payload=None,
                )
            except RunPodVisionError as exc:
                if (
                    exc.code == "vision_remote_unavailable"
                    and consecutive_network_failures < MAX_CONSECUTIVE_POLL_NETWORK_FAILURES
                ):
                    consecutive_network_failures += 1
                    self._sleep(self._config.poll_interval_seconds)
                    continue
                raise
            consecutive_network_failures = 0

            response_job_id = _validated_identifier(status_payload.get("id"))
            status = str(status_payload.get("status") or "").strip().upper()
            if response_job_id != job_id or not status:
                raise RunPodVisionError("vision_remote_invalid_response")
            if status in RUNNING_STATUSES:
                self._sleep(self._config.poll_interval_seconds)
                continue
            if status == "FAILED":
                raise RunPodVisionError("vision_remote_execution_failed")
            if status == "CANCELLED":
                raise RunPodVisionError("vision_remote_cancelled")
            if status == "TIMED_OUT":
                raise RunPodVisionError("vision_remote_timeout")
            if status != "COMPLETED":
                raise RunPodVisionError("vision_remote_invalid_response")

            output = status_payload.get("output")
            if not isinstance(output, dict):
                raise RunPodVisionError("vision_remote_invalid_response")
            if isinstance(output.get("vision_worker_error"), dict):
                raise RunPodVisionError("vision_remote_execution_failed")
            if not isinstance(output.get("vision_supervisor_handoff"), dict):
                raise RunPodVisionError("vision_remote_invalid_response")
            return RunPodVisionResult(job_id=job_id, output=output)

    def _submit(self, request: dict[str, Any]) -> str:
        response = self._request_json(
            method="POST",
            url=f"{self._base_url()}/run",
            payload={"input": request},
        )
        job_id = _validated_identifier(response.get("id"))
        if not job_id:
            raise RunPodVisionError("vision_remote_invalid_response")
        return job_id

    def _request_json(
        self,
        *,
        method: str,
        url: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            response = self._transport(
                method=method,
                url=url,
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                },
                payload=payload,
                timeout_seconds=self._config.http_timeout_seconds,
                max_response_bytes=self._config.max_response_bytes,
            )
        except RunPodVisionError:
            raise
        except Exception:
            raise RunPodVisionError("vision_remote_unavailable") from None
        if not isinstance(response, dict):
            raise RunPodVisionError("vision_remote_invalid_response")
        return response

    def _base_url(self) -> str:
        return f"{RUNPOD_API_BASE_URL}/{self._config.endpoint_id}"


def _validated_request(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise RunPodVisionError("vision_remote_invalid_response")
    required_text = (
        "execution_id",
        "attachment_id",
        "video_url",
        "content_type",
    )
    if request.get("schema_version") != RUNPOD_REQUEST_SCHEMA_VERSION:
        raise RunPodVisionError("vision_remote_invalid_response")
    if any(not isinstance(request.get(field), str) or not request[field] for field in required_text):
        raise RunPodVisionError("vision_remote_invalid_response")
    if not _validated_identifier(request["execution_id"]):
        raise RunPodVisionError("vision_remote_invalid_response")
    if not _validated_identifier(request["attachment_id"]):
        raise RunPodVisionError("vision_remote_invalid_response")
    return {key: request[key] for key in ("schema_version", *required_text)}


def _validated_identifier(value: Any) -> str:
    text = str(value or "").strip()
    return text if SAFE_IDENTIFIER.fullmatch(text) else ""


def _default_transport(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    timeout_seconds: float,
    max_response_bytes: int,
) -> dict[str, Any]:
    body = (
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        if payload is not None
        else None
    )
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_response_bytes:
            raise RunPodVisionError("vision_remote_invalid_response")
        raw = response.read(max_response_bytes + 1)
    if len(raw) > max_response_bytes:
        raise RunPodVisionError("vision_remote_invalid_response")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RunPodVisionError("vision_remote_invalid_response") from None
    if not isinstance(decoded, dict):
        raise RunPodVisionError("vision_remote_invalid_response")
    return decoded


def _positive_float_environment(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    try:
        number = float(value) if value else default
    except ValueError:
        raise RunPodVisionError("vision_remote_unavailable") from None
    if number <= 0:
        raise RunPodVisionError("vision_remote_unavailable")
    return number


def _positive_int_environment(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    try:
        number = int(value) if value else default
    except ValueError:
        raise RunPodVisionError("vision_remote_unavailable") from None
    if number <= 0:
        raise RunPodVisionError("vision_remote_unavailable")
    return number
