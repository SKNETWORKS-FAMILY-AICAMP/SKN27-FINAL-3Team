import ast
import json
import importlib
import os
import sys
import types
import unittest
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ai.vision.build_supervisor_handoff import build_handoff
from ai.vision.category_vlm_config import load_experiment_config
from ai.vision.run_to_supervisor import (
    _checkpoint_files,
    infer_videomae,
    qwen_error_code,
    run,
    select_yolo_model,
)


class VisionRunToSupervisorTest(unittest.TestCase):
    def test_handoff_status_contract_is_complete_partial_or_failed(self):
        for source, expected in (
            ("success", "complete"),
            ("complete", "complete"),
            ("partial", "partial"),
            ("failed", "failed"),
        ):
            with self.subTest(source=source):
                payload = build_handoff({"status": source})[
                    "vision_supervisor_handoff"
                ]
                self.assertEqual(payload["schema_version"], "vision-supervisor-handoff-v1")
                self.assertEqual(payload["status"], expected)

    def test_service_qwen_path_uses_shared_adaptive_retry(self):
        source = Path("ai/vision/run_to_supervisor.py").read_text(encoding="utf-8")

        self.assertIn("adaptive_retry_prompt(last_error)", source)
        self.assertIn("retry_token_limit(last_error)", source)
        self.assertEqual(
            source.count("revision=qwen_revision"),
            2,
        )

    def test_qwen_errors_have_stable_handoff_codes(self):
        self.assertEqual(
            qwen_error_code("json_incomplete:Unterminated string"),
            "vision_qwen_json_incomplete",
        )
        self.assertEqual(
            qwen_error_code("schema_invalid:missing:accident_situation"),
            "vision_qwen_schema_invalid",
        )
        self.assertEqual(
            qwen_error_code("vlm_input_contract:frame_count"),
            "vision_qwen_input_contract",
        )
        self.assertEqual(qwen_error_code("CUDA out of memory"), "vision_qwen_unavailable")

    def test_shared_frame_defaults_are_32(self):
        with patch.dict(os.environ, {}, clear=True):
            experiment = load_experiment_config("car_vs_car")

        self.assertEqual(experiment.frame_count, 32)
        self.assertEqual(experiment.vlm_input_frame_count, 32)
        self.assertEqual(
            experiment.qwen_model_revision,
            "66285546d2b821cf421d4f5eb2576359d3770cd3",
        )
        pipeline_tree = ast.parse(
            Path("ai/vision/pipeline.py").read_text(encoding="utf-8")
        )
        function = next(
            node
            for node in pipeline_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "extract_keyframes"
        )
        self.assertEqual(ast.literal_eval(function.args.defaults[-1]), 32)

    def test_yolo_detection_module_is_not_empty(self):
        with patch.dict(sys.modules, {"ultralytics": types.SimpleNamespace(YOLO=object)}):
            models = importlib.import_module("ai.vision.models")
        self.assertTrue(callable(models.detect_keyframes))

    def test_missing_trained_checkpoint_fails(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                _checkpoint_files(Path(directory))

    def test_videomae_selects_yolo_before_detection_and_details_reach_handoff(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            video, checkpoint = root / "sample.mp4", root / "checkpoint"
            video.touch(); checkpoint.mkdir()
            (checkpoint / "config.json").write_text("{}")
            (checkpoint / "model.safetensors").touch()
            agent_output = {"agent_output": {"status": "success", "summary": "old", "structured_result": {
                "key_frames": [{
                    "frame_id": "frame_1",
                    "frame_order": 1,
                    "frame_path": "frame.jpg",
                    "timestamp_sec": 0.0,
                }]
            }}}
            final_dir, handoff_dir = root / "final", root / "handoff"
            calls = []
            modules = {
                "ai.vision.pipeline": types.SimpleNamespace(extract_keyframes=lambda _, count: (
                    calls.append(("extract", count)) or (root / "keys.json", {})
                )),
                "ai.vision.models": types.SimpleNamespace(detect_keyframes=lambda _, model, confidence: (
                    calls.append(("detect", model, confidence)) or (root / "detections.json", {})
                )),
                "ai.vision.schemas": types.SimpleNamespace(convert_detection_to_agent_output=lambda *_: (root / "agent.json", agent_output)),
                "ai.vision.visualize": types.SimpleNamespace(
                    create_visualizations=lambda *_: (
                        root / "visualizations.json",
                        {"visualizations": []},
                    )
                ),
            }
            video_result = {"clips": [{"top_predictions": [{"label": "car_vs_car", "score": .9}]}]}
            with patch.dict(sys.modules, modules), \
                 patch("ai.vision.merge_analysis.FINAL_OUTPUT_DIR", final_dir), \
                 patch("ai.vision.build_supervisor_handoff.OUTPUT_DIR", handoff_dir), \
                 patch("ai.vision.run_to_supervisor.infer_videomae", side_effect=lambda *_: calls.append("videomae") or video_result), \
                 patch("ai.vision.run_to_supervisor.analyze_qwen", side_effect=lambda _paths, _metadata, _model, count, _device, _revision: (
                     calls.append(("qwen", count)) or {
                         "valid": True, "summary": "collision", "collision_moment_visible": True,
                         "uncertainties": ["occlusion"],
                     }
                 )):
                result = run(video, checkpoint=checkpoint)
            payload = json.loads(result.read_text())["vision_supervisor_handoff"]
            self.assertEqual(calls[:4], [
                "videomae", ("extract", 32), ("detect", "yolov8m.pt", .25), ("qwen", 32)
            ])
            self.assertEqual(payload["model_analysis"]["trained_accident_prediction"]["label"], "car_vs_car")
            self.assertEqual(payload["model_analysis"]["selected_yolo_model"], "yolov8m.pt")
            self.assertEqual(payload["model_analysis"]["qwen"]["uncertainties"], ["occlusion"])
            self.assertEqual(payload["media_summary"]["summary"], "collision")

    def test_korean_videomae_label_routes_to_a_yolo_model(self):
        prediction, model = select_yolo_model(
            {"clips": [{"top_predictions": [{"label": "차대차", "score": 0.9}]}]}
        )

        self.assertEqual(prediction["raw_label"], "차대차")
        self.assertEqual(prediction["label"], "car_vs_car")
        self.assertEqual(model, "yolov8m.pt")

    def test_qwen_failure_is_partial_handoff(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            video, checkpoint = root / "sample.mp4", root / "checkpoint"
            video.touch(); checkpoint.mkdir()
            (checkpoint / "config.json").write_text("{}")
            (checkpoint / "model.safetensors").touch()
            agent_output = {"agent_output": {"status": "success", "summary": "objects detected", "structured_result": {
                "key_frames": [{
                    "frame_id": "frame_1",
                    "frame_order": 1,
                    "frame_path": "frame.jpg",
                    "timestamp_sec": 0.0,
                }]
            }}}
            modules = {
                "ai.vision.pipeline": types.SimpleNamespace(extract_keyframes=lambda *_: (root / "keys.json", {})),
                "ai.vision.models": types.SimpleNamespace(detect_keyframes=lambda *_: (root / "detections.json", {})),
                "ai.vision.schemas": types.SimpleNamespace(convert_detection_to_agent_output=lambda *_: (root / "agent.json", agent_output)),
                "ai.vision.visualize": types.SimpleNamespace(
                    create_visualizations=lambda *_: (
                        root / "visualizations.json",
                        {"visualizations": []},
                    )
                ),
            }
            video_result = {"model_name": "checkpoint", "clips": [{"top_predictions": [{"label": "car_vs_bicycle", "score": .8}]}]}
            with patch.dict(sys.modules, modules), \
                 patch("ai.vision.merge_analysis.FINAL_OUTPUT_DIR", root / "final"), \
                 patch("ai.vision.build_supervisor_handoff.OUTPUT_DIR", root / "handoff"), \
                 patch("ai.vision.run_to_supervisor.infer_videomae", return_value=video_result), \
                 patch("ai.vision.run_to_supervisor.analyze_qwen", side_effect=RuntimeError("model unavailable")):
                result = run(video, checkpoint=checkpoint)
            payload = json.loads(result.read_text())["vision_supervisor_handoff"]
            self.assertEqual(payload["status"], "partial")
            self.assertFalse(payload["model_analysis"]["qwen"]["valid"])
            self.assertTrue(payload["model_analysis"]["qwen"]["requires_review"])
            self.assertEqual(payload["model_analysis"]["qwen"]["error_code"], "vision_qwen_unavailable")
            self.assertNotIn("RuntimeError", json.dumps(payload, ensure_ascii=False))

    def test_handoff_drops_local_paths_and_qwen_exception_text(self):
        handoff = build_handoff(
            {
                "status": "partial",
                "vision_agent_output": {
                    "agent_output": {
                        "structured_result": {
                            "key_frames": [
                                {
                                    "frame_id": "frame_1",
                                    "frame_path": "C:/private/frame.jpg",
                                    "timestamp_sec": 1.2,
                                }
                            ],
                            "evidence_candidates": [
                                {
                                    "evidence_id": "evidence_1",
                                    "source_ref": "C:/private/detection.json",
                                    "frame_path": "C:/private/frame.jpg",
                                }
                            ],
                            "qwen_analysis": {
                                "valid": False,
                                "error": "RuntimeError: C:/private/model",
                            },
                        },
                        "metadata": {"source_path": "C:/private/video.mp4"},
                    }
                },
                "video_understanding": {"model_name": "C:/private/checkpoint"},
            }
        )

        serialized = json.dumps(handoff, ensure_ascii=False)
        self.assertNotIn("C:/private", serialized)
        self.assertNotIn("RuntimeError", serialized)
        self.assertEqual(
            handoff["vision_supervisor_handoff"]["model_analysis"]["qwen"]["error_code"],
            "vision_qwen_unavailable",
        )

    def test_invalid_videomae_category_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            select_yolo_model({"clips": [{"top_predictions": [{"label": "unknown", "score": .7}]}]})

    def test_low_videomae_confidence_requires_review(self):
        prediction, model = select_yolo_model(
            {"clips": [{"top_predictions": [{"label": "car_vs_pedestrian", "score": .4}]}]}
        )
        self.assertEqual(model, "yolo11n.pt")
        self.assertTrue(prediction["requires_review"])

    def test_korean_videomae_label_selects_yolo(self):
        prediction, model = select_yolo_model(
            {"clips": [{"top_predictions": [{"label": "차대보행자", "score": .8}]}]}
        )
        self.assertEqual(prediction["label"], "car_vs_pedestrian")
        self.assertEqual(prediction["raw_label"], "차대보행자")
        self.assertEqual(model, "yolo11n.pt")


def test_auto_device_resolves_to_cpu_in_both_inference_paths(monkeypatch, tmp_path):
    import torch
    from transformers import VideoMAEForVideoClassification, VideoMAEImageProcessor

    from ai.vision.trained_category_classifier import TrainedCategoryClassifier

    class DeviceResolved(Exception):
        pass

    def cpu_only_device(value):
        assert value == "cpu"
        raise DeviceResolved

    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "config.json").write_text("{}", encoding="utf-8")
    (checkpoint / "model.safetensors").write_bytes(b"x")

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch, "device", cpu_only_device)

    with pytest.raises(DeviceResolved):
        infer_videomae(tmp_path / "video.mp4", checkpoint, 32, "auto")
    with pytest.raises(DeviceResolved):
        TrainedCategoryClassifier(checkpoint, device_name="auto")


if __name__ == "__main__":
    unittest.main()
