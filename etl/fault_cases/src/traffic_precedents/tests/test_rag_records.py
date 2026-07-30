from __future__ import annotations

from etl.fault_cases.src.traffic_precedents.rag_records.builder import (
    build_rag_records,
)
from etl.fault_cases.src.traffic_precedents.rag_records.validator import (
    validate_rag_records,
)


def test_builder_uses_only_direct_and_eligible_seed_evidence() -> None:
    cases = [
        {
            "판례정보일련번호": "1",
            "사건번호": "2024다1",
            "사건명": "직접",
            "법원명": "대법원",
            "선고일자": "20240101",
            "full_text": "사고 사실 법원 판단",
        },
        {
            "판례정보일련번호": "2",
            "사건번호": "2024다2",
            "사건명": "법리",
            "법원명": "대법원",
            "선고일자": "20240102",
            "full_text": "법리",
        },
        {
            "판례정보일련번호": "3",
            "사건번호": "2024다3",
            "사건명": "씨드",
            "법원명": "대법원",
            "선고일자": "20240103",
            "full_text": "씨드 사고",
        },
    ]
    blocks = [
        {
            "record_id": "1",
            "block_id": "b1",
            "block_type": "ACCIDENT_FACT",
            "semantic_role": "ACCIDENT_FACT",
            "text": "사고 사실",
            "start_offset": 0,
            "end_offset": 5,
            "is_valid_evidence": True,
        },
        {
            "record_id": "2",
            "block_id": "b2",
            "block_type": "GENERAL_LEGAL_PRINCIPLE",
            "semantic_role": "GENERAL_LEGAL_PRINCIPLE",
            "text": "법리",
            "start_offset": 0,
            "end_offset": 2,
            "is_valid_evidence": True,
        },
        {
            "record_id": "3",
            "block_id": "b3",
            "block_type": "ACCIDENT_FACT",
            "semantic_role": "ACCIDENT_FACT",
            "text": "씨드 사고",
            "start_offset": 0,
            "end_offset": 5,
            "is_valid_evidence": True,
        },
    ]
    classifications = [
        {
            "record_id": "1",
            "internal_grade": "GENERAL_READY_DIRECT",
            "evidence_block_ids": {"accident_fact": ["b1"]},
            "classifier_version": "c1",
            "validation": {"status": "PASSED", "validator_version": "v1"},
        },
        {
            "record_id": "2",
            "internal_grade": "GENERAL_READY_LEGAL_SUPPORT",
            "evidence_block_ids": {"legal": ["b2"]},
            "classifier_version": "c1",
            "validation": {"status": "PASSED", "validator_version": "v1"},
        },
        {
            "record_id": "3",
            "internal_grade": "SEED_READY",
            "evidence_block_ids": {"accident_fact": ["b3"]},
            "classifier_version": "c1",
            "validation": {"status": "PASSED", "validator_version": "v1"},
        },
    ]
    records = build_rag_records(cases, blocks, classifications)
    assert [row["block_id"] for row in records] == ["b1", "b3"]
    report = validate_rag_records(records, expected_blocks=2, expected_cases=2)
    assert report["status"] == "PASSED"
