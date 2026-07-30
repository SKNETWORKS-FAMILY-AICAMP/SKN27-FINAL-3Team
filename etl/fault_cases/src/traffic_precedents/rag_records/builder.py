from __future__ import annotations

from typing import Any, Iterable

from ..contracts import record_id_of
from .contracts import ALLOWED_GRADES, FORBIDDEN_ROLES


def _evidence_ids(classification: dict[str, Any]) -> set[str]:
    groups = classification.get("evidence_block_ids") or {}
    return {
        str(block_id)
        for block_ids in groups.values()
        for block_id in (block_ids or [])
        if str(block_id)
    }


def build_rag_records(
    cases: Iterable[dict[str, Any]],
    blocks: Iterable[dict[str, Any]],
    classifications: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    cases_by_id = {record_id_of(row): row for row in cases}
    blocks_by_id = {str(row.get("block_id") or ""): row for row in blocks}
    output: list[dict[str, Any]] = []
    for classification in classifications:
        record_id = str(classification.get("record_id") or "")
        grade = str(classification.get("internal_grade") or "")
        validation = classification.get("validation") or {}
        if grade not in ALLOWED_GRADES or validation.get("status") != "PASSED":
            continue
        case = cases_by_id.get(record_id)
        if case is None:
            raise ValueError(f"case missing for classification: {record_id}")
        for block_id in sorted(_evidence_ids(classification)):
            block = blocks_by_id.get(block_id)
            if block is None:
                raise ValueError(f"evidence block missing: {block_id}")
            if str(block.get("record_id") or "") != record_id:
                raise ValueError(f"evidence block case mismatch: {block_id}")
            if block.get("is_valid_evidence") is not True:
                continue
            if str(block.get("semantic_role") or "") in FORBIDDEN_ROLES:
                continue
            output.append(
                {
                    **block,
                    "retrieval_document_id": block_id,
                    "record_id": record_id,
                    "internal_grade": grade,
                    "validator_status": validation["status"],
                    "classifier_version": classification.get("classifier_version"),
                    "validator_version": validation.get("validator_version"),
                    "case_number": case.get("case_number") or case.get("사건번호"),
                    "case_name": case.get("case_name") or case.get("사건명"),
                    "court_name": case.get("court_name") or case.get("법원명"),
                    "decision_date": case.get("decision_date") or case.get("선고일자"),
                }
            )
    return sorted(output, key=lambda row: (str(row["record_id"]), str(row["block_id"])))
