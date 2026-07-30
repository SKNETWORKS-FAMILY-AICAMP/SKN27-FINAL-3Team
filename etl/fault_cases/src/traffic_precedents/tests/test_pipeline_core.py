from __future__ import annotations

from etl.fault_cases.src.traffic_precedents.classification.validator import (
    validate_classification,
)
from etl.fault_cases.src.traffic_precedents.collection.validate import (
    validate_collected_records,
)
from etl.fault_cases.src.traffic_precedents.preprocessing.cleaner import clean_text
from etl.fault_cases.src.traffic_precedents.preprocessing.merger import (
    merge_duplicate_precedents,
)
from etl.fault_cases.src.traffic_precedents.semantic_blocks.parser import (
    parse_semantic_blocks,
)


def test_collection_validation_rejects_duplicate_ids() -> None:
    report = validate_collected_records(
        [
            {"판례정보일련번호": "1", "판례내용": "본문"},
            {"판례정보일련번호": "1", "판례내용": "다른 본문"},
        ]
    )
    assert report["status"] == "FAILED"
    assert report["duplicate_record_ids"] == ["1"]


def test_preprocessing_cleans_html_and_merges_verified_duplicate() -> None:
    assert clean_text("  사고<br>내용&nbsp; ") == "사고 내용"
    representative, merged = merge_duplicate_precedents(
        [
            {
                "판례정보일련번호": "1",
                "사건번호": "2024다1",
                "법원명": "대법원",
                "선고일자": "20240101",
                "판례내용": "교통사고가 발생하였다.",
                "_source_route": "GENERAL",
            },
            {
                "판례정보일련번호": "2",
                "사건번호": "2024다1",
                "법원명": "대법원",
                "선고일자": "20240101",
                "판례내용": "교통사고가 발생하였다.",
                "_source_route": "SEED_READY",
            },
        ]
    )
    assert len(representative) == 1
    assert len(merged) == 1


def test_semantic_blocks_keep_offsets_in_full_text() -> None:
    record = {
        "판례정보일련번호": "1",
        "사건명": "손해배상(자)",
        "full_text": "교차로에서 차량이 충돌하였다. 법원은 원고 과실을 20%로 판단한다.",
        "body_text": "교차로에서 차량이 충돌하였다. 법원은 원고 과실을 20%로 판단한다.",
        "reason_text": "교차로에서 차량이 충돌하였다. 법원은 원고 과실을 20%로 판단한다.",
        "section_offsets": {"REASON": {"start": 0, "end": 40}},
    }
    blocks = parse_semantic_blocks(record)
    assert blocks
    for block in blocks:
        row = block.to_dict()
        assert record["full_text"][row["start_offset"] : row["end_offset"]].strip()


def test_independent_validator_accepts_direct_invariants() -> None:
    result = {
        "internal_grade": "GENERAL_READY_DIRECT",
        "source_route": "GENERAL",
        "main_issue": "ROAD_TRAFFIC_FAULT",
        "gates": {
            "E_actual_road_traffic_fact": True,
            "F_court_fault_decision": True,
            "G_fact_decision_link": True,
            "H_target_main_issue": True,
        },
        "evidence_block_ids": {
            "accident_fact": ["b1"],
            "fault_decision": ["b2"],
        },
        "search_safety": {"selected_ratio_contexts": {}},
    }
    assert validate_classification(result)["status"] == "PASSED"
