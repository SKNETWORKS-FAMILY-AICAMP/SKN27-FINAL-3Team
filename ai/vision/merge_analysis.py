"""Merge YOLO/bbox agent output with VideoMAE clip inference.

This keeps the existing Vision Agent output unchanged and adds VideoMAE as a
supplementary video-understanding section for report/RAG comparison.
"""
from pathlib import Path
import argparse
import json
from typing import Any


AGENT_OUTPUT_DIR = Path("storage/vision/outputs/agent_outputs")
VIDEOMAE_RESULT_DIR = Path("storage/vision/outputs/videomae_results")
FINAL_OUTPUT_DIR = Path("storage/vision/outputs/final_analysis")
SCHEMA_VERSION = "vision-final-analysis-v1"


def latest_file(directory: Path, pattern: str) -> Path:
    files = sorted(directory.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files found: {directory / pattern}")
    return files[-1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def best_prediction(clip: dict[str, Any]) -> dict[str, Any] | None:
    predictions = clip.get("top_predictions", [])
    if not predictions:
        return None
    return predictions[0]


def build_video_understanding(videomae_result: dict[str, Any]) -> dict[str, Any]:
    clips = []
    for clip in videomae_result.get("clips", []):
        top = best_prediction(clip)
        clips.append(
            {
                "clip_id": clip.get("clip_id"),
                "clip_path": clip.get("clip_path"),
                "clip_start_sec": clip.get("clip_start_sec"),
                "clip_end_sec": clip.get("clip_end_sec"),
                "basis": clip.get("basis"),
                "frame_count": clip.get("frame_count"),
                "top_prediction": top,
                "top_predictions": clip.get("top_predictions", []),
            }
        )

    return {
        "analysis_type": "videomae_pretrained_clip_inference",
        "model_name": videomae_result.get("model_name"),
        "device": videomae_result.get("device"),
        "source_manifest": videomae_result.get("source_manifest"),
        "clip_count": videomae_result.get("clip_count"),
        "clips": clips,
        "interpretation_note": (
            "VideoMAE Kinetics labels are supplementary action hints. "
            "They do not determine accident type, fault ratio, legal liability, "
            "or final situation summary by themselves."
        ),
    }


def build_final_analysis(agent_output: dict[str, Any], videomae_result: dict[str, Any]) -> dict[str, Any]:
    video_understanding = build_video_understanding(videomae_result)
    agent = agent_output.get("agent_output", agent_output)
    top_labels = []
    for clip in video_understanding.get("clips", []):
        top = clip.get("top_prediction")
        if top:
            top_labels.append({"clip_id": clip.get("clip_id"), "label": top.get("label"), "score": top.get("score")})

    return {
        "schema_version": SCHEMA_VERSION,
        "status": agent.get("status", "unknown"),
        "analysis_scope": "single_video_poc",
        "vision_agent_output": agent_output,
        "video_understanding": video_understanding,
        "comparison_summary": {
            "yolo_bbox_role": "key frame evidence, detected objects, bbox-change event window candidates",
            "videomae_role": "clip-level pretrained action hint for comparison",
            "videomae_top_labels": top_labels,
            "decision": "Use VideoMAE as auxiliary evidence only until accident-domain training/evaluation is done.",
        },
        "limitations": [
            "This final analysis does not estimate fault ratio.",
            "This final analysis does not determine legal responsibility.",
            "VideoMAE output is not accident-domain fine-tuned yet.",
            "Human review is required for the actual accident narrative.",
        ],
    }


def output_name(agent_path: Path) -> str:
    stem = agent_path.stem.replace("agent_output_", "")
    return f"final_analysis_{stem}.json"


def merge_analysis(agent_path: Path, videomae_path: Path, output_dir: Path) -> Path:
    agent_output = load_json(agent_path)
    videomae_result = load_json(videomae_path)
    final_analysis = build_final_analysis(agent_output, videomae_result)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_name(agent_path)
    output_path.write_text(json.dumps(final_analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge Vision Agent output and VideoMAE inference result.")
    parser.add_argument("--agent-output", type=Path, default=None)
    parser.add_argument("--videomae-result", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=FINAL_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    agent_path = args.agent_output or latest_file(AGENT_OUTPUT_DIR, "agent_output_*.json")
    videomae_path = args.videomae_result or latest_file(VIDEOMAE_RESULT_DIR, "videomae_results_*.json")
    output_path = merge_analysis(agent_path, videomae_path, args.output_dir)

    print(f"agent_output_path: {agent_path}")
    print(f"videomae_result_path: {videomae_path}")
    print(f"final_analysis_path: {output_path}")


if __name__ == "__main__":
    main()
