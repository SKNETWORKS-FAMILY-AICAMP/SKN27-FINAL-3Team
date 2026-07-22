from pathlib import Path
from subprocess import TimeoutExpired
from types import SimpleNamespace

from app.services import vision_media_analysis_adapter as adapter


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
