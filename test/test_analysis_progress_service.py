from __future__ import annotations

import pytest

from app.services.analysis_progress_service import build_analysis_progress


def test_queued_job_exposes_non_terminal_polling_contract() -> None:
    progress = build_analysis_progress(
        {
            "job_id": "job_queued",
            "status": "queued",
            "work_item": {
                "work_item_id": "awork_job_queued",
                "status": "queued",
            },
        }
    )

    assert progress == {
        "contract_version": "analysis_progress.v1",
        "semantic_status": "queued",
        "terminal": False,
        "retryable": True,
        "next_action": "continue_polling",
        "user_message": (
            "분석 요청이 대기 중입니다. 순서가 되면 자동으로 진행됩니다."
        ),
        "job_id": "job_queued",
        "correlation_id": "awork_job_queued",
    }


def test_retrying_work_item_keeps_running_semantics() -> None:
    progress = build_analysis_progress(
        {
            "job_id": "job_retrying",
            "status": "running",
            "work_item": {
                "work_item_id": "awork_job_retrying",
                "status": "retrying",
            },
        }
    )

    assert progress["semantic_status"] == "running"
    assert progress["terminal"] is False
    assert progress["retryable"] is True
    assert progress["next_action"] == "continue_polling"


@pytest.mark.parametrize(
    "needs_input",
    [
        {"pending_questions": [{"field": "incident_date", "question": "언제인가요?"}]},
        {
            "supervisor_state": {
                "fact_conflicts": [
                    {
                        "field": "signal_priority",
                        "candidates": [
                            {
                                "value": "녹색",
                                "source_message_id": "msg_1",
                                "confidence": 0.9,
                            },
                            {
                                "value": "적색",
                                "source_message_id": "msg_1",
                                "confidence": 0.8,
                            },
                        ],
                    }
                ]
            }
        },
        {
            "attachment_workflows": [
                {
                    "contract_version": "attachment_workflow.v1",
                    "attachment_id": "att_1",
                    "state": "ocr_needs_confirmation",
                    "next_action": "confirm_ocr_fields",
                    "retryable": False,
                    "missing_fields": ["response_deadline"],
                    "limitations": [],
                }
            ]
        },
    ],
)
def test_terminal_confirmation_requirement_is_needs_input(
    needs_input: dict[str, object],
) -> None:
    progress = build_analysis_progress(
        {
            "job_id": "job_needs_input",
            "status": "partial",
            **needs_input,
        }
    )

    assert progress["semantic_status"] == "needs_input"
    assert progress["terminal"] is True
    assert progress["retryable"] is False
    assert progress["next_action"] == "provide_requested_input"


def test_failed_job_retries_only_when_server_explicitly_allows_it() -> None:
    not_retryable = build_analysis_progress(
        {"job_id": "job_failed", "status": "failed"}
    )
    retryable = build_analysis_progress(
        {
            "job_id": "job_failed_retryable",
            "status": "failed",
            "progress_state": {"retryable": True},
        }
    )

    assert not_retryable["semantic_status"] == "failed"
    assert not_retryable["retryable"] is False
    assert retryable["semantic_status"] == "failed"
    assert retryable["retryable"] is True
    assert retryable["next_action"] == "retry_polling"


def test_partial_result_preserves_explicit_domain_retryability() -> None:
    progress = build_analysis_progress(
        {
            "job_id": "job_partial",
            "status": "partial",
            "attachment_workflows": [
                {
                    "state": "partial",
                    "retryable": True,
                }
            ],
        }
    )

    assert progress["semantic_status"] == "partial"
    assert progress["retryable"] is True
    assert progress["next_action"] == "retry_polling"


def test_worker_success_without_user_result_is_semantic_partial() -> None:
    progress = build_analysis_progress(
        {
            "job_id": "job_worker_only",
            "status": "success",
            "work_item": {
                "work_item_id": "awork_job_worker_only",
                "status": "success",
            },
        },
        composed_result={},
    )

    assert progress["semantic_status"] == "partial"
    assert progress["terminal"] is True
    assert progress["retryable"] is False
    assert progress["user_message"] != "분석이 완료되었습니다."


@pytest.mark.parametrize(
    "user_result",
    [
        {"assistant_message": {"answer": "확인된 분석 결과입니다."}},
        {"structured_results": {"law_ground_search": {"matched_laws": []}}},
        {"cards": [{"card_type": "verified_agent_result"}]},
        {"report_links": [{"report_id": "rep_1", "action": "detail"}]},
    ],
)
def test_canonical_success_requires_actual_user_result(
    user_result: dict[str, object],
) -> None:
    progress = build_analysis_progress(
        {"job_id": "job_success", "status": "success"},
        composed_result=user_result,
    )

    assert progress["semantic_status"] == "success"
    assert progress["terminal"] is True
    assert progress["retryable"] is False
    assert progress["next_action"] == "review_result"


def test_unknown_status_fails_closed_and_drops_malformed_identifiers() -> None:
    progress = build_analysis_progress(
        {
            "job_id": "https://private.example/job",
            "status": "mystery",
            "work_item": {
                "work_item_id": "C:\\private\\work-item",
                "status": "success",
            },
        }
    )

    assert progress["semantic_status"] == "failed"
    assert progress["terminal"] is True
    assert progress["retryable"] is False
    assert progress["job_id"] is None
    assert progress["correlation_id"] is None
    assert "private" not in progress["user_message"]
