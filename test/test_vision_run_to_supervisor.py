import json
import importlib
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ai.vision.run_to_supervisor import _checkpoint_files, run, select_yolo_model


class VisionRunToSupervisorTest(unittest.TestCase):
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
                "key_frames": [{"frame_path": "frame.jpg"}]
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
            }
            video_result = {"clips": [{"top_predictions": [{"label": "car_vs_car", "score": .9}]}]}
            with patch.dict(sys.modules, modules), \
                 patch("ai.vision.merge_analysis.FINAL_OUTPUT_DIR", final_dir), \
                 patch("ai.vision.build_supervisor_handoff.OUTPUT_DIR", handoff_dir), \
                 patch("ai.vision.run_to_supervisor.infer_videomae", side_effect=lambda *_: calls.append("videomae") or video_result), \
                 patch("ai.vision.run_to_supervisor.analyze_qwen", side_effect=lambda _, __, count, ___: (
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

    def test_qwen_failure_is_partial_handoff(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            video, checkpoint = root / "sample.mp4", root / "checkpoint"
            video.touch(); checkpoint.mkdir()
            (checkpoint / "config.json").write_text("{}")
            (checkpoint / "model.safetensors").touch()
            agent_output = {"agent_output": {"status": "success", "summary": "objects detected", "structured_result": {
                "key_frames": [{"frame_path": "frame.jpg"}]
            }}}
            modules = {
                "ai.vision.pipeline": types.SimpleNamespace(extract_keyframes=lambda *_: (root / "keys.json", {})),
                "ai.vision.models": types.SimpleNamespace(detect_keyframes=lambda *_: (root / "detections.json", {})),
                "ai.vision.schemas": types.SimpleNamespace(convert_detection_to_agent_output=lambda *_: (root / "agent.json", agent_output)),
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
            self.assertIn("RuntimeError", payload["model_analysis"]["qwen"]["error"])

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


if __name__ == "__main__":
    unittest.main()
