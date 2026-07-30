"""빈 상세 판례만 재수집하고 정상 판례 파일을 안전하게 통합합니다."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from .validation import (
    VALIDATION_VERSION,
    sha256_file,
    validate_detail_record,
    visible_text,
)


RETRY_VERSION = "empty_detail_retry_v1.0.0"


class DetailClient(Protocol):
    def fetch_detail(self, case_id: str) -> dict[str, Any]:
        """판례정보일련번호로 상세 판례를 반환합니다."""


def _write_json_line(stream: Any, row: dict[str, Any]) -> None:
    stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _record_id(record: dict[str, Any]) -> str:
    return visible_text(
        record.get("판례정보일련번호")
        or record.get("판례일련번호")
        or record.get("_case_id")
    )


def _merge_recovered_detail(
    original: dict[str, Any],
    detail: dict[str, Any],
    attempts_used: int,
) -> dict[str, Any]:
    merged = {
        key: value
        for key, value in original.items()
        if key != "_collection_validation"
    }
    merged.update(detail)
    merged["_case_id"] = original.get("_case_id") or _record_id(original)
    merged["_requested_case_number"] = (
        original.get("_requested_case_number")
        or original.get("사건번호")
        or ""
    )
    merged["_collection_retry"] = {
        "version": RETRY_VERSION,
        "status": "RECOVERED",
        "attempts_used": attempts_used,
    }
    validation = validate_detail_record(merged)
    merged["_collection_validation"] = {
        "version": VALIDATION_VERSION,
        "category": validation.category,
        "reason_codes": list(validation.reason_codes),
        "record_id": validation.record_id,
        "case_number": validation.case_number,
        "usable_text_fields": list(validation.usable_text_fields),
    }
    return merged


def _retry_one_record(
    original: dict[str, Any],
    line_number: int,
    client: DetailClient,
    max_attempts: int,
) -> tuple[str, dict[str, Any]]:
    """레코드 한 건을 재수집하고 배타적인 결과 하나를 반환합니다."""

    case_id = _record_id(original)
    final_error: Exception | None = None
    final_merged: dict[str, Any] | None = None
    attempts_used = 0

    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
        try:
            detail = client.fetch_detail(case_id)
            merged = _merge_recovered_detail(
                original,
                detail,
                attempts_used=attempt,
            )
            final_merged = merged
            if merged["_collection_validation"]["category"] == "valid":
                break
        except Exception as exc:  # noqa: BLE001
            final_error = exc

    if (
        final_merged is not None
        and final_merged["_collection_validation"]["category"] == "valid"
    ):
        return "recovered", final_merged

    if final_merged is not None:
        persistent = dict(final_merged)
        persistent["_collection_retry"] = {
            "version": RETRY_VERSION,
            "status": "STILL_EMPTY",
            "attempts_used": attempts_used,
        }
        return "still_empty", persistent

    return (
        "retry_error",
        {
            "line_number": line_number,
            "record_id": case_id,
            "case_number": (
                original.get("_requested_case_number")
                or original.get("사건번호")
            ),
            "attempts_used": attempts_used,
            "error_type": (
                type(final_error).__name__
                if final_error is not None
                else "UnknownError"
            ),
            "message": (
                str(final_error)
                if final_error is not None
                else "상세 응답을 얻지 못했습니다."
            ),
        },
    )


def retry_empty_detail_file(
    empty_input_path: Path,
    valid_input_path: Path,
    output_dir: Path,
    client: DetailClient,
    max_attempts: int = 2,
    max_workers: int = 1,
    progress_every: int = 50,
) -> dict[str, Any]:
    """빈 원문을 재수집하고 기존 정상 원문과 회복 원문을 하나로 통합합니다."""

    if max_attempts < 1:
        raise ValueError("max_attempts는 1 이상이어야 합니다.")
    if not 1 <= max_workers <= 8:
        raise ValueError("max_workers는 1 이상 8 이하여야 합니다.")

    empty_input_path = empty_input_path.resolve()
    valid_input_path = valid_input_path.resolve()
    output_dir = output_dir.resolve()
    if not empty_input_path.is_file():
        raise FileNotFoundError(f"빈 원문 입력 파일이 없습니다: {empty_input_path}")
    if not valid_input_path.is_file():
        raise FileNotFoundError(f"정상 원문 입력 파일이 없습니다: {valid_input_path}")
    output_dir.mkdir(parents=True, exist_ok=False)

    paths = {
        "recovered": output_dir / "01_recovered_details.jsonl",
        "still_empty": output_dir / "02_still_empty_details.jsonl",
        "retry_error": output_dir / "03_retry_errors.jsonl",
        "consolidated_valid": (
            output_dir / "04_valid_general_precedents_after_retry.jsonl"
        ),
    }
    report_path = output_dir / "05_retry_report.json"
    manifest_path = output_dir / "06_run_manifest.json"
    started_at = datetime.now().isoformat(timespec="seconds")
    input_manifest = {
        "empty_detail": {
            "path": str(empty_input_path),
            "bytes": empty_input_path.stat().st_size,
            "sha256": sha256_file(empty_input_path),
        },
        "valid": {
            "path": str(valid_input_path),
            "bytes": valid_input_path.stat().st_size,
            "sha256": sha256_file(valid_input_path),
        },
    }
    manifest: dict[str, Any] = {
        "run_id": output_dir.name,
        "stage": "02_general_collection_empty_detail_retry",
        "retry_version": RETRY_VERSION,
        "started_at": started_at,
        "completed_at": None,
        "status": "RUNNING",
        "max_attempts": max_attempts,
        "max_workers": max_workers,
        "inputs": input_manifest,
        "outputs": {},
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    counts = {
        "empty_input_count": 0,
        "recovered_count": 0,
        "still_empty_count": 0,
        "retry_error_count": 0,
        "base_valid_count": 0,
        "consolidated_valid_count": 0,
        "duplicate_id_count": 0,
    }
    recovered_rows: list[dict[str, Any]] = []
    empty_rows: list[tuple[int, dict[str, Any]]] = []
    with empty_input_path.open("r", encoding="utf-8") as source:
        for line_number, raw_line in enumerate(source, 1):
            if raw_line.strip():
                empty_rows.append((line_number, json.loads(raw_line)))

    handles = {
        key: path.open("w", encoding="utf-8", newline="\n")
        for key, path in paths.items()
        if key != "consolidated_valid"
    }
    try:
        def process_item(
            item: tuple[int, dict[str, Any]],
        ) -> tuple[str, dict[str, Any]]:
            line_number, original = item
            return _retry_one_record(
                original=original,
                line_number=line_number,
                client=client,
                max_attempts=max_attempts,
            )

        if max_workers == 1:
            results = map(process_item, empty_rows)
            executor = None
        else:
            executor = ThreadPoolExecutor(max_workers=max_workers)
            results = executor.map(process_item, empty_rows)

        try:
            for category, result_row in results:
                counts["empty_input_count"] += 1
                counts[f"{category}_count"] += 1
                if category == "recovered":
                    recovered_rows.append(result_row)
                _write_json_line(handles[category], result_row)

                if (
                    progress_every > 0
                    and counts["empty_input_count"] % progress_every == 0
                ):
                    print(
                        "빈 원문 재수집 진행: "
                        f"{counts['empty_input_count']}건 처리, "
                        f"회복 {counts['recovered_count']}, "
                        f"빈 원문 유지 {counts['still_empty_count']}, "
                        f"오류 {counts['retry_error_count']}",
                        flush=True,
                    )
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=False)
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

    base_ids: set[str] = set()
    with (
        valid_input_path.open("r", encoding="utf-8") as base_source,
        paths["consolidated_valid"].open(
            "w", encoding="utf-8", newline="\n"
        ) as consolidated,
    ):
        for raw_line in base_source:
            if not raw_line.strip():
                continue
            row = json.loads(raw_line)
            row_id = _record_id(row)
            if row_id in base_ids:
                counts["duplicate_id_count"] += 1
                continue
            base_ids.add(row_id)
            counts["base_valid_count"] += 1
            counts["consolidated_valid_count"] += 1
            consolidated.write(raw_line.rstrip("\r\n") + "\n")

        for row in recovered_rows:
            row_id = _record_id(row)
            if row_id in base_ids:
                counts["duplicate_id_count"] += 1
                continue
            base_ids.add(row_id)
            counts["consolidated_valid_count"] += 1
            _write_json_line(consolidated, row)

    retry_accounted = (
        counts["recovered_count"]
        + counts["still_empty_count"]
        + counts["retry_error_count"]
    )
    accounting_passed = (
        retry_accounted == counts["empty_input_count"]
        and counts["duplicate_id_count"] == 0
        and counts["consolidated_valid_count"]
        == counts["base_valid_count"] + counts["recovered_count"]
    )
    completed_at = datetime.now().isoformat(timespec="seconds")
    report = {
        "generated_at": completed_at,
        "retry_version": RETRY_VERSION,
        "max_attempts": max_attempts,
        "max_workers": max_workers,
        "inputs": input_manifest,
        "counts": counts,
        "accounting": {
            "retry_accounted_count": retry_accounted,
            "retry_accounting_passed": (
                retry_accounted == counts["empty_input_count"]
            ),
            "consolidated_accounting_passed": (
                counts["consolidated_valid_count"]
                == counts["base_valid_count"] + counts["recovered_count"]
            ),
            "duplicate_check_passed": counts["duplicate_id_count"] == 0,
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
        for key, path in paths.items()
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
        raise RuntimeError("재수집 결과 정산 또는 중복 검증에 실패했습니다.")
    return report
