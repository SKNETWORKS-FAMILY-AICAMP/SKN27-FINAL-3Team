from __future__ import annotations

from etl.fault_cases.src.agents.text_ml_case_search.rag.evidence_validator import (
    build_evidence_validation_report,
    validate_evidence,
    validate_evidence_item,
)


def _valid_evidence(chunk_text: str = "충분한 길이의 심의사례 근거 본문입니다.") -> dict:
    return {
        "source_type": "review_case",
        "source_reference": "review_case_db:rc_001#chunk_001",
        "metadata": {"case_id": "rc_001"},
        "chunk_text": chunk_text,
    }


def test_validate_evidence_item_accepts_valid_item() -> None:
    result = validate_evidence_item(
        item=_valid_evidence("신호 없는 교차로에서 직진 차량과 우측 진입 차량이 충돌한 심의사례 근거 본문입니다."),
        min_text_len=20,
    )

    assert result["is_valid"] is True
    assert result["invalid_reasons"] == []
    validation = result["item"]["metadata"]["validation"]
    assert validation["is_valid"] is True
    assert validation["min_text_len"] == 20


def test_validate_evidence_item_rejects_missing_required_fields() -> None:
    result = validate_evidence_item(
        item={
            "source_type": "",
            "source_reference": "",
            "chunk_text": "",
        },
        min_text_len=20,
    )

    assert result["is_valid"] is False
    assert "source_type_missing" in result["invalid_reasons"]
    assert "source_reference_missing" in result["invalid_reasons"]
    assert "metadata_missing" in result["invalid_reasons"]
    assert "chunk_text_missing" in result["invalid_reasons"]


def test_validate_evidence_item_rejects_short_chunk_text() -> None:
    result = validate_evidence_item(item=_valid_evidence("짧음"), min_text_len=20)

    assert result["is_valid"] is False
    assert result["invalid_reasons"] == ["chunk_text_too_short"]
    assert result["item"]["metadata"]["validation"]["chunk_text_len"] == 2


def test_validate_evidence_filters_invalid_items() -> None:
    evidence = validate_evidence(
        evidence=[
            _valid_evidence("충분한 길이의 심의사례 근거 본문입니다."),
            _valid_evidence("짧음"),
            {"source_type": "review_case", "source_reference": "", "metadata": {}, "chunk_text": "충분한 본문"},
        ],
        min_text_len=10,
    )

    assert len(evidence) == 1
    assert evidence[0]["metadata"]["validation"]["is_valid"] is True


def test_build_evidence_validation_report_counts_reasons() -> None:
    report = build_evidence_validation_report(
        evidence=[
            _valid_evidence("충분한 길이의 심의사례 근거 본문입니다."),
            _valid_evidence("짧음"),
            {"source_type": "", "source_reference": "", "chunk_text": ""},
        ],
        min_text_len=10,
    )

    assert report["input_count"] == 3
    assert report["valid_count"] == 1
    assert report["invalid_count"] == 2
    assert report["invalid_reason_counts"]["chunk_text_too_short"] == 1
    assert report["invalid_reason_counts"]["source_type_missing"] == 1
    assert report["invalid_reason_counts"]["source_reference_missing"] == 1
