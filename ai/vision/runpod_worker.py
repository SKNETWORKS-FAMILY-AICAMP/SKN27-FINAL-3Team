"""RunPod Serverless worker for the existing Vision Supervisor handoff pipeline."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import urlsplit

from app.services.runpod_vision_client import SAFE_IDENTIFIER
from app.services.vision_media_analysis_adapter import _safe_worker_handoff
from app.services.vision_media_analysis_adapter import HANDOFF_STATUSES


REQUEST_SCHEMA_VERSION = "vision-runpod-request-v1"
HANDOFF_SCHEMA_VERSION = "vision-supervisor-handoff-v1"
ALLOWED_CONTENT_TYPES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}
WORKER_ERROR_CODES = {
    "vision_worker_invalid_request",
    "vision_worker_download_failed",
    "vision_worker_media_too_large",
    "vision_worker_execution_failed",
    "vision_worker_invalid_handoff",
}
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_DOWNLOAD_BYTES = 52_428_800
DEFAULT_EXECUTION_TIMEOUT_SECONDS = 540
DOWNLOAD_CHUNK_BYTES = 1_048_576
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HANDOFF_GLOB = "storage/vision/outputs/supervisor_handoff/*.json"


class VisionWorkerError(RuntimeError):
    def __init__(self, code: str):
        safe_code = (
            code if code in WORKER_ERROR_CODES else "vision_worker_execution_failed"
        )
        super().__init__(safe_code)
        self.code = safe_code


def handler(job: dict[str, Any]) -> dict[str, Any]:
    request = job.get("input") if isinstance(job, dict) else None
    return run_worker_job(request)


def run_worker_job(request: Any) -> dict[str, Any]:
    try:
        validated = _validate_request(request)
        suffix = ALLOWED_CONTENT_TYPES[validated["content_type"]]
        with TemporaryDirectory(
            prefix=f"runpod-vision-{validated['execution_id']}-"
        ) as directory:
            input_path = Path(directory) / f"input{suffix}"
            _download_video(validated, input_path)
            raw_handoff = _run_pipeline(input_path)
            return _safe_remote_worker_output(raw_handoff)
    except VisionWorkerError as exc:
        return _worker_failure(exc.code)
    except Exception:
        return _worker_failure("vision_worker_execution_failed")


def _validate_request(request: Any) -> dict[str, str]:
    if not isinstance(request, dict):
        raise VisionWorkerError("vision_worker_invalid_request")
    if request.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise VisionWorkerError("vision_worker_invalid_request")
    execution_id = _safe_identifier(request.get("execution_id"))
    attachment_id = _safe_identifier(request.get("attachment_id"))
    content_type = str(request.get("content_type") or "").strip().lower()
    video_url = str(request.get("video_url") or "").strip()
    if (
        not execution_id
        or not attachment_id
        or content_type not in ALLOWED_CONTENT_TYPES
        or not _allowed_https_url(video_url)
    ):
        raise VisionWorkerError("vision_worker_invalid_request")
    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "execution_id": execution_id,
        "attachment_id": attachment_id,
        "video_url": video_url,
        "content_type": content_type,
    }


def _safe_identifier(value: Any) -> str:
    text = str(value or "").strip()
    return text if SAFE_IDENTIFIER.fullmatch(text) else ""


def _allowed_https_url(url: str) -> bool:
    parsed = urlsplit(url)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.fragment)
    ):
        return False
    return _host_is_allowed(parsed.hostname.lower(), _allowed_hosts())


def _allowed_hosts() -> tuple[str, ...]:
    return tuple(
        host.strip().lower()
        for host in os.getenv("RUNPOD_VISION_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    )


def _host_is_allowed(host: str, allowed_hosts: tuple[str, ...]) -> bool:
    for allowed in allowed_hosts:
        if allowed.startswith("*."):
            suffix = allowed[1:]
            if host.endswith(suffix) and host != suffix.removeprefix("."):
                return True
        elif host == allowed:
            return True
    return False


def _download_video(request: dict[str, Any], destination: Path) -> None:
    max_bytes = _positive_int_environment(
        "RUNPOD_VISION_MAX_DOWNLOAD_BYTES",
        DEFAULT_MAX_DOWNLOAD_BYTES,
    )
    timeout_seconds = _positive_float_environment(
        "RUNPOD_VISION_DOWNLOAD_TIMEOUT_SECONDS",
        DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    )
    http_request = urllib.request.Request(
        str(request["video_url"]),
        headers={
            "Accept": str(request["content_type"]),
            "User-Agent": "skn27-runpod-vision-worker/1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            http_request,
            timeout=timeout_seconds,
        ) as response:
            response_content_type = (
                str(response.headers.get("Content-Type") or "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if response_content_type != request["content_type"]:
                raise VisionWorkerError("vision_worker_download_failed")
            content_length = _optional_content_length(
                response.headers.get("Content-Length")
            )
            if content_length is not None and content_length > max_bytes:
                raise VisionWorkerError("vision_worker_media_too_large")

            downloaded = 0
            with destination.open("wb") as output:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise VisionWorkerError("vision_worker_media_too_large")
                    output.write(chunk)
            if downloaded <= 0:
                raise VisionWorkerError("vision_worker_download_failed")
    except VisionWorkerError:
        raise
    except Exception:
        raise VisionWorkerError("vision_worker_download_failed") from None


def _optional_content_length(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        length = int(value)
    except (TypeError, ValueError):
        raise VisionWorkerError("vision_worker_download_failed") from None
    if length < 0:
        raise VisionWorkerError("vision_worker_download_failed")
    return length


def _run_pipeline(input_path: Path) -> dict[str, Any]:
    checkpoint = os.getenv("VISION_TRAINED_CLASSIFIER_CHECKPOINT", "").strip()
    if not checkpoint:
        raise VisionWorkerError("vision_worker_execution_failed")
    environment = os.environ.copy()
    current_python_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(REPOSITORY_ROOT), current_python_path) if value
    )
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "ai.vision.run_to_supervisor",
                str(input_path),
                "--checkpoint",
                checkpoint,
            ],
            cwd=input_path.parent,
            env=environment,
            capture_output=True,
            text=True,
            timeout=_positive_int_environment(
                "RUNPOD_VISION_EXECUTION_TIMEOUT_SECONDS",
                DEFAULT_EXECUTION_TIMEOUT_SECONDS,
            ),
            check=False,
        )
    except Exception:
        raise VisionWorkerError("vision_worker_execution_failed") from None
    if completed.returncode != 0:
        raise VisionWorkerError("vision_worker_execution_failed")
    paths = sorted(input_path.parent.glob(HANDOFF_GLOB))
    if len(paths) != 1:
        raise VisionWorkerError("vision_worker_invalid_handoff")
    try:
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise VisionWorkerError("vision_worker_invalid_handoff") from None
    if not isinstance(payload, dict):
        raise VisionWorkerError("vision_worker_invalid_handoff")
    return payload


def _safe_remote_worker_output(worker_payload: Any) -> dict[str, Any]:
    safe = _safe_worker_handoff(worker_payload)
    if (
        safe.get("handoff_schema_version") != HANDOFF_SCHEMA_VERSION
        or safe.get("status") not in HANDOFF_STATUSES
    ):
        raise VisionWorkerError("vision_worker_invalid_handoff")
    return {
        "vision_supervisor_handoff": {
            "schema_version": HANDOFF_SCHEMA_VERSION,
            "status": safe["status"],
            "media_summary": safe["media_summary"],
            "event_candidates": safe["event_candidates"],
            "visual_evidence": {
                "key_frames": safe["key_frames"],
                "evidence_candidates": safe["evidence_candidates"],
                "detected_object_summary": safe["detected_object_summary"],
            },
            "model_analysis": {
                "trained_accident_prediction": safe[
                    "trained_accident_prediction"
                ],
                "qwen": safe["qwen"],
            },
            "not_determined_by_vision": safe["not_determined_by_vision"],
            "limitations": safe["limitations"],
        }
    }


def _worker_failure(error_code: str) -> dict[str, dict[str, str]]:
    safe_code = (
        error_code
        if error_code in WORKER_ERROR_CODES
        else "vision_worker_execution_failed"
    )
    return {"vision_worker_error": {"error_code": safe_code}}


def _positive_int_environment(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    try:
        number = int(value) if value else default
    except ValueError:
        raise VisionWorkerError("vision_worker_execution_failed") from None
    if number <= 0:
        raise VisionWorkerError("vision_worker_execution_failed")
    return number


def _positive_float_environment(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    try:
        number = float(value) if value else default
    except ValueError:
        raise VisionWorkerError("vision_worker_execution_failed") from None
    if number <= 0:
        raise VisionWorkerError("vision_worker_execution_failed")
    return number


def start_serverless() -> None:
    import runpod

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    start_serverless()
