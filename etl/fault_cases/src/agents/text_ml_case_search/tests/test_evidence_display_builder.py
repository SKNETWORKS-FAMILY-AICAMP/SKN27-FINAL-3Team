from __future__ import annotations

from etl.fault_cases.src.agents.text_ml_case_search.builders.evidence_display_builder import (
    build_display_evidence,
)


def test_build_display_evidence_strips_highlight_tags_and_keeps_source_reference() -> None:
    display = build_display_evidence(
        evidence=[
            {
                "source_type": "review_case",
                "title": "sample case",
                "source_reference": "review_case_db:rc_001#chunk_001",
                "chunk_text": "This is a useful review case chunk about a signal intersection crash.",
                "metadata": {
                    "reference_chart_key": "249",
                    "decision_fault_ratio": "A 70 : B 30",
                    "highlight": {
                        "chunk_text": ["<em>signal</em> intersection crash"],
                    },
                },
            }
        ],
    )

    item = display[0]
    assert item["source_reference"] == "review_case_db:rc_001#chunk_001"
    assert item["reference_chart_key"] == "249"
    assert item["ratio_label"] == "A 70 : B 30"
    assert item["matched_snippets"] == ["signal intersection crash"]
    assert "<em>" not in item["matched_snippets"][0]


def test_build_display_evidence_uses_claimant_respondent_ratio_fallback() -> None:
    display = build_display_evidence(
        evidence=[
            {
                "source_type": "review_case",
                "title": "sample case",
                "source_reference": "review_case_db:rc_001#chunk_001",
                "chunk_text": "short chunk",
                "metadata": {
                    "claimant_final_ratio": "70",
                    "respondent_final_ratio": "30",
                },
            }
        ],
    )

    assert display[0]["ratio_label"] == "claimant 70 : respondent 30"


def test_build_display_evidence_truncates_long_summary() -> None:
    display = build_display_evidence(
        evidence=[
            {
                "source_type": "review_case",
                "title": "sample case",
                "source_reference": "review_case_db:rc_001#chunk_001",
                "chunk_text": "a" * 400,
                "metadata": {},
            }
        ],
        summary_chars=20,
    )

    assert display[0]["summary"] == "aaaaaaaaaaaaaaaaaaa..."


def test_build_display_evidence_marks_possible_encoding_issue() -> None:
    display = build_display_evidence(
        evidence=[
            {
                "source_type": "review_case",
                "title": "\uf9e1\uf9e7\uf92f",
                "source_reference": "review_case_db:rc_001#chunk_001",
                "chunk_text": "\uf9e1\uf9e7\uf92f broken text",
                "metadata": {},
            }
        ],
    )

    assert "text_encoding_review_required" in display[0]["display_warnings"]
