"""Run pretrained VideoMAE inference on sampled clip frames.

This is a comparison POC only. VideoMAE adds clip-level action hints to the
final analysis, but it does not replace the accident classifier.
"""
from pathlib import Path
import argparse
import json
from typing import Any

import torch
from PIL import Image

try:
    from transformers import VideoMAEForVideoClassification, VideoMAEImageProcessor
except ImportError as exc:  # pragma: no cover - runtime guidance
    raise SystemExit(
        "Missing dependency: transformers. Install dependencies with: "
        "pip install -r requirements.txt"
    ) from exc


INPUT_DIR = Path("storage/vision/outputs/videomae_inputs")
OUTPUT_DIR = Path("storage/vision/outputs/videomae_results")
DEFAULT_MODEL = "MCG-NJU/videomae-base-finetuned-kinetics"
DEFAULT_TOP_K = 5


def latest_manifest(input_dir: Path) -> Path:
    manifests = sorted(input_dir.glob("videomae_clip_manifest_*.json"))
    if not manifests:
        raise FileNotFoundError(f"No VideoMAE input manifest found under {input_dir}")
    return manifests[-1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_clip_frames(clip: dict[str, Any]) -> list[Image.Image]:
    rows = clip.get("videomae_input", {}).get("frames", [])
    frames: list[Image.Image] = []
    for row in rows:
        frame_path = Path(row.get("frame_path", ""))
        if not frame_path.exists():
            raise FileNotFoundError(f"Missing sampled frame: {frame_path}")
        frames.append(Image.open(frame_path).convert("RGB"))
    if not frames:
        raise ValueError(f"No frames found for clip_id={clip.get('clip_id')}")
    return frames


def move_to_device(inputs: dict[str, torch.Tensor], device: torch.device) -> dict[str, torch.Tensor]:
    return {key: value.to(device) for key, value in inputs.items()}


def infer_clip(
    frames: list[Image.Image],
    processor: VideoMAEImageProcessor,
    model: VideoMAEForVideoClassification,
    device: torch.device,
    top_k: int,
) -> list[dict[str, Any]]:
    inputs = processor(frames, return_tensors="pt")
    inputs = move_to_device(inputs, device)

    with torch.no_grad():
        outputs = model(**inputs)
        probabilities = torch.softmax(outputs.logits, dim=-1)[0]
        k = min(top_k, probabilities.shape[-1])
        scores, indices = torch.topk(probabilities, k=k)

    predictions = []
    for rank, (score, index) in enumerate(zip(scores.tolist(), indices.tolist()), start=1):
        label = model.config.id2label.get(index, str(index))
        predictions.append(
            {
                "rank": rank,
                "label_id": int(index),
                "label": label,
                "score": round(float(score), 6),
            }
        )
    return predictions


def run_inference(
    manifest_path: Path,
    output_dir: Path,
    model_name: str,
    top_k: int,
    device_name: str | None,
) -> Path:
    manifest = load_json(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device(device_name or ("cuda" if torch.cuda.is_available() else "cpu"))
    processor = VideoMAEImageProcessor.from_pretrained(model_name)
    model = VideoMAEForVideoClassification.from_pretrained(model_name).to(device)
    model.eval()

    results = []
    for clip in manifest.get("clips", []):
        frames = load_clip_frames(clip)
        predictions = infer_clip(frames, processor, model, device, top_k)
        result = {
            "clip_id": clip.get("clip_id"),
            "clip_path": clip.get("clip_path"),
            "clip_start_sec": clip.get("clip_start_sec"),
            "clip_end_sec": clip.get("clip_end_sec"),
            "basis": clip.get("basis"),
            "frame_count": len(frames),
            "top_predictions": predictions,
        }
        results.append(result)
        top = predictions[0] if predictions else {"label": "n/a", "score": 0.0}
        print(f"{clip.get('clip_id')}: {top['label']} score={top['score']}")

    output = {
        "schema_version": "videomae-inference-result-v1",
        "source_manifest": manifest_path.as_posix(),
        "model_name": model_name,
        "device": str(device),
        "top_k": top_k,
        "clip_count": len(results),
        "note": "Kinetics pretrained labels are action hints, not accident-type labels.",
        "clips": results,
    }

    source_stem = manifest_path.stem.replace("videomae_clip_manifest_", "")
    output_path = output_dir / f"videomae_results_{source_stem}.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run VideoMAE pretrained inference on sampled clip frames.")
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--model-name", default=DEFAULT_MODEL)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--device", default=None, help="cuda, cpu, or leave empty for auto")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_path = args.manifest or latest_manifest(INPUT_DIR)
    output_path = run_inference(
        manifest_path=manifest_path,
        output_dir=args.output_dir,
        model_name=args.model_name,
        top_k=args.top_k,
        device_name=args.device,
    )
    print(f"manifest_path: {manifest_path}")
    print(f"videomae_result_path: {output_path}")


if __name__ == "__main__":
    main()
