import csv
import hashlib
from pathlib import Path

from ai.vision.audit_project_readiness import audit_artifacts, audit_manifest, audit_qwen_results


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_readiness_audits_integrity_metadata_leakage_and_qwen_frames(tmp_path):
    artifact = tmp_path / "model" / "config.json"
    artifact.parent.mkdir()
    artifact.write_text("{}", encoding="utf-8")

    manifest = tmp_path / "manifest.csv"
    write_csv(
        manifest,
        [
            {
                "asset_id": "a",
                "incident_id": "same",
                "split": "train",
                "viewpoint": "front",
                "lighting": "day",
                "visible_target": "car",
            },
            {
                "asset_id": "b",
                "incident_id": "same",
                "split": "test",
                "viewpoint": "unknown",
                "lighting": "",
                "visible_target": "",
            },
        ],
    )
    qwen = tmp_path / "qwen_yolo_compare_results.csv"
    write_csv(qwen, [{"asset_id": "a", "qwen_input_frame_count": "4"}])

    artifacts = audit_artifacts([artifact, tmp_path / "missing.json"])
    metadata = audit_manifest(manifest)
    qwen_result = audit_qwen_results([qwen])

    assert artifacts[0]["sha256"] == hashlib.sha256(b"{}").hexdigest()
    assert metadata["incident_integrity"] == "leak_detected"
