from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ai.vision import runpod_worker as worker


ROOT = Path(__file__).resolve().parents[1]
SIGNED_URL = (
    "https://private-bucket.s3.ap-northeast-2.amazonaws.com/video.mp4"
    "?X-Amz-Signature=private"
)


def _request(**overrides: Any) -> dict[str, Any]:
    request = {
        "schema_version": "vision-runpod-request-v1",
        "execution_id": "exec_worker_1",
        "attachment_id": "att_worker_1",
        "video_url": SIGNED_URL,
        "content_type": "video/mp4",
    }
    request.update(overrides)
    return request


def _raw_handoff() -> dict[str, Any]:
    return {
        "vision_supervisor_handoff": {
            "schema_version": "vision-supervisor-handoff-v1",
            "status": "partial",
            "source": {
                "source_video": "C:/private/video.mp4",
                "video_url": SIGNED_URL,
            },
            "media_summary": {
                "media_type": "video",
                "summary": "worker evidence summary",
                "field_summary": {"weather": "clear"},
            },
            "event_candidates": [
                {
                    "event_candidate_id": "event_1",
                    "start_sec": 1.0,
                    "end_sec": 2.0,
                    "basis": "motion",
                    "private_path": "C:/private/event.json",
                }
            ],
            "visual_evidence": {
                "key_frames": [
                    {
                        "frame_id": "frame_1",
                        "timestamp_sec": 1.2,
                        "frame_role": "collision_candidate",
                        "frame_path": "C:/private/frame.jpg",
                    }
                ],
                "evidence_candidates": [
                    {
                        "evidence_id": "evidence_1",
                        "evidence_type": "object",
                        "timestamp_sec": 1.2,
                        "object_classes": ["car"],
                        "score": 0.8,
                        "source_ref": SIGNED_URL,
                    }
                ],
                "detected_object_summary": {"car": 1},
            },
            "model_analysis": {
                "trained_accident_prediction": {
                    "label": "car_vs_car",
                    "score": 0.8,
                    "requires_review": False,
                    "checkpoint": "C:/private/checkpoint",
                },
                "qwen": {
                    "valid": False,
                    "error_code": "vision_qwen_unavailable",
                    "error": f"failed at {SIGNED_URL}",
                },
            },
            "not_determined_by_vision": [
                "fault_ratio",
                "liable_party",
                "traffic_violation",
                "final_accident_type",
            ],
            "limitations": [
                "Human review is required.",
                "C:/private/diagnostic",
                SIGNED_URL,
            ],
        }
    }


def test_worker_downloads_runs_pipeline_sanitizes_and_deletes_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspaces: list[Path] = []

    def fake_download(request: dict[str, Any], destination: Path) -> None:
        assert request["video_url"] == SIGNED_URL
        workspaces.append(destination.parent)
        destination.write_bytes(b"video")

    def fake_pipeline(input_path: Path) -> dict[str, Any]:
        assert input_path.read_bytes() == b"video"
        return _raw_handoff()

    monkeypatch.setenv(
        "RUNPOD_VISION_ALLOWED_HOSTS",
        "*.s3.ap-northeast-2.amazonaws.com",
    )
    monkeypatch.setattr(worker, "_download_video", fake_download)
    monkeypatch.setattr(worker, "_run_pipeline", fake_pipeline)

    result = worker.run_worker_job(_request())

    assert result["vision_supervisor_handoff"]["schema_version"] == (
        "vision-supervisor-handoff-v1"
    )
    assert result["vision_supervisor_handoff"]["visual_evidence"]["key_frames"] == [
        {
            "frame_id": "frame_1",
            "timestamp_sec": 1.2,
            "frame_role": "collision_candidate",
        }
    ]
    assert result["vision_supervisor_handoff"]["visual_evidence"][
        "evidence_candidates"
    ][0]["evidence_id"] == "evidence_1"
    assert "C:/" not in repr(result)
    assert "X-Amz-Signature" not in repr(result)
    assert "checkpoint" not in repr(result).lower()
    assert workspaces and not workspaces[0].exists()


def test_worker_failure_returns_safe_code_and_deletes_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspaces: list[Path] = []

    def fake_download(_request: dict[str, Any], destination: Path) -> None:
        workspaces.append(destination.parent)
        destination.write_bytes(b"video")

    def failing_pipeline(_input_path: Path) -> dict[str, Any]:
        raise RuntimeError(f"private failure {SIGNED_URL} C:/private/model")

    monkeypatch.setenv(
        "RUNPOD_VISION_ALLOWED_HOSTS",
        "private-bucket.s3.ap-northeast-2.amazonaws.com",
    )
    monkeypatch.setattr(worker, "_download_video", fake_download)
    monkeypatch.setattr(worker, "_run_pipeline", failing_pipeline)

    result = worker.run_worker_job(_request())

    assert result == {
        "vision_worker_error": {
            "error_code": "vision_worker_execution_failed",
        }
    }
    assert SIGNED_URL not in repr(result)
    assert "C:/" not in repr(result)
    assert workspaces and not workspaces[0].exists()


@pytest.mark.parametrize(
    "request_payload",
    [
        {},
        _request(schema_version="unknown"),
        _request(execution_id="../unsafe"),
        _request(attachment_id=""),
        _request(content_type="application/octet-stream"),
        _request(video_url="http://private.example/video.mp4"),
        _request(video_url="https://user@private.example/video.mp4"),
        _request(video_url="https://private.example/video.mp4#fragment"),
        _request(video_url="https://evil.example/video.mp4"),
    ],
)
def test_worker_rejects_invalid_request_without_downloading(
    monkeypatch: pytest.MonkeyPatch,
    request_payload: dict[str, Any],
) -> None:
    monkeypatch.setenv(
        "RUNPOD_VISION_ALLOWED_HOSTS",
        "private-bucket.s3.ap-northeast-2.amazonaws.com",
    )
    monkeypatch.setattr(
        worker,
        "_download_video",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid request downloaded")
        ),
    )

    result = worker.run_worker_job(request_payload)

    assert result == {
        "vision_worker_error": {
            "error_code": "vision_worker_invalid_request",
        }
    }
    assert SIGNED_URL not in repr(result)


def test_worker_requires_explicit_allowed_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RUNPOD_VISION_ALLOWED_HOSTS", raising=False)

    result = worker.run_worker_job(_request())

    assert result["vision_worker_error"]["error_code"] == (
        "vision_worker_invalid_request"
    )


def test_handler_reads_only_the_runpod_input_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        worker,
        "run_worker_job",
        lambda request: captured.append(request) or {"status": "ok"},
    )

    result = worker.handler(
        {
            "id": "runpod_job_1",
            "input": _request(),
            "private": SIGNED_URL,
        }
    )

    assert result == {"status": "ok"}
    assert captured == [_request()]


class _FakeResponse:
    def __init__(
        self,
        chunks: list[bytes],
        *,
        content_type: str = "video/mp4",
        content_length: int | None = None,
    ):
        self._chunks = list(chunks)
        self.headers = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


def test_download_video_streams_valid_content_to_destination(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    response = _FakeResponse(
        [b"vid", b"eo", b""],
        content_length=5,
    )
    monkeypatch.setattr(worker.urllib.request, "urlopen", lambda *_args, **_kwargs: response)
    monkeypatch.setenv("RUNPOD_VISION_MAX_DOWNLOAD_BYTES", "10")
    destination = tmp_path / "input.mp4"

    worker._download_video(_request(), destination)

    assert destination.read_bytes() == b"video"


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (
            _FakeResponse([b""], content_type="text/plain", content_length=0),
            "vision_worker_download_failed",
        ),
        (
            _FakeResponse([b""], content_length=11),
            "vision_worker_media_too_large",
        ),
        (
            _FakeResponse([b"123456", b"789012", b""]),
            "vision_worker_media_too_large",
        ),
    ],
)
def test_download_video_rejects_mime_and_size(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    response: _FakeResponse,
    expected_code: str,
) -> None:
    monkeypatch.setattr(worker.urllib.request, "urlopen", lambda *_args, **_kwargs: response)
    monkeypatch.setenv("RUNPOD_VISION_MAX_DOWNLOAD_BYTES", "10")

    with pytest.raises(worker.VisionWorkerError) as raised:
        worker._download_video(_request(), tmp_path / "input.mp4")

    assert raised.value.code == expected_code
    assert SIGNED_URL not in repr(raised.value)


def test_download_network_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        worker.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TimeoutError(f"timeout {SIGNED_URL}")
        ),
    )

    with pytest.raises(worker.VisionWorkerError) as raised:
        worker._download_video(_request(), tmp_path / "input.mp4")

    assert raised.value.code == "vision_worker_download_failed"
    assert SIGNED_URL not in repr(raised.value)


def test_invalid_pipeline_handoff_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "RUNPOD_VISION_ALLOWED_HOSTS",
        "private-bucket.s3.ap-northeast-2.amazonaws.com",
    )
    monkeypatch.setattr(
        worker,
        "_download_video",
        lambda _request, destination: destination.write_bytes(b"video"),
    )
    monkeypatch.setattr(
        worker,
        "_run_pipeline",
        lambda _path: {
            "vision_supervisor_handoff": {
                "schema_version": "unknown",
                "private": SIGNED_URL,
            }
        },
    )

    result = worker.run_worker_job(_request())

    assert result == {
        "vision_worker_error": {
            "error_code": "vision_worker_invalid_handoff",
        }
    }


def test_runpod_worker_image_keeps_models_and_secrets_out_of_the_image() -> None:
    dockerfile = (
        ROOT / "deploy" / "runpod-vision" / "Dockerfile"
    ).read_text(encoding="utf-8")
    readme = (
        ROOT / "deploy" / "runpod-vision" / "README.md"
    ).read_text(encoding="utf-8")
    requirements = (
        ROOT / "requirements-vision-runpod.txt"
    ).read_text(encoding="utf-8")

    assert "runpod~=1.7.6" in requirements
    assert "python -u -m ai.vision.runpod_worker" in dockerfile
    assert "requirements-vision-runpod.txt" in dockerfile
    assert "COPY ai " in dockerfile
    assert "COPY app " in dockerfile
    assert "COPY models" not in dockerfile
    assert "RUNPOD_API_KEY=" not in dockerfile
    assert "VISION_TRAINED_CLASSIFIER_CHECKPOINT=" not in dockerfile
    assert "workersMin=0" in readme
    assert "workersMax=1" in readme
    assert "Network Volume" in readme
    assert "restricted" in readme
    assert "비식별" in readme
