"""Convert detection output into Vision Agent event/evidence JSON.

The agent summarizes visual observations and candidate event windows. Fault,
liability, and final accident type stay unresolved for downstream agents.
"""
from pathlib import Path
import json
from uuid import uuid4


NODE_CODE = "vision_media_analysis"
SCHEMA_VERSION = "vision-agent-output-v2"

PM_ATTACHMENT_PURPOSES = {
    "fine_notice",
    "accident_scene",
    "accident_statement",
    "evidence",
    "unknown",
}

VISION_ANALYSIS_MODES = {
    "accident_scene",
    "damage_image",
    "unknown",
}

OUTPUT_DIR = Path("storage/vision/outputs")
DETECTION_DIR = OUTPUT_DIR / "detections"
SCHEMA_OUTPUT_DIR = OUTPUT_DIR / "agent_outputs"
IMPORTANT_OBJECTS = {
    "person",
    "car",
    "truck",
    "bus",
    "motorcycle",
    "bicycle",
    "traffic light",
    "stop sign",
}
VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "bicycle"}


def find_latest_detection_output() -> Path:
    outputs = sorted(DETECTION_DIR.glob("detections_*.json"))
    if not outputs:
        raise FileNotFoundError(f"No detection JSON found under {DETECTION_DIR}. Run ai/vision/models.py first.")
    return outputs[-1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def infer_media_type(source_path: str | None) -> str:
    if not source_path:
        return "unknown"
    suffix = Path(source_path).suffix.lower()
    if suffix in {".mp4", ".mov", ".avi", ".mkv"}:
        return "video"
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        return "image"
    return "unknown"


def summarize_classes(detections: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for frame in detections:
        for obj in frame.get("objects", []):
            class_name = obj.get("class_name", "unknown")
            counts[class_name] = counts.get(class_name, 0) + 1
    return counts


def bbox_center(bbox: list[float] | None) -> tuple[float, float] | None:
    if not bbox or len(bbox) != 4:
        return None
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def bbox_area(bbox: list[float] | None) -> float:
    if not bbox or len(bbox) != 4:
        return 0.0
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def distance(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float:
    if a is None or b is None:
        return 0.0
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def frame_ref(frame: dict) -> str:
    return f"frame_{int(frame.get('frame_order') or 0):02d}"


def best_objects_by_class(frame: dict) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for obj in frame.get("objects", []):
        class_name = obj.get("class_name", "unknown")
        if class_name not in IMPORTANT_OBJECTS:
            continue
        current = best.get(class_name)
        if current is None or float(obj.get("confidence", 0.0)) > float(current.get("confidence", 0.0)):
            best[class_name] = obj
    return best


def build_summary(class_counts: dict[str, int], event_windows: list[dict], media_type: str) -> str:
    if not class_counts:
        return f"{media_type}에서 신뢰도 기준을 통과한 주요 객체가 탐지되지 않았습니다."

    classes = ", ".join(f"{name} {count}건" for name, count in sorted(class_counts.items()))
    if event_windows:
        window = event_windows[0]
        event_text = f" {window['event_window_start_sec']}~{window['event_window_end_sec']}초 구간이 우선 확인 후보입니다."
    else:
        event_text = " 사건 관련 구간은 key frame 범위 기준으로만 추정되었습니다."
    return (
        f"{media_type} key frame에서 {classes}이 탐지되었습니다."
        f"{event_text} 이 결과는 관찰 근거이며 과실비율, 가해 차량, 법적 책임을 확정하지 않습니다."
    )


def build_detected_objects(detections: list[dict]) -> list[dict]:
    objects = []
    for frame in detections:
        source_ref = frame_ref(frame)
        for obj_index, obj in enumerate(frame.get("objects", []), start=1):
            objects.append(
                {
                    "object_id": f"obj_{source_ref}_{obj_index:03d}",
                    "source_ref": source_ref,
                    "class_id": obj.get("class_id"),
                    "class_name": obj.get("class_name"),
                    "confidence": obj.get("confidence"),
                    "bbox": {"format": "xyxy", "values": obj.get("bbox_xyxy")},
                    "timestamp_sec": frame.get("timestamp_sec"),
                    "frame_path": frame.get("frame_path"),
                }
            )
    return objects


def build_object_change_observations(detections: list[dict]) -> list[dict]:
    observations = []
    previous_frame = None
    previous_best: dict[str, dict] = {}

    for frame in sorted(detections, key=lambda item: item.get("timestamp_sec") or 0):
        current_best = best_objects_by_class(frame)
        if previous_frame is None:
            previous_frame = frame
            previous_best = current_best
            continue

        shared = sorted(set(previous_best) & set(current_best))
        appeared = sorted(set(current_best) - set(previous_best))
        disappeared = sorted(set(previous_best) - set(current_best))
        motions = []

        for class_name in shared:
            prev_obj = previous_best[class_name]
            curr_obj = current_best[class_name]
            center_move = distance(bbox_center(prev_obj.get("bbox_xyxy")), bbox_center(curr_obj.get("bbox_xyxy")))
            area_change = abs(bbox_area(curr_obj.get("bbox_xyxy")) - bbox_area(prev_obj.get("bbox_xyxy")))
            motions.append(
                {
                    "class_name": class_name,
                    "center_move_px": round(center_move, 2),
                    "bbox_area_change": round(area_change, 2),
                }
            )

        motion_score = sum(item["center_move_px"] for item in motions) / 100.0
        motion_score += len(appeared) * 0.5 + len(disappeared) * 0.3
        if not motions and not appeared and not disappeared:
            previous_frame = frame
            previous_best = current_best
            continue

        observations.append(
            {
                "source_refs": [frame_ref(previous_frame), frame_ref(frame)],
                "from_timestamp_sec": previous_frame.get("timestamp_sec"),
                "to_timestamp_sec": frame.get("timestamp_sec"),
                "motion_score": round(motion_score, 4),
                "object_motion": motions,
                "appeared_classes": appeared,
                "disappeared_classes": disappeared,
                "basis": "class_level_bbox_change_between_sampled_keyframes",
            }
        )
        previous_frame = frame
        previous_best = current_best

    return observations


def build_event_window_candidates(detections: list[dict], changes: list[dict], media_type: str) -> list[dict]:
    if media_type != "video" or not detections:
        return []

    if changes:
        peak = max(changes, key=lambda item: item.get("motion_score", 0.0))
        start = max(0.0, float(peak.get("from_timestamp_sec") or 0.0) - 2.0)
        end = float(peak.get("to_timestamp_sec") or start) + 2.0
        score = min(1.0, 0.35 + float(peak.get("motion_score", 0.0)) / 5.0)
        return [
            {
                "event_candidate_id": "event_window_01",
                "event_window_start_sec": round(start, 3),
                "event_window_end_sec": round(end, 3),
                "priority_score": round(score, 4),
                "source_refs": peak.get("source_refs", []),
                "basis": "bbox_motion_peak_with_2sec_context",
                "clip_status": "candidate_for_inference",
            }
        ]

    timestamps = [frame.get("timestamp_sec") for frame in detections if frame.get("timestamp_sec") is not None]
    if not timestamps:
        return []
    return [
        {
            "event_candidate_id": "event_window_01",
            "event_window_start_sec": min(timestamps),
            "event_window_end_sec": max(timestamps),
            "priority_score": 0.2,
            "source_refs": [frame_ref(frame) for frame in detections],
            "basis": "uniform_keyframe_fallback",
            "clip_status": "candidate_for_inference",
        }
    ]


def build_key_frames(detections: list[dict], event_windows: list[dict]) -> list[dict]:
    source_refs = event_windows[0].get("source_refs", []) if event_windows else []
    peak_ref = source_refs[-1] if source_refs else None
    peak_order = int(peak_ref.split("_")[-1]) if peak_ref else None
    keyframes = []

    for frame in detections:
        order = int(frame.get("frame_order") or 0)
        role = "fallback"
        reason = "uniform_sample_for_poc"
        if peak_order is not None:
            if order < peak_order:
                role = "event_before" if order <= peak_order - 2 else "risk_increase"
                reason = "before_bbox_motion_peak"
            elif order == peak_order:
                role = "event_peak"
                reason = "bbox_motion_peak_candidate"
            else:
                role = "event_after"
                reason = "after_bbox_motion_peak"

        keyframes.append(
            {
                "frame_id": frame_ref(frame),
                "frame_order": frame.get("frame_order"),
                "frame_index": frame.get("frame_index"),
                "timestamp_sec": frame.get("timestamp_sec"),
                "frame_role": role,
                "frame_path": frame.get("frame_path"),
                "selection_reason": reason,
            }
        )
    return [item for item in keyframes if item.get("frame_path")]


def build_evidence_candidates(detections: list[dict]) -> list[dict]:
    candidates = []
    for frame in detections:
        objects = frame.get("objects", [])
        if not objects:
            continue
        candidates.append(
            {
                "evidence_id": f"ev_{int(frame.get('frame_order') or 0):02d}",
                "evidence_type": "key_frame_object_detection",
                "source_ref": frame_ref(frame),
                "timestamp_sec": frame.get("timestamp_sec"),
                "frame_path": frame.get("frame_path"),
                "object_count": frame.get("object_count", len(objects)),
                "object_classes": sorted({obj.get("class_name", "unknown") for obj in objects}),
                "score": max(float(obj.get("confidence", 0.0)) for obj in objects),
                "score_type": "max_object_detection_confidence",
            }
        )
    return candidates


def build_scene_context_candidates(class_counts: dict[str, int]) -> list[dict]:
    candidates = []
    if class_counts.get("traffic light"):
        candidates.append(
            {
                "context_type": "traffic_signal_visible",
                "label": "신호등 후보",
                "score": None,
                "basis": "traffic light object detected",
            }
        )
    if class_counts.get("person"):
        candidates.append(
            {
                "context_type": "vulnerable_road_user_visible",
                "label": "보행자 관련 장면 후보",
                "score": None,
                "basis": "person object detected",
            }
        )
    return candidates


def build_field_summary(class_counts: dict[str, int], event_windows: list[dict], changes: list[dict]) -> str:
    lines = []
    if event_windows:
        window = event_windows[0]
        lines.append(f"{window['event_window_start_sec']}~{window['event_window_end_sec']}초 구간이 우선 확인 후보로 생성되었습니다.")
    if class_counts:
        lines.append("탐지된 주요 객체는 " + ", ".join(f"{name} {count}건" for name, count in sorted(class_counts.items())) + "입니다.")
    if changes:
        peak = max(changes, key=lambda item: item.get("motion_score", 0.0))
        lines.append(f"{peak.get('from_timestamp_sec')}~{peak.get('to_timestamp_sec')}초 사이 객체 위치 또는 등장 변화가 가장 크게 관찰되었습니다.")
    lines.append("영상만으로 사고유형, 과실비율, 가해 차량, 법적 책임은 확정하지 않습니다.")
    return " ".join(lines)


def build_unavailable_items() -> list[dict]:
    return [
        {"item": "fault_ratio", "reason": "Vision 단독 결과로 과실비율을 산정하지 않습니다."},
        {"item": "liable_party", "reason": "단일 카메라 영상만으로 책임 주체를 확정하지 않습니다."},
        {"item": "traffic_violation", "reason": "신호 상태와 법규 위반은 추가 정보 확인이 필요합니다."},
        {"item": "final_accident_type", "reason": "사용자 진술과 RAG 판단을 함께 확인해야 합니다."},
    ]


def convert_detection_to_agent_output(detection_path: Path) -> tuple[Path, dict]:
    SCHEMA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    detection_output = load_json(detection_path)
    source_path = detection_output.get("source_video")
    source_stem = Path(source_path or "media").stem
    media_type = infer_media_type(source_path)
    detections = detection_output.get("detections", [])
    class_counts = summarize_classes(detections)
    changes = build_object_change_observations(detections)
    event_windows = build_event_window_candidates(detections, changes, media_type)

    structured_result = {
        "media_type": media_type,
        "event_window_candidates": event_windows,
        "key_clips": [
            {
                "clip_id": window["event_candidate_id"].replace("event_window", "clip"),
                "clip_start_sec": window["event_window_start_sec"],
                "clip_end_sec": window["event_window_end_sec"],
                "clip_duration_sec": round(window["event_window_end_sec"] - window["event_window_start_sec"], 3),
                "clip_path": None,
                "clip_status": window["clip_status"],
                "source_refs": window["source_refs"],
            }
            for window in event_windows
        ],
        "key_frames": build_key_frames(detections, event_windows),
        "detected_objects": build_detected_objects(detections),
        "object_change_observations": changes,
        "scene_context_candidates": build_scene_context_candidates(class_counts),
        "user_claim_comparison": {
            "status": "not_provided",
            "message": "사용자 사고 진술이 입력되면 영상 관찰 결과와 일치 가능/추가 확인 필요/확인 불가 항목으로 대조합니다.",
        },
        "field_summary": build_field_summary(class_counts, event_windows, changes),
        "evidence_candidates": build_evidence_candidates(detections),
        "unavailable_items": build_unavailable_items(),
        "limitations": [
            {"type": "poc_baseline_limit", "message": "현재 결과는 균등 key frame과 YOLO 객체 탐지 기반 POC입니다."},
            {"type": "tracking_limit", "message": "동일 객체 추적 모델 없이 class 단위 bbox 변화로 사건 후보를 추정합니다."},
            {"type": "legal_limit", "message": "과실비율, 법적 책임, 신호 위반 여부를 확정하지 않습니다."},
        ],
    }

    agent_output = {
        "agent_output": {
            "node_code": NODE_CODE,
            "status": "success" if detections else "partial",
            "summary": build_summary(class_counts, event_windows, media_type),
            "structured_result": structured_result,
            "metadata": {
                "schema_version": SCHEMA_VERSION,
                "vision_result_id": f"vr_{uuid4().hex[:12]}",
                "source_path": source_path,
                "keyframe_output_path": detection_output.get("keyframe_output_path"),
                "detection_output_path": detection_path.as_posix(),
                "model": detection_output.get("model", {}),
                "purpose_policy": {
                    "pm_attachment_purpose_enum": sorted(PM_ATTACHMENT_PURPOSES),
                    "damage_image_policy": "damage_image is not a PM top-level purpose; it is allowed only as a Vision internal analysis_mode.",
                    "vision_internal_analysis_modes": sorted(VISION_ANALYSIS_MODES),
                },
            },
        }
    }

    output_path = SCHEMA_OUTPUT_DIR / f"agent_output_{source_stem}.json"
    output_path.write_text(json.dumps(agent_output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path, agent_output


def main() -> None:
    detection_path = find_latest_detection_output()
    output_path, agent_output = convert_detection_to_agent_output(detection_path)
    result = agent_output["agent_output"]["structured_result"]

    print(f"detection_path: {detection_path}")
    print(f"agent_output_path: {output_path}")
    print(f"status: {agent_output['agent_output']['status']}")
    print(f"event_windows: {len(result['event_window_candidates'])}")
    print(f"key_frames: {len(result['key_frames'])}")
    print(f"detected_objects: {len(result['detected_objects'])}")
    print(f"object_change_observations: {len(result['object_change_observations'])}")
    print(f"evidence_candidates: {len(result['evidence_candidates'])}")


if __name__ == "__main__":
    main()
