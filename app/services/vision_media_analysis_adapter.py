"""Isolated adapter for the existing VideoMAE, YOLO, and Qwen Vision pipeline."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import urlsplit

from app.services.runpod_vision_client import (
    RunPodVisionClient,
    RunPodVisionConfig,
    RunPodVisionError,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VISION_NODE_CODE = "vision_media_analysis"
VISION_CHECKPOINT_ENV = "VISION_TRAINED_CLASSIFIER_CHECKPOINT"
DEFAULT_RUNTIME_TIMEOUT_SECONDS = 180
HANDOFF_GLOB = "storage/vision/outputs/supervisor_handoff/*.json"
RUNPOD_REQUEST_SCHEMA_VERSION = "vision-runpod-request-v1"
RUNPOD_SIGNED_URL_GRACE_SECONDS = 60
RUNPOD_JOB_CACHE_GRACE_SECONDS = 300
RUNPOD_JOB_CACHE_PREFIX = "vision:runpod:v1"


def run_vision_media_analysis(
    agent_input: dict[str, Any],
    adapter_context: dict[str, Any],
) -> dict[str, Any]:
    """Run Vision only for a canonical scan-ready blackbox video attachment."""

    attachment = _select_scan_ready_video(agent_input.get("attachments") or [])
    if attachment is None:
        return _failure("attachment_not_scan_ready")

    provider = os.getenv("VISION_RUNTIME_PROVIDER", "local").strip().lower() or "local"
    if provider == "local":
        return _run_local_provider(attachment, adapter_context)
    if provider == "runpod":
        return _run_runpod_provider(attachment, adapter_context)
    return _failure("vision_remote_unavailable")


def _run_local_provider(
    attachment: dict[str, Any],
    adapter_context: dict[str, Any],
) -> dict[str, Any]:
    checkpoint = _configured_checkpoint()
    if checkpoint is None or not _checkpoint_is_complete(checkpoint):
        return _failure("vision_checkpoint_missing")

    try:
        video_bytes = _read_scan_ready_video_bytes(attachment)
    except Exception:
        return _failure("attachment_not_scan_ready")
    if not video_bytes:
        return _failure("attachment_not_scan_ready")

    execution_id = _safe_execution_id(adapter_context.get("execution_id"))
    try:
        with TemporaryDirectory(prefix=f"vision-{execution_id}-") as directory:
            workspace = Path(directory)
            input_path = workspace / "input.mp4"
            input_path.write_bytes(video_bytes)
            try:
                completed = _run_vision_subprocess(
                    input_path=input_path,
                    checkpoint=checkpoint,
                    workspace=workspace,
                )
            except subprocess.TimeoutExpired:
                return _failure("vision_execution_timeout")
            except OSError:
                return _failure("vision_execution_failed")

            if completed.returncode != 0:
                return _failure(_subprocess_failure_code(completed))

            handoff_path = _single_handoff_path(workspace)
            worker_payload = json.loads(handoff_path.read_text(encoding="utf-8"))
            return _success(_safe_worker_handoff(worker_payload))
    except (OSError, ValueError, json.JSONDecodeError):
        return _failure("vision_execution_failed")


def _run_runpod_provider(
    attachment: dict[str, Any],
    adapter_context: dict[str, Any],
) -> dict[str, Any]:
    execution_id = _safe_execution_id(adapter_context.get("execution_id"))
    attachment_id = _safe_execution_id(attachment.get("attachment_id"))
    content_type = str(
        attachment.get("content_type") or attachment.get("mime_type") or ""
    ).lower()
    try:
        config = RunPodVisionConfig.from_environment()
        video_url = _presign_runpod_video(
            attachment,
            timeout_seconds=config.timeout_seconds,
        )
        request = {
            "schema_version": RUNPOD_REQUEST_SCHEMA_VERSION,
            "execution_id": execution_id,
            "attachment_id": attachment_id,
            "video_url": video_url,
            "content_type": content_type,
        }
        existing_job_id = _cached_runpod_job_id(execution_id)
        cache_ttl = math.ceil(
            config.timeout_seconds + RUNPOD_JOB_CACHE_GRACE_SECONDS
        )
        result = _new_runpod_client(config).run(
            request,
            existing_job_id=existing_job_id,
            on_job_submitted=lambda job_id: _cache_runpod_job_id(
                execution_id,
                job_id,
                cache_ttl,
            ),
        )
        safe_handoff = _safe_worker_handoff(result.output)
        if safe_handoff.get("handoff_schema_version") != "vision-supervisor-handoff-v1":
            raise RunPodVisionError("vision_remote_invalid_response")
        return _success(safe_handoff)
    except RunPodVisionError as exc:
        return _failure(exc.code)
    except Exception:
        return _failure("vision_remote_unavailable")


def _new_runpod_client(config: RunPodVisionConfig) -> RunPodVisionClient:
    return RunPodVisionClient(config)


def presign_get(
    reference: dict[str, Any],
    *,
    ttl_seconds: int,
) -> dict[str, Any]:
    from chatbot.object_storage import presign_get as object_storage_presign_get

    return object_storage_presign_get(reference, ttl_seconds=ttl_seconds)


def _presign_runpod_video(
    attachment: dict[str, Any],
    *,
    timeout_seconds: float,
) -> str:
    reference = attachment.get("object_storage")
    if not isinstance(reference, dict) or reference.get("provider") != "s3":
        raise RunPodVisionError("vision_remote_unavailable")
    ttl_seconds = math.ceil(timeout_seconds + RUNPOD_SIGNED_URL_GRACE_SECONDS)
    result = presign_get(reference, ttl_seconds=ttl_seconds)
    if (
        not isinstance(result, dict)
        or result.get("status") != "ready"
        or result.get("provider") != "s3"
    ):
        raise RunPodVisionError("vision_remote_unavailable")
    try:
        actual_ttl = int(result.get("ttl_seconds") or 0)
    except (TypeError, ValueError):
        raise RunPodVisionError("vision_remote_unavailable") from None
    url = str(result.get("url") or "")
    parsed = urlsplit(url)
    if (
        actual_ttl < math.ceil(timeout_seconds)
        or parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.fragment)
    ):
        raise RunPodVisionError("vision_remote_unavailable")
    return url


def _cached_runpod_job_id(execution_id: str) -> str:
    try:
        from django.core.cache import cache

        value = cache.get(_runpod_job_cache_key(execution_id))
    except Exception:
        return ""
    return str(value or "").strip()


def _cache_runpod_job_id(
    execution_id: str,
    job_id: str,
    ttl_seconds: int,
) -> None:
    try:
        from django.core.cache import cache

        cache.set(
            _runpod_job_cache_key(execution_id),
            str(job_id),
            timeout=ttl_seconds,
        )
    except Exception:
        return


def _runpod_job_cache_key(execution_id: str) -> str:
    return f"{RUNPOD_JOB_CACHE_PREFIX}:{_safe_execution_id(execution_id)}"


def _select_scan_ready_video(attachments: list[Any]) -> dict[str, Any] | None:
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        storage_uri = str(attachment.get("storage_uri") or "")
        object_storage = attachment.get("object_storage")
        content_type = str(attachment.get("content_type") or attachment.get("mime_type") or "").lower()
        if (
            attachment.get("purpose") == "blackbox_video"
            and attachment.get("metadata_source") == "canonical_scan_gate"
            and attachment.get("resolution_status") == "scan_ready"
            and attachment.get("status") == "ready"
            and attachment.get("scan_status") == "clean"
            and content_type in {"video/mp4", "video/quicktime"}
            and storage_uri.startswith("s3://")
            and isinstance(object_storage, dict)
            and object_storage.get("resource_type") == "uploaded_file"
            and object_storage.get("status") == "ready"
            and object_storage.get("storage_uri") == storage_uri
        ):
            return attachment
    return None


def _configured_checkpoint() -> Path | None:
    value = os.getenv(VISION_CHECKPOINT_ENV, "").strip()
    return Path(value) if value else None


def _checkpoint_is_complete(checkpoint: Path) -> bool:
    return (checkpoint / "config.json").is_file() and any(
        (checkpoint / name).is_file()
        for name in ("model.safetensors", "pytorch_model.bin")
    )


def _read_scan_ready_video_bytes(attachment: dict[str, Any]) -> bytes | None:
    from chatbot.file_scan_service import read_scan_ready_attachment_bytes

    attachment_id = str(attachment.get("attachment_id") or "")
    storage_uri = str(attachment.get("storage_uri") or "")
    if not attachment_id or not storage_uri:
        return None
    return read_scan_ready_attachment_bytes(
        attachment_id,
        expected_storage_uri=storage_uri,
    )


def _run_vision_subprocess(
    *,
    input_path: Path,
    checkpoint: Path,
    workspace: Path,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    current_python_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(REPOSITORY_ROOT), current_python_path) if value
    )
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ai.vision.run_to_supervisor",
            str(input_path),
            "--checkpoint",
            str(checkpoint),
        ],
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        timeout=_runtime_timeout_seconds(),
        check=False,
    )


def _runtime_timeout_seconds() -> int:
    value = os.getenv("VISION_RUNTIME_TIMEOUT_SECONDS", "").strip()
    try:
        timeout = int(value) if value else DEFAULT_RUNTIME_TIMEOUT_SECONDS
    except ValueError:
        return DEFAULT_RUNTIME_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_RUNTIME_TIMEOUT_SECONDS


def _subprocess_failure_code(completed: subprocess.CompletedProcess[str]) -> str:
    diagnostics = str(completed.stderr or "")
    if "ModuleNotFoundError" in diagnostics or "ImportError" in diagnostics:
        return "vision_dependency_missing"
    if "could not open video" in diagnostics.lower():
        return "vision_media_decode_failed"
    return "vision_execution_failed"


def _single_handoff_path(workspace: Path) -> Path:
    paths = sorted(workspace.glob(HANDOFF_GLOB))
    if len(paths) != 1:
        raise ValueError("Vision did not produce exactly one Supervisor handoff.")
    return paths[0]


def _safe_worker_handoff(worker_payload: Any) -> dict[str, Any]:
    payload = worker_payload if isinstance(worker_payload, dict) else {}
    handoff = payload.get("vision_supervisor_handoff")
    handoff = handoff if isinstance(handoff, dict) else {}
    visual = handoff.get("visual_evidence") if isinstance(handoff.get("visual_evidence"), dict) else {}
    model_analysis = handoff.get("model_analysis") if isinstance(handoff.get("model_analysis"), dict) else {}
    media_summary = handoff.get("media_summary") if isinstance(handoff.get("media_summary"), dict) else {}
    prediction = (
        model_analysis.get("trained_accident_prediction")
        if isinstance(model_analysis.get("trained_accident_prediction"), dict)
        else {}
    )
    qwen = model_analysis.get("qwen") if isinstance(model_analysis.get("qwen"), dict) else {}

    evidence = _safe_evidence(visual.get("evidence_candidates"))
    return {
        "analysis_kind": "accident_evidence",
        "handoff_schema_version": handoff.get("schema_version"),
        "status": "partial",
        "media_summary": _allow_fields(media_summary, ("media_type", "summary", "field_summary")),
        "event_candidates": _safe_event_candidates(handoff.get("event_candidates")),
        "key_frames": _safe_key_frames(visual.get("key_frames")),
        "evidence_candidates": evidence,
        "detected_object_summary": _safe_object_summary(visual.get("detected_object_summary")),
        "trained_accident_prediction": _allow_fields(
            prediction,
            ("label", "score", "requires_review"),
        ),
        "qwen": _allow_fields(
            qwen,
            (
                "valid",
                "summary",
                "predicted_accident_target",
                "accident_target_evidence",
                "collision_moment_visible",
                "accident_situation",
                "scene_conditions",
                "uncertainties",
                "requires_review",
                "error_code",
            ),
        ),
        "not_determined_by_vision": _string_list(handoff.get("not_determined_by_vision")),
        "limitations": _safe_limitations(handoff.get("limitations")),
        "evidence": evidence,
    }


def _safe_event_candidates(value: Any) -> list[dict[str, Any]]:
    return [
        _allow_fields(
            item,
            ("event_candidate_id", "start_sec", "end_sec", "priority_score", "basis"),
        )
        for item in value or []
        if isinstance(item, dict)
    ]


def _safe_key_frames(value: Any) -> list[dict[str, Any]]:
    return [
        _allow_fields(
            item,
            ("frame_id", "timestamp_sec", "frame_role", "selection_reason"),
        )
        for item in value or []
        if isinstance(item, dict)
    ]


def _safe_evidence(value: Any) -> list[dict[str, Any]]:
    return [
        _allow_fields(
            item,
            ("evidence_id", "evidence_type", "timestamp_sec", "object_classes", "score", "score_type"),
        )
        for item in value or []
        if isinstance(item, dict)
    ]


def _safe_object_summary(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): count
        for key, count in value.items()
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0
    }


def _allow_fields(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {field: source.get(field) for field in fields if field in source}


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value or [] if isinstance(item, str) and item.strip()]


def _safe_limitations(value: Any) -> list[str]:
    return [
        item
        for item in _string_list(value)
        if not item.startswith(("/", "\\")) and ":/" not in item and ":\\" not in item
    ]


def _safe_execution_id(value: Any) -> str:
    safe = "".join(character for character in str(value or "") if character.isalnum() or character in "-_")
    return safe[:64] or "run"


def _success(handoff: dict[str, Any]) -> dict[str, Any]:
    evidence = list(handoff.get("evidence") or [])
    return {
        "status": "partial",
        "execution_status": "completed_with_review_required",
        "summary": "영상에서 확인 가능한 증거와 제한사항을 정리했습니다.",
        "structured_result": handoff,
        "evidence": evidence,
        "next_actions": ["review_evidence_with_case_and_law_sources"],
        "limitations": list(handoff.get("limitations") or []),
    }


def _failure(error_code: str) -> dict[str, Any]:
    return {
        "status": "partial",
        "execution_status": "degraded",
        "summary": "영상 증거 분석을 완료하지 못해 재시도 또는 자료 확인이 필요합니다.",
        "structured_result": {
            "analysis_kind": "accident_evidence",
            "error_code": error_code,
            "not_determined_by_vision": [
                "fault_ratio",
                "liable_party",
                "traffic_violation",
                "final_accident_type",
            ],
        },
        "evidence": [],
        "next_actions": ["review_video_analysis_preflight"],
        "limitations": ["Vision result is unavailable; no fault or legal conclusion was produced."],
    }
