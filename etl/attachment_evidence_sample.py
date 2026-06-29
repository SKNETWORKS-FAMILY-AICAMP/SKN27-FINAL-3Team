"""Build a sample attachment/evidence link for one uploaded image.

PM purpose stays evidence/accident_scene; damage_image is only an internal analysis mode.
"""
from pathlib import Path
import json
from datetime import datetime, timezone
from uuid import uuid4


RAW_DIR = Path("storage/vision/raw")
OUTPUT_DIR = Path("storage/vision/outputs/erd_samples")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# PM top-level purpose enum. damage_image must not be used here.
PM_ATTACHMENT_PURPOSES = {
    "fine_notice",
    "accident_scene",
    "accident_statement",
    "evidence",
    "unknown",
}


def find_first_image() -> Path:
    images = sorted(
        path
        for path in RAW_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        raise FileNotFoundError(f"No image files found under {RAW_DIR}")
    return images[0]


def guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".bmp":
        return "image/bmp"
    return "application/octet-stream"


def build_attachment_evidence_sample(
    image_path: Path,
    purpose: str = "evidence",
    analysis_mode: str = "accident_scene",
) -> tuple[Path, dict]:
    if purpose not in PM_ATTACHMENT_PURPOSES:
        raise ValueError(
            f"Invalid PM attachment purpose: {purpose}. "
            f"Allowed values: {sorted(PM_ATTACHMENT_PURPOSES)}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    attachment_id = "att_" + uuid4().hex[:12]
    evidence_id = "evd_" + uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    sample = {
        "sample_name": "single_image_attachment_evidence_link_poc",
        "created_at": now,
        "policy": {
            "pm_attachment_purpose": purpose,
            "vision_internal_analysis_mode": analysis_mode,
            "damage_image_policy": (
                "damage_image is not a PM top-level attachment purpose. "
                "Use evidence or accident_scene at the PM boundary, then map to "
                "damage_image only inside Supervisor/Vision when the context is clear."
            ),
        },
        "attachment": {
            "attachment_id": attachment_id,
            "message_id": "msg_sample_0001",
            "media_type": "image",
            "purpose": purpose,
            "mime_type": guess_mime_type(image_path),
            "storage_uri": image_path.as_posix(),
            "file_name": image_path.name,
            "file_exists": image_path.exists(),
            "privacy_risk": True,
        },
        "evidence": {
            "evidence_id": evidence_id,
            "attachment_id": attachment_id,
            "evidence_type": "uploaded_image",
            "source_uri": image_path.as_posix(),
            "source_ref": f"{attachment_id}#original",
            "description": "User-uploaded image registered as evidence candidate for Vision analysis.",
            "usable_for_agent": True,
        },
        "vision_reference": {
            "node_code": "vision_media_analysis",
            "input_ref": attachment_id,
            "analysis_mode": analysis_mode,
            "expected_structured_result_fields": [
                "media_type",
                "observations",
                "detected_objects",
                "road_type_candidates",
                "accident_type_candidates",
                "risk_event_candidates",
                "event_window",
                "key_frames",
                "damage_area_candidates",
                "evidence_candidates",
                "limitations",
            ],
            "expected_output_link": {
                "evidence_candidates[].source_ref": f"{attachment_id}#original",
                "detected_objects[].frame_path": image_path.as_posix(),
            },
        },
    }

    output_path = OUTPUT_DIR / "attachment_evidence_sample.json"
    output_path.write_text(
        json.dumps(sample, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return output_path, sample


def main():
    image_path = find_first_image()
    output_path, sample = build_attachment_evidence_sample(image_path)

    print(f"image_path: {image_path}")
    print(f"attachment_id: {sample['attachment']['attachment_id']}")
    print(f"evidence_id: {sample['evidence']['evidence_id']}")
    print(f"purpose: {sample['attachment']['purpose']}")
    print(f"analysis_mode: {sample['vision_reference']['analysis_mode']}")
    print(f"output_path: {output_path}")


if __name__ == "__main__":
    main()

