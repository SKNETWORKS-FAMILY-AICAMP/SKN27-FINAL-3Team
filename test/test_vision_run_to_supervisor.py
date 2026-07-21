import json
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ai.vision.run_to_supervisor import _checkpoint_files, run


class VisionRunToSupervisorTest(unittest.TestCase):
    def test_missing_trained_checkpoint_fails(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                _checkpoint_files(Path(directory))

    def test_trained_prediction_and_qwen_reach_handoff(self):
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
            modules = {
                "ai.vision.pipeline": types.SimpleNamespace(extract_keyframes=lambda *_: (root / "keys.json", {})),
                "ai.vision.models": types.SimpleNamespace(detect_keyframes=lambda *_: (root / "detections.json", {})),
                "ai.vision.schemas": types.SimpleNamespace(convert_detection_to_agent_output=lambda *_: (root / "agent.json", agent_output)),
                "ai.vision.merge_analysis": types.SimpleNamespace(FINAL_OUTPUT_DIR=final_dir, output_name=lambda _: "final.json",
                    build_final_analysis=lambda agent, video_result: {"vision_agent_output": agent, "video_understanding": video_result}),
                "ai.vision.build_supervisor_handoff": types.SimpleNamespace(OUTPUT_DIR=handoff_dir, write_handoff=self._handoff),
            }
            video_result = {"clips": [{"top_predictions": [{"label": "car_vs_car", "score": .9}]}]}
            with patch.dict(sys.modules, modules), \
                 patch("ai.vision.run_to_supervisor.infer_videomae", return_value=video_result), \
                 patch("ai.vision.run_to_supervisor.analyze_qwen", return_value={"valid": True, "summary": "collision"}):
                result = run(video, checkpoint=checkpoint)
            payload = json.loads(result.read_text())
            self.assertEqual(payload["prediction"]["label"], "car_vs_car")
            self.assertEqual(payload["summary"], "collision")

    @staticmethod
    def _handoff(final_path, output_dir):
        data = json.loads(final_path.read_text())
        agent = data["vision_agent_output"]["agent_output"]
        output_dir.mkdir(parents=True)
        output = output_dir / "handoff.json"
        output.write_text(json.dumps({"prediction": agent["structured_result"]["trained_model_prediction"], "summary": agent["summary"]}))
        return output


if __name__ == "__main__":
    unittest.main()
