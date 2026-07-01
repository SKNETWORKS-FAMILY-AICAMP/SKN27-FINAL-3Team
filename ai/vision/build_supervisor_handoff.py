"""Build the compact Vision payload for Supervisor routing.

The handoff JSON keeps only fields downstream legal/RAG/report agents need:
summary, event candidates, evidence, limitations, and routing hints.
"""
from pathlib import Path
import argparse
import json
from typing import Any


FINAL_ANALYSIS_DIR = Path("storage/vision/outputs/final_analysis")
OUTPUT_DIR = Path("storage/vision/outputs/supervisor_handoff")
SCHEMA_VERSION = "vision-supervisor-handoff-v1"
NOT_DETERMINED_BY_VISION = [
    "fault_ratio",
    "liable_party",
    "traffic_violation",
    "final_accident_type",
]


def latest_file(directory: Path, pattern: str) -> Path:
    files = sorted(directory.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files found: {directory / pattern}")
    return files[-1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def count_detected_objects(objects: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for obj in objects:
        class_name = obj.get("class_name") or "unknown"
        counts[class_name] = counts.get(class_name, 0) + 1
    return dict(sorted(counts.items()))


def compact_event_candidates(event_windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "event_candidate_id": event.get("event_candidate_id"),
            "start_sec": event.get("event_window_start_sec"),
            "end_sec": event.get("event_window_end_sec"),
            "priority_score": event.get("priority_score"),
            "basis": event.get("basis"),
            "source_refs": event.get("source_refs", []),
        }
        for event in event_windows
    ]


def compact_key_frames(key_frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "frame_id": frame.get("frame_id"),
            "timestamp_sec": frame.get("timestamp_sec"),
            "frame_role": frame.get("frame_role"),
            "frame_path": frame.get("frame_path"),
            "selection_reason": frame.get("selection_reason"),
        }
        for frame in key_frames
    ]


def compact_evidence_candidates(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": item.get("evidence_id"),
            "evidence_type": item.get("evidence_type"),
            "source_ref": item.get("source_ref"),
            "timestamp_sec": item.get("timestamp_sec"),
            "frame_path": item.get("frame_path"),
            "object_classes": item.get("object_classes", []),
            "score": item.get("score"),
            "score_type": item.get("score_type"),
        }
        for item in evidence
    ]


def top_video_hint(video_understanding: dict[str, Any]) -> dict[str, Any]:
    clips = video_understanding.get("clips", [])
    if not clips:
        return {
            "model_name": video_understanding.get("model_name"),
            "top_label": None,
            "score": None,
            "usage_policy": "supplementary_context_only",
        }

    clip = clips[0]
    top = clip.get("top_prediction") or {}
    return {
        "model_name": video_understanding.get("model_name"),
        "clip_id": clip.get("clip_id"),
        "top_label": top.get("label"),
        "score": top.get("score"),
        "usage_policy": "supplementary_context_only",
        "note": "VideoMAE pretrained output is an action hint, not accident liability or fault-ratio evidence.",
    }


def build_handoff(final_analysis: dict[str, Any]) -> dict[str, Any]:
    agent = final_analysis.get("vision_agent_output", {}).get("agent_output", {})
    structured = agent.get("structured_result", {})
    metadata = agent.get("metadata", {})
    video_understanding = final_analysis.get("video_understanding", {})

    detected_objects = structured.get("detected_objects", [])
    handoff = {
        "vision_supervisor_handoff": {
            "schema_version": SCHEMA_VERSION,
            "source": {
                "final_analysis_schema_version": final_analysis.get("schema_version"),
                "vision_node_code": agent.get("node_code"),
                "analysis_scope": final_analysis.get("analysis_scope"),
                "source_video": metadata.get("source_path"),
                "vision_result_id": metadata.get("vision_result_id"),
            },
            "status": final_analysis.get("status") or agent.get("status"),
            "media_summary": {
                "media_type": structured.get("media_type"),
                "summary": agent.get("summary"),
                "field_summary": structured.get("field_summary"),
            },
            "event_candidates": compact_event_candidates(structured.get("event_window_candidates", [])),
            "visual_evidence": {
                "key_frames": compact_key_frames(structured.get("key_frames", [])),
                "evidence_candidates": compact_evidence_candidates(structured.get("evidence_candidates", [])),
                "detected_object_summary": count_detected_objects(detected_objects),
            },
            "video_understanding_hint": top_video_hint(video_understanding),
            "not_determined_by_vision": NOT_DETERMINED_BY_VISION,
            "routing_recommendation": {
                "next_agents": ["legal_rag_agent", "precedent_agent", "report_agent"],
                "legal_agent_focus": [
                    "traffic_violation",
                    "legal_responsibility",
                    "applicable_law",
                ],
                "precedent_agent_focus": [
                    "similar_accident_cases",
                    "fault_ratio_reference",
                    "case_factors",
                ],
                "report_agent_focus": [
                    "visual_evidence_summary",
                    "timeline",
                    "limitations",
                ],
            },
            "limitations": final_analysis.get("limitations", []) + structured.get("limitations", []),
        }
    }
    return handoff


def output_name(final_analysis_path: Path) -> str:
    stem = final_analysis_path.stem.replace("final_analysis_", "")
    return f"vision_supervisor_handoff_{stem}.json"


def write_handoff(final_analysis_path: Path, output_dir: Path) -> Path:
    final_analysis = load_json(final_analysis_path)
    handoff = build_handoff(final_analysis)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_name(final_analysis_path)
    output_path.write_text(json.dumps(handoff, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Supervisor handoff JSON from final Vision analysis.")
    parser.add_argument("--final-analysis", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    final_analysis_path = args.final_analysis or latest_file(FINAL_ANALYSIS_DIR, "final_analysis_*.json")
    output_path = write_handoff(final_analysis_path, args.output_dir)
    data = load_json(output_path)["vision_supervisor_handoff"]

    print(f"final_analysis_path: {final_analysis_path}")
    print(f"supervisor_handoff_path: {output_path}")
    print(f"status: {data.get('status')}")
    print(f"event_candidates: {len(data.get('event_candidates', []))}")
    print(f"key_frames: {len(data.get('visual_evidence', {}).get('key_frames', []))}")
    print(f"evidence_candidates: {len(data.get('visual_evidence', {}).get('evidence_candidates', []))}")
    print(f"not_determined_by_vision: {len(data.get('not_determined_by_vision', []))}")


if __name__ == "__main__":
    main()
