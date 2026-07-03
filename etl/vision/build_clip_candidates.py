"""Build VideoMAE comparison clip candidates from final Vision evidence.

Videos up to 5 seconds are kept whole; longer videos use the center of an
event-window candidate to build a 5-second clip for clip-level inference.
"""
from pathlib import Path
import argparse
import json

import cv2


AGENT_OUTPUT_DIR = Path("storage/vision/outputs/agent_outputs")
CLIP_CANDIDATE_DIR = Path("storage/vision/outputs/clip_candidates")
DEFAULT_SHORT_VIDEO_SEC = 5.0


def find_latest_agent_output() -> Path:
    outputs = sorted(AGENT_OUTPUT_DIR.glob("agent_output_*.json"))
    if not outputs:
        raise FileNotFoundError(f"No agent output JSON found under {AGENT_OUTPUT_DIR}")
    return outputs[-1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def video_duration_sec(video_path: Path) -> float | None:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    cap.release()
    if frame_count <= 0 or fps <= 0:
        return None
    return frame_count / fps


def make_full_video_candidate(source_video: str, duration_sec: float) -> dict:
    return {
        "clip_id": "clip_01",
        "source_video": source_video,
        "clip_start_sec": 0.0,
        "clip_end_sec": round(duration_sec, 3),
        "clip_duration_sec": round(duration_sec, 3),
        "priority_score": 1.0,
        "source_refs": [],
        "basis": "short_video_full_context",
        "clip_label_status": "candidate_for_inference",
        "planned_use": "videomae_comparison_poc",
    }


def make_event_window_candidates(
    source_video: str,
    event_windows: list[dict],
    pre_context_sec: float,
    post_context_sec: float,
    source_duration_sec: float | None,
) -> list[dict]:
    candidates = []
    for idx, window in enumerate(event_windows, start=1):
        base_start_sec = float(window.get("event_window_start_sec") or 0.0)
        base_end_sec = max(base_start_sec, float(window.get("event_window_end_sec") or base_start_sec))
        accident_sec = (base_start_sec + base_end_sec) / 2
        start_sec = max(0.0, accident_sec - pre_context_sec)
        end_sec = accident_sec + post_context_sec
        if source_duration_sec is not None:
            end_sec = min(source_duration_sec, end_sec)
        clip_id = window.get("event_candidate_id", f"event_window_{idx:02d}").replace("event_window", "clip")
        candidates.append(
            {
                "clip_id": clip_id,
                "source_video": source_video,
                "accident_candidate_sec": round(accident_sec, 3),
                "clip_start_sec": round(start_sec, 3),
                "clip_end_sec": round(end_sec, 3),
                "clip_duration_sec": round(end_sec - start_sec, 3),
                "priority_score": window.get("priority_score"),
                "source_refs": window.get("source_refs", []),
                "basis": window.get("basis", "agent_event_window_center_5s"),
                "clip_label_status": window.get("clip_status", "candidate_for_inference"),
                "pre_context_sec": pre_context_sec,
                "post_context_sec": post_context_sec,
                "planned_use": "videomae_comparison_poc",
            }
        )
    return candidates


def build_clip_candidates(
    agent_output_path: Path,
    pre_context_sec: float = 2.5,
    post_context_sec: float = 2.5,
    short_video_sec: float = DEFAULT_SHORT_VIDEO_SEC,
) -> tuple[Path, dict]:
    CLIP_CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)

    data = load_json(agent_output_path)
    agent = data["agent_output"]
    result = agent["structured_result"]
    metadata = agent["metadata"]
    source_video = metadata.get("source_path")
    source_stem = Path(source_video or "media").stem
    duration_sec = video_duration_sec(Path(source_video)) if source_video else None

    if duration_sec is not None and duration_sec <= short_video_sec:
        candidates = [make_full_video_candidate(source_video, duration_sec)]
    else:
        candidates = make_event_window_candidates(
            source_video=source_video,
            event_windows=result.get("event_window_candidates", []),
            pre_context_sec=pre_context_sec,
            post_context_sec=post_context_sec,
            source_duration_sec=duration_sec,
        )

    output = {
        "source_agent_output": agent_output_path.as_posix(),
        "source_video": source_video,
        "source_duration_sec": None if duration_sec is None else round(duration_sec, 3),
        "short_video_threshold_sec": short_video_sec,
        "schema_version": "clip-candidates-v1",
        "candidate_count": len(candidates),
        "clip_candidates": candidates,
    }

    output_path = CLIP_CANDIDATE_DIR / f"clip_candidates_{source_stem}.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path, output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build clip candidates from Vision Agent output.")
    parser.add_argument("--agent-output", type=Path, default=None)
    parser.add_argument("--pre-context-sec", type=float, default=2.5)
    parser.add_argument("--post-context-sec", type=float, default=2.5)
    parser.add_argument("--short-video-sec", type=float, default=DEFAULT_SHORT_VIDEO_SEC)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    agent_output_path = args.agent_output or find_latest_agent_output()
    output_path, output = build_clip_candidates(
        agent_output_path=agent_output_path,
        pre_context_sec=args.pre_context_sec,
        post_context_sec=args.post_context_sec,
        short_video_sec=args.short_video_sec,
    )

    print(f"agent_output_path: {agent_output_path}")
    print(f"clip_candidates_path: {output_path}")
    print(f"source_duration_sec: {output['source_duration_sec']}")
    print(f"short_video_threshold_sec: {output['short_video_threshold_sec']}")
    print(f"candidate_count: {output['candidate_count']}")
    for item in output["clip_candidates"]:
        print(
            f"{item['clip_id']} "
            f"{item['clip_start_sec']}~{item['clip_end_sec']}s "
            f"score={item['priority_score']} "
            f"basis={item['basis']}"
        )


if __name__ == "__main__":
    main()
