"""Load the best trained VideoMAE accident classifier once for notebook inference."""

from functools import lru_cache
import json
import os
from pathlib import Path


LABELS = {
    "차대차": "car_vs_car",
    "차대보행자": "car_vs_pedestrian",
    "차대이륜차": "car_vs_motorcycle",
    "차대자전거": "car_vs_bicycle",
    "car_vs_car": "car_vs_car",
    "car_vs_pedestrian": "car_vs_pedestrian",
    "car_vs_motorcycle": "car_vs_motorcycle",
    "car_vs_bicycle": "car_vs_bicycle",
}


def find_best_checkpoint(project_root: Path) -> Path:
    configured = os.getenv("VISION_TRAINED_CLASSIFIER_CHECKPOINT")
    if configured:
        checkpoint = Path(configured).expanduser().resolve()
        if (checkpoint / "config.json").is_file():
            return checkpoint
        raise FileNotFoundError(f"Invalid VISION_TRAINED_CLASSIFIER_CHECKPOINT: {checkpoint}")

    candidates = []
    for config_path in (project_root / "storage/vision/models").rglob("run_config.json"):
        checkpoint = config_path.parent
        if not (checkpoint / "config.json").is_file():
            continue
        if not any((checkpoint / name).is_file() for name in ("model.safetensors", "pytorch_model.bin")):
            continue
        config = json.loads(config_path.read_text(encoding="utf-8"))
        candidates.append((float(config.get("best_val_accuracy", -1)), checkpoint))
    if not candidates:
        raise FileNotFoundError(
            "No trained VideoMAE checkpoint found. Run ai/vision/train_videomae_classifier.py first "
            "or set VISION_TRAINED_CLASSIFIER_CHECKPOINT."
        )
    return max(candidates, key=lambda item: item[0])[1]


class TrainedCategoryClassifier:
    def __init__(self, checkpoint: Path, frame_count: int = 16, device_name: str = "auto"):
        import torch
        from transformers import VideoMAEForVideoClassification, VideoMAEImageProcessor

        self.torch = torch
        self.device = torch.device("cuda" if device_name == "auto" and torch.cuda.is_available() else device_name)
        self.frame_count = frame_count
        self.processor = VideoMAEImageProcessor.from_pretrained(checkpoint)
        self.model = VideoMAEForVideoClassification.from_pretrained(checkpoint).to(self.device).eval()
        self.checkpoint = checkpoint

    @lru_cache(maxsize=512)
    def predict(self, video_path: str) -> dict:
        from ai.vision.train_videomae_classifier import read_video_frames

        frames = read_video_frames(Path(video_path), self.frame_count)
        inputs = {
            key: value.to(self.device)
            for key, value in self.processor(list(frames), return_tensors="pt").items()
        }
        with self.torch.inference_mode():
            probabilities = self.torch.softmax(self.model(**inputs).logits[0], dim=-1)
        index = int(probabilities.argmax())
        raw_label = self.model.config.id2label.get(index, str(index))
        return {
            "label": LABELS.get(raw_label, raw_label),
            "raw_label": raw_label,
            "confidence": round(float(probabilities[index]), 6),
            "checkpoint": str(self.checkpoint),
        }
