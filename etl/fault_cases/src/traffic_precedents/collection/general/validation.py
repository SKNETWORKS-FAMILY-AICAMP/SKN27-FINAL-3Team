"""일반 판례 상세 수집 결과의 완전성을 스트리밍 검증합니다."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO


VALIDATION_VERSION = "collection_detail_v1.0.0"
MAIN_TEXT_FIELDS = ("판례내용", "판시사항", "판결요지")
HTML_TAG_RE = re.compile(r"<[^>]*>")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class RecordValidation:
    """레코드 한 건의 배타적인 검증 결과."""

    category: str
    reason_codes: tuple[str, ...]
    record_id: str
    case_number: str
    usable_text_fields: tuple[str, ...]


def visible_text(value: Any) -> str:
    """HTML 태그와 공백을 제외하고 사람이 읽을 수 있는 텍스트를 반환합니다."""

    if value is None:
        return ""
    text = html.unescape(str(value))
    text = HTML_TAG_RE.sub(" ", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def validate_detail_record(record: dict[str, Any]) -> RecordValidation:
    """상세 판례를 valid, empty_detail, invalid_metadata 중 하나로 판정합니다."""

    record_id = visible_text(
        record.get("판례정보일련번호")
        or record.get("판례일련번호")
        or record.get("_case_id")
    )
    case_number = visible_text(
        record.get("사건번호") or record.get("_requested_case_number")
    )
    usable_fields = tuple(
        field for field in MAIN_TEXT_FIELDS if visible_text(record.get(field))
    )

    missing_reasons: list[str] = []
    if not record_id:
        missing_reasons.append("MISSING_RECORD_ID")
    if not case_number:
        missing_reasons.append("MISSING_CASE_NUMBER")

    if missing_reasons:
        return RecordValidation(
            category="invalid_metadata",
            reason_codes=tuple(missing_reasons),
            record_id=record_id,
            case_number=case_number,
            usable_text_fields=usable_fields,
        )

    if not usable_fields:
        return RecordValidation(
            category="empty_detail",
            reason_codes=("ALL_MAIN_TEXT_FIELDS_EMPTY",),
            record_id=record_id,
            case_number=case_number,
            usable_text_fields=(),
        )

    return RecordValidation(
        category="valid",
        reason_codes=("DETAIL_TEXT_PRESENT",),
        record_id=record_id,
        case_number=case_number,
        usable_text_fields=usable_fields,
    )


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """대용량 파일을 메모리에 올리지 않고 SHA-256을 계산합니다."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_line(stream: TextIO, row: dict[str, Any]) -> None:
    stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _validated_row(
    record: dict[str, Any],
    validation: RecordValidation,
) -> dict[str, Any]:
    result = dict(record)
    result["_collection_validation"] = {
        "version": VALIDATION_VERSION,
        "category": validation.category,
        "reason_codes": list(validation.reason_codes),
        "record_id": validation.record_id,
        "case_number": validation.case_number,
        "usable_text_fields": list(validation.usable_text_fields),
    }
    return result


def validate_jsonl_file(input_path: Path, output_dir: Path) -> dict[str, Any]:
    """JSONL 전체를 스트리밍 검증하고 배타적인 결과 파일과 보고서를 만듭니다."""

    input_path = input_path.resolve()
    output_dir = output_dir.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"입력 JSONL이 없습니다: {input_path}")

    output_dir.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now().isoformat(timespec="seconds")

    output_paths = {
        "valid": output_dir / "01_valid_general_precedents.jsonl",
        "empty_detail": output_dir / "02_empty_detail_records.jsonl",
        "invalid_metadata": output_dir / "03_invalid_metadata_records.jsonl",
        "validation_error": output_dir / "04_validation_errors.jsonl",
    }
    report_path = output_dir / "05_validation_report.json"
    manifest_path = output_dir / "06_run_manifest.json"

    input_manifest = {
        "path": str(input_path),
        "bytes": input_path.stat().st_size,
        "sha256": sha256_file(input_path),
    }
    counts = {
        "physical_line_count": 0,
        "blank_line_count": 0,
        "json_record_count": 0,
        "valid_count": 0,
        "empty_detail_count": 0,
        "invalid_metadata_count": 0,
        "validation_error_count": 0,
    }

    manifest: dict[str, Any] = {
        "run_id": output_dir.name,
        "stage": "02_general_collection_validation",
        "validation_version": VALIDATION_VERSION,
        "started_at": started_at,
        "completed_at": None,
        "status": "RUNNING",
        "input": input_manifest,
        "outputs": {},
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    handles = {
        key: path.open("w", encoding="utf-8", newline="\n")
        for key, path in output_paths.items()
    }
    try:
        with input_path.open("r", encoding="utf-8") as source:
            for line_number, raw_line in enumerate(source, 1):
                counts["physical_line_count"] += 1
                stripped = raw_line.strip()
                if not stripped:
                    counts["blank_line_count"] += 1
                    continue

                try:
                    record = json.loads(stripped)
                    if not isinstance(record, dict):
                        raise TypeError(
                            f"JSON 객체가 아니라 {type(record).__name__}입니다."
                        )
                except (json.JSONDecodeError, TypeError) as exc:
                    counts["validation_error_count"] += 1
                    _write_json_line(
                        handles["validation_error"],
                        {
                            "line_number": line_number,
                            "error_type": type(exc).__name__,
                            "message": str(exc),
                            "raw_preview": stripped[:500],
                        },
                    )
                    continue

                counts["json_record_count"] += 1
                validation = validate_detail_record(record)
                _write_json_line(
                    handles[validation.category],
                    _validated_row(record, validation),
                )
                counts[f"{validation.category}_count"] += 1
    except Exception:
        manifest["status"] = "FAILED"
        manifest["completed_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["counts"] = counts
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        for stream in handles.values():
            stream.close()

    accounted_nonblank = (
        counts["valid_count"]
        + counts["empty_detail_count"]
        + counts["invalid_metadata_count"]
        + counts["validation_error_count"]
    )
    nonblank_line_count = (
        counts["physical_line_count"] - counts["blank_line_count"]
    )
    json_category_count = (
        counts["valid_count"]
        + counts["empty_detail_count"]
        + counts["invalid_metadata_count"]
    )
    accounting_passed = (
        accounted_nonblank == nonblank_line_count
        and json_category_count == counts["json_record_count"]
    )

    completed_at = datetime.now().isoformat(timespec="seconds")
    report = {
        "generated_at": completed_at,
        "validation_version": VALIDATION_VERSION,
        "input": input_manifest,
        "criteria": {
            "required_identity": [
                "판례정보일련번호|판례일련번호|_case_id",
                "사건번호|_requested_case_number",
            ],
            "required_any_visible_text_field": list(MAIN_TEXT_FIELDS),
            "html_only_text_is_empty": True,
        },
        "counts": counts,
        "accounting": {
            "nonblank_line_count": nonblank_line_count,
            "accounted_nonblank_count": accounted_nonblank,
            "json_category_count": json_category_count,
            "accounting_passed": accounting_passed,
        },
        "output_directory": str(output_dir),
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest["completed_at"] = completed_at
    manifest["status"] = "COMPLETED" if accounting_passed else "FAILED"
    manifest["counts"] = counts
    manifest["accounting_passed"] = accounting_passed
    manifest["outputs"] = {
        key: {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for key, path in output_paths.items()
    }
    manifest["outputs"]["report"] = {
        "path": str(report_path),
        "bytes": report_path.stat().st_size,
        "sha256": sha256_file(report_path),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if not accounting_passed:
        raise RuntimeError("수집 완전성 정산식이 맞지 않아 실행을 실패 처리했습니다.")
    return report
