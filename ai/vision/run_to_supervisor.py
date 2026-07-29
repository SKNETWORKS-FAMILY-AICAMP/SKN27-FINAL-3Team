"""Run trained VideoMAE + YOLO + Qwen and create a Supervisor handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

DEFAULT_QWEN_MODEL = "Qwen/Qwen2.5-VL-3B-Instruct"
DEFAULT_QWEN_REVISION = "66285546d2b821cf421d4f5eb2576359d3770cd3"


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

    from ai.vision.train_videomae_classifier import choose_device, read_video_frames

    device = choose_device(device_name)
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


def _json_object(
    text: str, allowed_frame_refs: set[str] | None = None
) -> dict[str, Any]:
    from ai.vision.vlm_json import parse_vlm_json

    value, valid, error = parse_vlm_json(text, allowed_frame_refs)
    if not valid:
        raise ValueError(error)
    return value


def qwen_error_code(error: str) -> str:
    if error.startswith("vlm_input_contract:"):
        return "vision_qwen_input_contract"
    if error.startswith("json_incomplete:"):
        return "vision_qwen_json_incomplete"
    if error.startswith("schema_invalid:"):
        return "vision_qwen_schema_invalid"
    if error.startswith("language_invalid:"):
        return "vision_qwen_language_invalid"
    return "vision_qwen_unavailable"


def analyze_qwen(
    frame_paths: list[str],
    frame_metadata: list[dict],
    classification_context: dict[str, Any],
    model_name: str,
    max_frames: int,
    device_name: str,
    qwen_revision: str = DEFAULT_QWEN_REVISION,
) -> dict[str, Any]:
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
    from ai.vision.vlm_input import build_qwen_content
    from ai.vision.vlm_json import (
        VLM_JSON_PROMPT,
        adaptive_retry_prompt,
        retry_token_limit,
    )

    processor = AutoProcessor.from_pretrained(model_name, revision=qwen_revision)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_name,
        revision=qwen_revision,
        torch_dtype="auto",
        device_map="auto" if device_name == "auto" else device_name,
    ).eval()
    last_error = "json_incomplete:no_attempt"
    result = None
    for prompt_index in range(2):
        prompt = (
            VLM_JSON_PROMPT
            if prompt_index == 0
            else adaptive_retry_prompt(last_error)
        )
        content = build_qwen_content(
            frame_paths, frame_metadata, prompt, max_frames, classification_context
        )
        messages = [{"role": "user", "content": content}]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = processor(
            text=[text], images=image_inputs, videos=video_inputs, padding=True, return_tensors="pt"
        ).to(model.device)
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                max_new_tokens=(
                    512 if prompt_index == 0 else retry_token_limit(last_error)
                ),
                do_sample=False,
                use_cache=True,
            )
        trimmed = [output[len(source) :] for source, output in zip(inputs.input_ids, generated)]
        raw = processor.batch_decode(
            trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]
        try:
            allowed_refs = {
                f"frame_{int(item['frame_order']):02d}"
                for item in frame_metadata[:max_frames]
            }
            result = _json_object(raw, allowed_refs)
        except ValueError as exc:
            last_error = str(exc)
        del inputs, generated
        if result is not None:
            break
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    if result is None:
        raise ValueError(last_error)
    result.update({"valid": True, "model_name": model_name, "frame_count": min(len(frame_paths), max_frames)})
    return result


def select_yolo_model(
    videomae: dict[str, Any], override: str | None = None, min_confidence: float = 0.5
) -> tuple[dict[str, Any], str]:
    from ai.vision.category_vlm_config import BEST_YOLO_MODELS
    from ai.vision.trained_category_classifier import LABELS

    try:
        prediction = videomae["clips"][0]["top_predictions"][0]
        raw_label = str(prediction["label"])
        label = LABELS.get(raw_label, raw_label)
        score = float(prediction["score"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("VideoMAE did not return a valid top prediction") from exc
    if label not in BEST_YOLO_MODELS:
        raise ValueError(f"Unsupported VideoMAE accident category: {label}")
    if not 0 <= score <= 1:
        raise ValueError(f"Invalid VideoMAE confidence: {score}")
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be in [0, 1]")
    prediction = {
        **prediction,
        "label": label,
        "raw_label": raw_label,
        "requires_review": score < min_confidence,
    }
    return prediction, override or BEST_YOLO_MODELS[label]


def safe_analyze_qwen(
    frame_paths: list[str],
    frame_metadata: list[dict],
    classification_context: dict[str, Any],
    model_name: str,
    max_frames: int,
    device_name: str,
    qwen_revision: str = DEFAULT_QWEN_REVISION,
) -> dict[str, Any]:
    def fallback(error_code: str) -> dict[str, Any]:
        label = classification_context["canonical_label"]
        confidence = classification_context.get("confidence")
        return {
            "valid": False,
            "schema_version": "vision-qwen-explanation-v1",
            "narrative": (
                f"VideoMAE classified the event as {label}"
                f" with confidence {confidence:.2%}."
                if isinstance(confidence, (int, float))
                else f"VideoMAE classified the event as {label}."
            ),
            "evidence_sentences": [],
            "conflict": False,
            "conflict_reason": None,
            "uncertainties": ["Qwen explanation generation failed; human review is required."],
            "fallback_used": True,
            "error_code": error_code,
            "requires_review": True,
            "limitations": ["Qwen explanation was unavailable; VideoMAE and YOLO results remain available."],
        }
    if not frame_paths:
        return fallback("vision_qwen_input_contract")
    try:
        return analyze_qwen(
            frame_paths,
            frame_metadata,
            classification_context,
            model_name,
            max_frames,
            device_name,
            qwen_revision,
        )
    except Exception as exc:
        return fallback(qwen_error_code(str(exc)))


def _qwen_evidence(
    agent_output: dict[str, Any], visualization_output: dict[str, Any]
) -> tuple[list[str], list[dict]]:
    agent = agent_output.get("agent_output", agent_output)
    structured = agent.get("structured_result", {})
    frames = {frame["frame_id"]: frame for frame in structured.get("key_frames", [])}
    objects = {}
    for obj in structured.get("detected_objects", []):
        objects.setdefault(obj.get("source_ref"), []).append({
            "class_name": obj.get("class_name", "unknown"),
            "confidence": obj.get("confidence", 0.0),
            "bbox_xyxy": obj.get("bbox", {}).get("values"),
        })

    paths, metadata = [], []
    for visual in visualization_output.get("visualizations", []):
        frame = frames.get(visual.get("frame_id"))
        if not frame or not visual.get("visualization_path"):
            continue
        paths.append(visual["visualization_path"])
        metadata.append({
            "frame_order": frame.get("frame_order"),
            "timestamp_sec": frame.get("timestamp_sec"),
            "role": frame.get("frame_role", "event_evidence"),
            "selection_reason": frame.get("selection_reason", "selected_by_event_evidence"),
            "objects": objects.get(visual["frame_id"], []),
        })
    return paths, metadata


def run(
    input_path: Path,
    *,
    checkpoint: Path,
    frame_count: int = 32,
    videomae_frame_count: int = 32,
    yolo_model: str | None = None,
    confidence: float = 0.25,
    qwen_model: str = DEFAULT_QWEN_MODEL,
    qwen_revision: str = DEFAULT_QWEN_REVISION,
    qwen_frame_count: int = 12,
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
    from ai.vision.visualize import create_visualizations

    videomae = infer_videomae(input_path, checkpoint, videomae_frame_count, device)
    prediction, selected_yolo_model = select_yolo_model(videomae, yolo_model, min_category_confidence)
    top_predictions = videomae["clips"][0].get("top_predictions", [])
    top2_margin = (
        round(float(top_predictions[0]["score"]) - float(top_predictions[1]["score"]), 6)
        if len(top_predictions) > 1 else None
    )
    _, weights = _checkpoint_files(checkpoint)
    checkpoint_hash = hashlib.sha256(weights.read_bytes()).hexdigest()
    classification_context = {
        "canonical_label": prediction["label"],
        "confidence": prediction["score"],
        "top2_margin": top2_margin,
        "requires_review": prediction["requires_review"],
        "model_version": checkpoint.name,
        "checkpoint_hash": checkpoint_hash,
    }
    keyframe_path, _ = extract_keyframes(input_path, frame_count)
    detection_path, _ = detect_keyframes(keyframe_path, selected_yolo_model, confidence)
    agent_path, agent_output = convert_detection_to_agent_output(detection_path)
    _, visualization_output = create_visualizations(agent_path)
    qwen_paths, qwen_metadata = _qwen_evidence(agent_output, visualization_output)
    qwen = {
        "valid": False,
        "skipped": True,
        "requires_review": True,
        "error_code": "vision_qwen_skipped",
    } if skip_qwen else safe_analyze_qwen(
        qwen_paths,
        qwen_metadata,
        classification_context,
        qwen_model,
        qwen_frame_count,
        device,
        qwen_revision,
    )

    agent = agent_output.get("agent_output", agent_output)
    structured = agent.setdefault("structured_result", {})
    structured["trained_model_prediction"] = prediction
    structured["selected_yolo_model"] = selected_yolo_model
    structured["qwen_analysis"] = qwen
    if not qwen.get("valid"):
        agent["status"] = "partial"
        structured.setdefault("limitations", []).extend(qwen.get("limitations", []))
    if prediction["requires_review"]:
        agent["status"] = "partial"
        structured.setdefault("limitations", []).append(
            f"VideoMAE confidence is below the review threshold ({min_category_confidence:.2f})."
        )
    if qwen.get("conflict"):
        agent["status"] = "partial"
        prediction["requires_review"] = True
        structured.setdefault("limitations", []).append(
            "Qwen reported a conflict with visible evidence; the VideoMAE label remains unchanged."
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
    parser.add_argument("--frame-count", type=int, default=32)
    parser.add_argument("--videomae-frame-count", type=int, default=32)
    parser.add_argument("--yolo-model", default=None, help="Optional explicit override for category-selected YOLO")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument(
        "--qwen-model",
        default=os.getenv("VISION_QWEN_MODEL_ID", DEFAULT_QWEN_MODEL),
    )
    parser.add_argument(
        "--qwen-revision",
        default=os.getenv("VISION_QWEN_MODEL_REVISION", DEFAULT_QWEN_REVISION),
    )
    parser.add_argument("--qwen-frame-count", type=int, default=12)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--skip-qwen", action="store_true", help="Troubleshooting only")
    parser.add_argument("--min-category-confidence", type=float, default=0.5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = run(args.input, checkpoint=args.checkpoint, frame_count=args.frame_count,
                 videomae_frame_count=args.videomae_frame_count, yolo_model=args.yolo_model,
                 confidence=args.confidence, qwen_model=args.qwen_model,
                 qwen_revision=args.qwen_revision,
                 qwen_frame_count=args.qwen_frame_count, device=args.device, skip_qwen=args.skip_qwen,
                 min_category_confidence=args.min_category_confidence)
    print(f"supervisor_handoff_path: {output}")


if __name__ == "__main__":
    main()
