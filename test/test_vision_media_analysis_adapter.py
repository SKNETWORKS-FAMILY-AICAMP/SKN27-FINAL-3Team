from pathlib import Path
from subprocess import TimeoutExpired
from types import SimpleNamespace

import pytest

from app.services import vision_media_analysis_adapter as adapter
from app.services.runpod_vision_client import RunPodVisionError, RunPodVisionResult


SIGNED_URL = (
    "https://private-bucket.s3.ap-northeast-2.amazonaws.com/video.mp4"
    "?X-Amz-Signature=private"
)


def _canonical_video_input() -> dict:
    return {
        "attachments": [
            {
                "attachment_id": "att_video_1",
                "purpose": "blackbox_video",
                "content_type": "video/mp4",
                "metadata_source": "canonical_scan_gate",
                "resolution_status": "scan_ready",
                "status": "ready",
                "scan_status": "clean",
                "storage_uri": "s3://uploads/att_video_1.mp4",
                "object_storage": {
                    "resource_type": "uploaded_file",
                    "status": "ready",
                    "storage_uri": "s3://uploads/att_video_1.mp4",
                    "provider": "s3",
                    "bucket": "private-bucket",
                    "key": "canonical/uploads/att_video_1.mp4",
                },
            }
        ]
    }


def _write_safe_handoff(*, input_path: Path, checkpoint: Path, workspace: Path):
    assert input_path == workspace / "input.mp4"
    assert input_path.read_bytes() == b"video"
    assert checkpoint == Path("C:/models/checkpoint")
    output = workspace / "storage" / "vision" / "outputs" / "supervisor_handoff"
    output.mkdir(parents=True)
    (output / "handoff.json").write_text(
        """{
          "vision_supervisor_handoff": {
            "schema_version": "vision-supervisor-handoff-v1",
            "status": "partial",
            "source": {"source_video": "C:/private/video.mp4"},
            "media_summary": {"media_type": "video", "summary": "evidence summary"},
            "event_candidates": [{"event_candidate_id": "event_1", "start_sec": 1.0, "end_sec": 2.0}],
            "visual_evidence": {
              "key_frames": [{"frame_id": "frame_1", "timestamp_sec": 1.2, "frame_path": "C:/private/frame.jpg"}],
              "evidence_candidates": [{"evidence_id": "evidence_1", "evidence_type": "object", "source_ref": "C:/private/result.json", "timestamp_sec": 1.2, "object_classes": ["car"], "score": 0.8}],
              "detected_object_summary": {"car": 1}
            },
            "model_analysis": {
              "trained_accident_prediction": {"label": "car_vs_car", "score": 0.9},
              "qwen": {"valid": false, "error_code": "vision_qwen_unavailable", "error": "RuntimeError: C:/private/model"}
            },
            "not_determined_by_vision": ["fault_ratio", "liable_party"],
            "limitations": ["Human review is required.", "C:/private/diagnostic"]
          }
        }""",
        encoding="utf-8",
    )
    return SimpleNamespace(returncode=0, stderr="")


def test_adapter_runs_in_an_execution_scoped_workspace_and_returns_partial(monkeypatch) -> None:
    workspaces: list[Path] = []

    def write_handoff(**kwargs):
        workspaces.append(kwargs["workspace"])
        return _write_safe_handoff(**kwargs)

    monkeypatch.setenv("VISION_TRAINED_CLASSIFIER_CHECKPOINT", "C:/models/checkpoint")
    monkeypatch.setattr(adapter, "_read_scan_ready_video_bytes", lambda _attachment: b"video")
    monkeypatch.setattr(adapter, "_checkpoint_is_complete", lambda _path: True)
    monkeypatch.setattr(adapter, "_run_vision_subprocess", write_handoff)

    result = adapter.run_vision_media_analysis(
        _canonical_video_input(),
        {"execution_id": "exec_vision_1"},
    )

    assert result["status"] == "partial"
    assert result["structured_result"]["analysis_kind"] == "accident_evidence"
    assert result["structured_result"]["not_determined_by_vision"] == ["fault_ratio", "liable_party"]
    assert result["evidence"] == [
        {
            "evidence_id": "evidence_1",
            "evidence_type": "object",
            "timestamp_sec": 1.2,
            "object_classes": ["car"],
            "score": 0.8,
        }
    ]
    assert result["limitations"] == ["Human review is required."]
    assert "C:/" not in repr(result)
    assert workspaces and not workspaces[0].exists()


def test_missing_checkpoint_returns_a_stable_failure_without_path(monkeypatch) -> None:
    monkeypatch.delenv("VISION_TRAINED_CLASSIFIER_CHECKPOINT", raising=False)

    result = adapter.run_vision_media_analysis(
        _canonical_video_input(),
        {"execution_id": "exec_vision_2"},
    )

    assert result["status"] == "partial"
    assert result["structured_result"]["error_code"] == "vision_checkpoint_missing"
    assert "checkpoint" not in result["summary"].lower()


def test_noncanonical_video_is_rejected_before_storage_is_read(monkeypatch) -> None:
    read_calls: list[dict] = []
    invalid = _canonical_video_input()
    invalid["attachments"][0]["scan_status"] = "pending"
    monkeypatch.setattr(adapter, "_read_scan_ready_video_bytes", lambda attachment: read_calls.append(attachment))

    result = adapter.run_vision_media_analysis(invalid, {"execution_id": "exec_vision_3"})

    assert result["structured_result"]["error_code"] == "attachment_not_scan_ready"
    assert read_calls == []


def test_subprocess_timeout_uses_a_stable_failure(monkeypatch) -> None:
    monkeypatch.setenv("VISION_TRAINED_CLASSIFIER_CHECKPOINT", "C:/models/checkpoint")
    monkeypatch.setattr(adapter, "_read_scan_ready_video_bytes", lambda _attachment: b"video")
    monkeypatch.setattr(adapter, "_checkpoint_is_complete", lambda _path: True)
    monkeypatch.setattr(
        adapter,
        "_run_vision_subprocess",
        lambda **_kwargs: (_ for _ in ()).throw(TimeoutExpired("vision", 180)),
    )

    result = adapter.run_vision_media_analysis(
        _canonical_video_input(),
        {"execution_id": "exec_vision_4"},
    )

    assert result["structured_result"]["error_code"] == "vision_execution_timeout"


def test_subprocess_video_decode_failure_uses_a_stable_failure(monkeypatch) -> None:
    monkeypatch.setenv("VISION_TRAINED_CLASSIFIER_CHECKPOINT", "C:/models/checkpoint")
    monkeypatch.setattr(adapter, "_read_scan_ready_video_bytes", lambda _attachment: b"video")
    monkeypatch.setattr(adapter, "_checkpoint_is_complete", lambda _path: True)
    monkeypatch.setattr(
        adapter,
        "_run_vision_subprocess",
        lambda **_kwargs: SimpleNamespace(
            returncode=1,
            stderr="RuntimeError: Could not open video: C:/private/input.mp4",
        ),
    )

    result = adapter.run_vision_media_analysis(
        _canonical_video_input(),
        {"execution_id": "exec_vision_5"},
    )

    assert result["structured_result"]["error_code"] == "vision_media_decode_failed"
    assert "C:/" not in repr(result)


def _remote_worker_output() -> dict:
    return {
        "vision_supervisor_handoff": {
            "schema_version": "vision-supervisor-handoff-v1",
            "status": "partial",
            "source": {"source_video": "C:/private/video.mp4"},
            "media_summary": {
                "media_type": "video",
                "summary": "remote evidence summary",
            },
            "event_candidates": [
                {
                    "event_candidate_id": "event_remote_1",
                    "start_sec": 2.0,
                    "end_sec": 3.0,
                }
            ],
            "visual_evidence": {
                "key_frames": [
                    {
                        "frame_id": "frame_remote_1",
                        "timestamp_sec": 2.5,
                        "frame_path": "C:/private/frame.jpg",
                    }
                ],
                "evidence_candidates": [
                    {
                        "evidence_id": "evidence_remote_1",
                        "evidence_type": "object",
                        "timestamp_sec": 2.5,
                        "object_classes": ["car"],
                        "score": 0.75,
                        "source_ref": SIGNED_URL,
                    }
                ],
                "detected_object_summary": {"car": 1},
            },
            "model_analysis": {
                "trained_accident_prediction": {
                    "label": "car_vs_car",
                    "score": 0.82,
                    "requires_review": False,
                },
                "qwen": {
                    "valid": False,
                    "error_code": "vision_qwen_unavailable",
                    "error": SIGNED_URL,
                },
            },
            "not_determined_by_vision": ["fault_ratio", "liable_party"],
            "limitations": ["Human review is required.", SIGNED_URL, "C:/private/error"],
        }
    }


def test_runpod_provider_bypasses_local_checkpoint_and_caches_submitted_job(
    monkeypatch,
) -> None:
    captured: dict = {}
    cached: list[tuple[str, str, int]] = []

    class FakeClient:
        def run(self, request, *, existing_job_id="", on_job_submitted=None):
            captured["request"] = request
            captured["existing_job_id"] = existing_job_id
            assert on_job_submitted is not None
            on_job_submitted("job_remote_1")
            return RunPodVisionResult(
                job_id="job_remote_1",
                output=_remote_worker_output(),
            )

    monkeypatch.setenv("VISION_RUNTIME_PROVIDER", "runpod")
    monkeypatch.setenv("RUNPOD_API_KEY", "runpod-private-key")
    monkeypatch.setenv("RUNPOD_VISION_ENDPOINT_ID", "endpoint_123")
    monkeypatch.setenv("RUNPOD_VISION_TIMEOUT_SECONDS", "600")
    monkeypatch.setattr(
        adapter,
        "_configured_checkpoint",
        lambda: (_ for _ in ()).throw(AssertionError("local checkpoint used")),
    )
    monkeypatch.setattr(
        adapter,
        "_read_scan_ready_video_bytes",
        lambda _attachment: (_ for _ in ()).throw(AssertionError("local bytes read")),
    )
    monkeypatch.setattr(
        adapter,
        "_presign_runpod_video",
        lambda _attachment, *, timeout_seconds: SIGNED_URL,
    )
    monkeypatch.setattr(adapter, "_new_runpod_client", lambda _config: FakeClient())
    monkeypatch.setattr(adapter, "_cached_runpod_job_id", lambda _execution_id: "")
    monkeypatch.setattr(
        adapter,
        "_cache_runpod_job_id",
        lambda execution_id, job_id, ttl_seconds: cached.append(
            (execution_id, job_id, ttl_seconds)
        ),
    )

    result = adapter.run_vision_media_analysis(
        _canonical_video_input(),
        {"execution_id": "exec_remote_1"},
    )

    assert captured["existing_job_id"] == ""
    assert captured["request"] == {
        "schema_version": "vision-runpod-request-v1",
        "execution_id": "exec_remote_1",
        "attachment_id": "att_video_1",
        "video_url": SIGNED_URL,
        "content_type": "video/mp4",
    }
    assert cached == [("exec_remote_1", "job_remote_1", 900)]
    assert result["structured_result"]["handoff_schema_version"] == "vision-supervisor-handoff-v1"
    assert result["evidence"][0]["evidence_id"] == "evidence_remote_1"
    assert SIGNED_URL not in repr(result)
    assert "C:/" not in repr(result)
    assert "runpod-private-key" not in repr(result)


def test_runpod_provider_reuses_cached_job_id(monkeypatch) -> None:
    captured: dict = {}

    class FakeClient:
        def run(self, request, *, existing_job_id="", on_job_submitted=None):
            captured["request"] = request
            captured["existing_job_id"] = existing_job_id
            captured["callback"] = on_job_submitted
            return RunPodVisionResult(
                job_id=existing_job_id,
                output=_remote_worker_output(),
            )

    monkeypatch.setenv("VISION_RUNTIME_PROVIDER", "runpod")
    monkeypatch.setenv("RUNPOD_API_KEY", "runpod-private-key")
    monkeypatch.setenv("RUNPOD_VISION_ENDPOINT_ID", "endpoint_123")
    monkeypatch.setattr(
        adapter,
        "_presign_runpod_video",
        lambda _attachment, *, timeout_seconds: SIGNED_URL,
    )
    monkeypatch.setattr(adapter, "_new_runpod_client", lambda _config: FakeClient())
    monkeypatch.setattr(
        adapter,
        "_cached_runpod_job_id",
        lambda _execution_id: "job_existing",
    )
    monkeypatch.setattr(
        adapter,
        "_cache_runpod_job_id",
        lambda *_args: (_ for _ in ()).throw(AssertionError("job recached")),
    )

    result = adapter.run_vision_media_analysis(
        _canonical_video_input(),
        {"execution_id": "exec_remote_retry"},
    )

    assert result["status"] == "partial"
    assert captured["existing_job_id"] == "job_existing"
    assert captured["callback"] is not None


@pytest.mark.parametrize(
    "error_code",
    [
        "vision_remote_execution_failed",
        "vision_remote_cancelled",
        "vision_remote_timeout",
        "vision_remote_unavailable",
        "vision_remote_invalid_response",
    ],
)
def test_runpod_provider_preserves_stable_remote_error(
    monkeypatch,
    error_code: str,
) -> None:
    class FailingClient:
        def run(self, *_args, **_kwargs):
            raise RunPodVisionError(error_code)

    monkeypatch.setenv("VISION_RUNTIME_PROVIDER", "runpod")
    monkeypatch.setenv("RUNPOD_API_KEY", "runpod-private-key")
    monkeypatch.setenv("RUNPOD_VISION_ENDPOINT_ID", "endpoint_123")
    monkeypatch.setattr(
        adapter,
        "_presign_runpod_video",
        lambda _attachment, *, timeout_seconds: SIGNED_URL,
    )
    monkeypatch.setattr(adapter, "_new_runpod_client", lambda _config: FailingClient())
    monkeypatch.setattr(adapter, "_cached_runpod_job_id", lambda _execution_id: "")

    result = adapter.run_vision_media_analysis(
        _canonical_video_input(),
        {"execution_id": "exec_remote_failure"},
    )

    assert result["structured_result"]["error_code"] == error_code
    assert "runpod-private-key" not in repr(result)
    assert SIGNED_URL not in repr(result)


def test_runpod_presign_requires_s3_https_and_sufficient_ttl(monkeypatch) -> None:
    calls: list[tuple[dict, int]] = []

    def fake_presign(reference, *, ttl_seconds):
        calls.append((reference, ttl_seconds))
        return {
            "status": "ready",
            "provider": "s3",
            "url": SIGNED_URL,
            "ttl_seconds": ttl_seconds,
        }

    monkeypatch.setattr(adapter, "presign_get", fake_presign)

    attachment = _canonical_video_input()["attachments"][0]
    url = adapter._presign_runpod_video(attachment, timeout_seconds=600)

    assert url == SIGNED_URL
    assert calls == [(attachment["object_storage"], 660)]


@pytest.mark.parametrize(
    "presign_result",
    [
        {
            "status": "ready",
            "provider": "mock_s3",
            "url": "mock-s3://private/video?ttl=660",
            "ttl_seconds": 660,
        },
        {
            "status": "ready",
            "provider": "s3",
            "url": "http://private.example/video?signature=private",
            "ttl_seconds": 660,
        },
        {
            "status": "ready",
            "provider": "s3",
            "url": "https://user@private.example/video?signature=private",
            "ttl_seconds": 660,
        },
        {
            "status": "ready",
            "provider": "s3",
            "url": "https://private.example/video?signature=private#fragment",
            "ttl_seconds": 660,
        },
        {
            "status": "ready",
            "provider": "s3",
            "url": SIGNED_URL,
            "ttl_seconds": 599,
        },
        {
            "status": "unavailable",
            "provider": "s3",
            "reason": "private provider detail",
        },
    ],
)
def test_invalid_runpod_presign_is_remote_unavailable(
    monkeypatch,
    presign_result: dict,
) -> None:
    monkeypatch.setattr(adapter, "presign_get", lambda *_args, **_kwargs: presign_result)
    attachment = _canonical_video_input()["attachments"][0]

    with pytest.raises(RunPodVisionError) as raised:
        adapter._presign_runpod_video(attachment, timeout_seconds=600)

    assert raised.value.code == "vision_remote_unavailable"
    assert SIGNED_URL not in repr(raised.value)


def test_unknown_runtime_provider_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("VISION_RUNTIME_PROVIDER", "jupyter")

    result = adapter.run_vision_media_analysis(
        _canonical_video_input(),
        {"execution_id": "exec_unknown_provider"},
    )

    assert result["structured_result"]["error_code"] == "vision_remote_unavailable"
    assert "jupyter" not in repr(result)
