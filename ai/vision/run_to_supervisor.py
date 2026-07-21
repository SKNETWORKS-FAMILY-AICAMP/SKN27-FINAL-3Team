"""Run trained VideoMAE + YOLO + Qwen and create a Supervisor handoff."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _checkpoint_files(checkpoint: Path) -> tuple[Path, Path]:
    config = checkpoint / "config.json"
    weights = next(
        (checkpoint / name for name in ("model.safetensors", "pytorch_model.bin") if (checkpoint / name).is_file()),
        checkpoint / "model.safetensors",
    )
    if not config.is_file() or not weights.is_file():
        raise FileNotFoundError(
            f"Trained VideoMAE checkpoint is incomplete: {checkpoint} "
            "(config.json and model.safetensors/pytorch_model.bin are required)"
        )
    return config, weights


def infer_videomae(video: Path, checkpoint: Path, frame_count: int, device_name: str) -> dict[str, Any]:
    _checkpoint_files(checkpoint)
    import torch
    from transformers import VideoMAEForVideoClassification, VideoMAEImageProcessor

    from ai.vision.train_videomae_classifier import read_video_frames

    device = torch.device("cuda" if device_name == "auto" and torch.cuda.is_available() else device_name)
    frames = read_video_frames(video, frame_count)
    processor = VideoMAEImageProcessor.from_pretrained(checkpoint)
    model = VideoMAEForVideoClassification.from_pretrained(checkpoint).to(device).eval()
    inputs = {key: value.to(device) for key, value in processor(list(frames), return_tensors="pt").items()}
    with torch.inference_mode():
        probabilities = torch.softmax(model(**inputs).logits[0], dim=-1)
    scores, indices = torch.topk(probabilities, min(4, probabilities.numel()))
    predictions = [
        {"label": model.config.id2label.get(int(index), str(int(index))), "score": round(float(score), 6)}
        for score, index in zip(scores.cpu(), indices.cpu())
    ]
    del model, inputs
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return {
        "model_name": str(checkpoint),
        "device": str(device),
        "source_manifest": None,
        "clip_count": 1,
        "clips": [{
            "clip_id": video.stem,
            "clip_path": str(video),
            "frame_count": len(frames),
            "basis": "trained_accident_classifier",
            "top_predictions": predictions,
        }],
    }


def _json_object(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Qwen response did not contain a JSON object")
    return json.loads(text[start : end + 1])


def analyze_qwen(frame_paths: list[str], model_name: str, max_frames: int, device_name: str) -> dict[str, Any]:
    if not frame_paths:
        return {
            "valid": False,
            "error": "No key frames available",
            "requires_review": True,
            "limitations": ["Qwen analysis was not available because no key frames were extracted."],
        }
    import torch
    from qwen_vl_utils import process_vision_info
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    selected = frame_paths[:max_frames]
    prompt = (
        "Analyze these accident-video key frames. Return JSON only with keys: summary, "
        "visible_objects, predicted_accident_target, accident_target_evidence, accident_visible, "
        "collision_moment_visible, accident_situation, scene_conditions, uncertainties. "
        "predicted_accident_target must be one of car_vs_car, pedestrian, motorcycle, bicycle, uncertain."
    )
    content = [{"type": "image", "image": str(Path(path).resolve()), "max_pixels": 640 * 360} for path in selected]
    content.append({"type": "text", "text": prompt})
    messages = [{"role": "user", "content": content}]
    processor = AutoProcessor.from_pretrained(model_name)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_name, torch_dtype="auto", device_map="auto" if device_name == "auto" else device_name
    ).eval()
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(text=[text], images=image_inputs, videos=video_inputs, padding=True, return_tensors="pt").to(model.device)
    with torch.inference_mode():
        generated = model.generate(**inputs, max_new_tokens=256, do_sample=False, use_cache=False)
    trimmed = [output[len(source) :] for source, output in zip(inputs.input_ids, generated)]
    raw = processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
    result = _json_object(raw)
    result.update({"valid": True, "model_name": model_name, "frame_count": len(selected)})
    del model, inputs
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return result


def select_yolo_model(
    videomae: dict[str, Any], override: str | None = None, min_confidence: float = 0.5
) -> tuple[dict[str, Any], str]:
    from ai.vision.category_vlm_config import BEST_YOLO_MODELS

    try:
        prediction = videomae["clips"][0]["top_predictions"][0]
        label = str(prediction["label"])
        score = float(prediction["score"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("VideoMAE did not return a valid top prediction") from exc
    if label not in BEST_YOLO_MODELS:
        raise ValueError(f"Unsupported VideoMAE accident category: {label}")
    if not 0 <= score <= 1:
        raise ValueError(f"Invalid VideoMAE confidence: {score}")
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be in [0, 1]")
    prediction = {**prediction, "requires_review": score < min_confidence}
    return prediction, override or BEST_YOLO_MODELS[label]


def safe_analyze_qwen(frame_paths: list[str], model_name: str, max_frames: int, device_name: str) -> dict[str, Any]:
    try:
        return analyze_qwen(frame_paths, model_name, max_frames, device_name)
    except Exception as exc:
        return {
            "valid": False,
            "error": f"{type(exc).__name__}: {exc}",
            "requires_review": True,
            "limitations": ["Qwen analysis failed; VideoMAE and YOLO results remain available."],
        }


def _frame_paths(agent_output: dict[str, Any]) -> list[str]:
    agent = agent_output.get("agent_output", agent_output)
    frames = agent.get("structured_result", {}).get("key_frames", [])
    return [str(frame["frame_path"]) for frame in frames if frame.get("frame_path")]


def run(
    input_path: Path,
    *,
    checkpoint: Path,
    frame_count: int = 8,
    videomae_frame_count: int = 16,
    yolo_model: str | None = None,
    confidence: float = 0.25,
    qwen_model: str = "Qwen/Qwen2.5-VL-3B-Instruct",
    qwen_frame_count: int = 4,
    device: str = "auto",
    skip_qwen: bool = False,
    min_category_confidence: float = 0.5,
) -> Path:
    if not input_path.is_file():
        raise FileNotFoundError(f"Input video not found: {input_path}")
    _checkpoint_files(checkpoint)
    if min(frame_count, videomae_frame_count, qwen_frame_count) < 1:
        raise ValueError("frame counts must be positive")
    if not 0 < confidence <= 1:
        raise ValueError("confidence must be in (0, 1]")

    from ai.vision.build_supervisor_handoff import OUTPUT_DIR, write_handoff
    from ai.vision.merge_analysis import FINAL_OUTPUT_DIR, build_final_analysis, output_name
    from ai.vision.models import detect_keyframes
    from ai.vision.pipeline import extract_keyframes
    from ai.vision.schemas import convert_detection_to_agent_output

    videomae = infer_videomae(input_path, checkpoint, videomae_frame_count, device)
    prediction, selected_yolo_model = select_yolo_model(videomae, yolo_model, min_category_confidence)
    keyframe_path, _ = extract_keyframes(input_path, frame_count)
    detection_path, _ = detect_keyframes(keyframe_path, selected_yolo_model, confidence)
    agent_path, agent_output = convert_detection_to_agent_output(detection_path)
    qwen = {"valid": False, "skipped": True, "requires_review": True} if skip_qwen else safe_analyze_qwen(
        _frame_paths(agent_output), qwen_model, qwen_frame_count, device
    )

    agent = agent_output.get("agent_output", agent_output)
    structured = agent.setdefault("structured_result", {})
    structured["trained_model_prediction"] = prediction
    structured["selected_yolo_model"] = selected_yolo_model
    structured["qwen_analysis"] = qwen
    if qwen.get("summary"):
        agent["summary"] = qwen["summary"]
    if not qwen.get("valid"):
        agent["status"] = "partial"
        structured.setdefault("limitations", []).extend(qwen.get("limitations", []))
    if prediction["requires_review"]:
        agent["status"] = "partial"
        structured.setdefault("limitations", []).append(
            f"VideoMAE confidence is below the review threshold ({min_category_confidence:.2f})."
        )

    final_path = FINAL_OUTPUT_DIR / output_name(agent_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(
        json.dumps(build_final_analysis(agent_output, videomae), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return write_handoff(final_path, OUTPUT_DIR)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run trained VideoMAE, YOLO and Qwen for Supervisor handoff.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--frame-count", type=int, default=8)
    parser.add_argument("--videomae-frame-count", type=int, default=16)
    parser.add_argument("--yolo-model", default=None, help="Optional explicit override for category-selected YOLO")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--qwen-model", default="Qwen/Qwen2.5-VL-3B-Instruct")
    parser.add_argument("--qwen-frame-count", type=int, default=4)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--skip-qwen", action="store_true", help="Troubleshooting only")
    parser.add_argument("--min-category-confidence", type=float, default=0.5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = run(args.input, checkpoint=args.checkpoint, frame_count=args.frame_count,
                 videomae_frame_count=args.videomae_frame_count, yolo_model=args.yolo_model,
                 confidence=args.confidence, qwen_model=args.qwen_model,
                 qwen_frame_count=args.qwen_frame_count, device=args.device, skip_qwen=args.skip_qwen,
                 min_category_confidence=args.min_category_confidence)
    print(f"supervisor_handoff_path: {output}")


if __name__ == "__main__":
    main()
