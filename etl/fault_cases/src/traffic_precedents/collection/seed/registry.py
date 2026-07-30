"""PDF 참조 사건번호 250건의 시드 상태를 하나의 레지스트리로 고정합니다."""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .case_number import normalize_case_number


REGISTRY_VERSION = "seed_registry_v1.0.0"
HTML_TAG_RE = re.compile(r"<[^>]*>")
WHITESPACE_RE = re.compile(r"\s+")


def _visible(value: Any) -> str:
    text = html.unescape(str(value or ""))
    return WHITESPACE_RE.sub(" ", HTML_TAG_RE.sub(" ", text)).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise TypeError(f"JSON 객체가 아닌 행이 있습니다: {path}")
                rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _case_key(row: dict[str, Any]) -> str:
    raw = row.get("case_number") or row.get("_requested_case_number") or ""
    return normalize_case_number(str(raw))


def _ready_quality(record: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not _visible(
        record.get("판례정보일련번호")
        or record.get("판례일련번호")
        or record.get("_case_id")
    ):
        reasons.append("MISSING_RECORD_ID")
    if not _visible(
        record.get("사건번호") or record.get("_requested_case_number")
    ):
        reasons.append("MISSING_CASE_NUMBER")
    if not any(
        _visible(record.get(field))
        for field in ("판례내용", "판시사항", "판결요지")
    ):
        reasons.append("ALL_MAIN_TEXT_FIELDS_EMPTY")
    return not reasons, reasons


def _index_unique(
    rows: list[dict[str, Any]],
    label: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _case_key(row)
        if not key:
            raise ValueError(f"{label}에 사건번호가 없는 행이 있습니다.")
        if key in result:
            raise ValueError(f"{label} 사건번호 중복: {key}")
        result[key] = row
    return result


def build_seed_registry(
    unique_path: Path,
    collected_path: Path,
    not_found_path: Path,
    ambiguous_path: Path,
    errors_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """250건의 배타적 수집 상태와 59건 SEED_READY 파일을 생성합니다."""

    inputs = {
        "unique": unique_path.resolve(),
        "collected": collected_path.resolve(),
        "not_found": not_found_path.resolve(),
        "ambiguous": ambiguous_path.resolve(),
        "errors": errors_path.resolve(),
    }
    for label, path in inputs.items():
        if not path.is_file():
            raise FileNotFoundError(f"{label} 입력 파일이 없습니다: {path}")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now().isoformat(timespec="seconds")
    input_manifest = {
        label: {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for label, path in inputs.items()
    }

    unique_rows = _read_jsonl(inputs["unique"])
    collected_rows = _read_jsonl(inputs["collected"])
    not_found_rows = _read_jsonl(inputs["not_found"])
    ambiguous_rows = _read_jsonl(inputs["ambiguous"])
    error_rows = _read_jsonl(inputs["errors"])

    collected = _index_unique(collected_rows, "collected")
    not_found = _index_unique(not_found_rows, "not_found")
    ambiguous = _index_unique(ambiguous_rows, "ambiguous")
    outcome_keys = set(collected) | set(not_found) | set(ambiguous)
    overlap_count = (
        len(collected) + len(not_found) + len(ambiguous) - len(outcome_keys)
    )

    registry_rows: list[dict[str, Any]] = []
    ready_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    counts = {
        "unique_case_number_count": len(unique_rows),
        "seed_ready_count": 0,
        "unresolved_not_found_count": 0,
        "unresolved_ambiguous_count": 0,
        "collection_error_count": 0,
        "missing_outcome_count": 0,
        "outcome_overlap_count": overlap_count,
        "pdf_warning_count": len(error_rows),
    }
    seen_unique: set[str] = set()

    for source in unique_rows:
        key = _case_key(source)
        if not key:
            raise ValueError("고유 사건번호 입력에 빈 사건번호가 있습니다.")
        if key in seen_unique:
            raise ValueError(f"고유 사건번호 입력 중복: {key}")
        seen_unique.add(key)
        base = {
            "case_number": source["case_number"],
            "normalized_case_number": key,
            "source_pdfs": source.get("source_pdfs", []),
            "source_pages": source.get("source_pages", {}),
            "inclusion_route": "official_fault_standard_citation",
            "force_ready": True,
            "registry_version": REGISTRY_VERSION,
        }

        if key in collected:
            record = collected[key]
            quality_passed, quality_reasons = _ready_quality(record)
            if quality_passed:
                status = "SEED_READY"
                counts["seed_ready_count"] += 1
                ready = dict(record)
                ready["internal_grade"] = "SEED_READY"
                ready["seed_registry_status"] = status
                ready["seed_validator"] = {
                    "version": REGISTRY_VERSION,
                    "status": "PASSED",
                    "reason_codes": [
                        "OFFICIAL_FAULT_STANDARD_CITATION",
                        "DETAIL_TEXT_PRESENT",
                    ],
                }
                ready_rows.append(ready)
            else:
                status = "SEED_COLLECTION_ERROR"
                counts["collection_error_count"] += 1

            registry = {
                **base,
                "seed_status": status,
                "internal_grade": (
                    "SEED_READY" if status == "SEED_READY" else None
                ),
                "record_id": (
                    record.get("판례정보일련번호")
                    or record.get("판례일련번호")
                    or record.get("_case_id")
                ),
                "official_case_number": record.get("사건번호"),
                "case_name": record.get("사건명"),
                "court_name": record.get("법원명"),
                "decision_date": record.get("선고일자"),
                "quality_passed": quality_passed,
                "quality_reason_codes": quality_reasons,
            }
        elif key in not_found:
            status = "SEED_UNRESOLVED_NOT_FOUND"
            counts["unresolved_not_found_count"] += 1
            registry = {
                **base,
                "seed_status": status,
                "internal_grade": None,
                "record_id": None,
                "quality_passed": False,
                "quality_reason_codes": ["LAW_API_EXACT_MATCH_NOT_FOUND"],
            }
            unresolved_rows.append(registry)
        elif key in ambiguous:
            status = "SEED_UNRESOLVED_AMBIGUOUS"
            counts["unresolved_ambiguous_count"] += 1
            candidates = ambiguous[key].get("candidates", [])
            registry = {
                **base,
                "seed_status": status,
                "internal_grade": None,
                "record_id": None,
                "candidate_count": len(candidates),
                "candidates": [
                    {
                        "record_id": candidate.get("판례일련번호"),
                        "case_number": candidate.get("사건번호"),
                        "case_name": candidate.get("사건명"),
                        "court_name": candidate.get("법원명"),
                        "decision_date": candidate.get("선고일자"),
                    }
                    for candidate in candidates
                ],
                "quality_passed": False,
                "quality_reason_codes": ["MULTIPLE_EXACT_LAW_API_MATCHES"],
            }
            unresolved_rows.append(registry)
        else:
            status = "SEED_MISSING_OUTCOME"
            counts["missing_outcome_count"] += 1
            registry = {
                **base,
                "seed_status": status,
                "internal_grade": None,
                "record_id": None,
                "quality_passed": False,
                "quality_reason_codes": ["NO_COLLECTION_OUTCOME"],
            }
            unresolved_rows.append(registry)

        registry_rows.append(registry)

    accounted_count = (
        counts["seed_ready_count"]
        + counts["unresolved_not_found_count"]
        + counts["unresolved_ambiguous_count"]
        + counts["collection_error_count"]
        + counts["missing_outcome_count"]
    )
    accounting_passed = (
        accounted_count == counts["unique_case_number_count"]
        and counts["outcome_overlap_count"] == 0
        and len({row["normalized_case_number"] for row in registry_rows})
        == len(registry_rows)
        and len(
            {
                str(
                    row.get("판례정보일련번호")
                    or row.get("판례일련번호")
                    or row.get("_case_id")
                )
                for row in ready_rows
            }
        )
        == len(ready_rows)
    )

    paths = {
        "registry": output_dir / "01_seed_registry.jsonl",
        "seed_ready": output_dir / "02_seed_ready_full_cases.jsonl",
        "unresolved": output_dir / "03_seed_unresolved.jsonl",
    }
    _write_jsonl(paths["registry"], registry_rows)
    _write_jsonl(paths["seed_ready"], ready_rows)
    _write_jsonl(paths["unresolved"], unresolved_rows)

    completed_at = datetime.now().isoformat(timespec="seconds")
    report = {
        "generated_at": completed_at,
        "registry_version": REGISTRY_VERSION,
        "inputs": input_manifest,
        "counts": counts,
        "accounting": {
            "accounted_count": accounted_count,
            "accounting_passed": accounting_passed,
        },
        "output_directory": str(output_dir),
    }
    report_path = output_dir / "04_seed_registry_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "run_id": output_dir.name,
        "stage": "01_seed_registry",
        "registry_version": REGISTRY_VERSION,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": "COMPLETED" if accounting_passed else "FAILED",
        "inputs": input_manifest,
        "counts": counts,
        "accounting_passed": accounting_passed,
        "outputs": {
            label: {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for label, path in paths.items()
        },
    }
    manifest["outputs"]["report"] = {
        "path": str(report_path),
        "bytes": report_path.stat().st_size,
        "sha256": _sha256(report_path),
    }
    (output_dir / "05_run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not accounting_passed:
        raise RuntimeError("시드 레지스트리 정산 또는 고유 ID 검증에 실패했습니다.")
    return report
