from __future__ import annotations

from copy import deepcopy


def test_detail_reports_missing_job_without_reading_progress() -> None:
    from app.services.analysis_job_query_service import load_analysis_job_detail

    progress_calls: list[str] = []

    outcome = load_analysis_job_detail(
        "job_missing",
        load_job=lambda _job_id: None,
        load_progress=lambda job_id: progress_calls.append(job_id),
    )

    assert outcome.kind == "not_found"
    assert outcome.payload == {}
    assert progress_calls == []


def test_detail_adds_progress_without_mutating_repository_record() -> None:
    from app.services.analysis_job_query_service import load_analysis_job_detail

    stored = {"job_id": "job_1", "status": "running", "metadata": {"attempt": 1}}
    original = deepcopy(stored)

    outcome = load_analysis_job_detail(
        "job_1",
        load_job=lambda _job_id: stored,
        load_progress=lambda _job_id: {"state": "running", "progress": 40},
    )

    assert outcome.kind == "detail"
    assert outcome.payload["job_id"] == "job_1"
    assert outcome.payload["progress_cache"] == {"state": "running", "progress": 40}
    assert stored == original


def test_pending_result_uses_the_v2_contract_without_calling_composer() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    composer_calls: list[dict[str, object]] = []

    outcome = load_analysis_result(
        "job_queued",
        load_job=lambda _job_id: {
            "job_id": "job_queued",
            "status": "queued",
            "work_item": {"id": "work_1", "state": "queued"},
            "progress_state": {"current": 1, "total": 3},
        },
        compose_response=lambda payload: composer_calls.append(payload),
    )

    assert outcome.kind == "pending"
    assert outcome.payload == {
        "contract_version": "analysis_result.v2",
        "job_id": "job_queued",
        "status": "queued",
        "assistant_message": None,
        "structured_results": {},
        "evidence": [],
        "limitations": [],
        "work_item": {"id": "work_1", "state": "queued"},
        "progress_state": {"current": 1, "total": 3},
    }
    assert composer_calls == []


def test_completed_result_normalizes_only_dict_agent_outputs_for_composer() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    captured: list[dict[str, object]] = []
    expected = {"contract_version": "analysis_result.v2", "status": "partial"}

    def compose(payload: dict[str, object]) -> dict[str, object]:
        captured.append(payload)
        return expected

    outcome = load_analysis_result(
        "job_done",
        load_job=lambda _job_id: {
            "job_id": "job_done",
            "status": "partial",
            "status_counts": {"success": 1, "failed": 1},
            "agent_results": [
                {"node_code": "law_ground_search", "status": "success"},
                "invalid",
                None,
            ],
        },
        compose_response=compose,
    )

    assert outcome.kind == "completed"
    assert outcome.payload is expected
    assert captured == [
        {
            "job_id": "job_done",
            "status_counts": {"success": 1, "failed": 1},
            "executions": [
                {
                    "node_code": "law_ground_search",
                    "agent_output": {
                        "node_code": "law_ground_search",
                        "status": "success",
                    },
                }
            ],
            "supervisor_state": {},
            "attachments": [],
        }
    ]


def test_completed_result_preserves_persisted_presentation_fields() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    composed = {"contract_version": "analysis_result.v2", "status": "completed"}
    outcome = load_analysis_result(
        "job_done",
        load_job=lambda _job_id: {
            "job_id": "job_done",
            "status": "completed",
            "cards": [{"title": "next step"}],
            "pending_questions": [{"question": "confirm facts"}],
            "report_links": [{"url": "/reports/report_1"}],
            "attachments": [{"attachment_id": "attachment_1"}],
            "reporting_payload": {"report_id": "report_1"},
            "supervisor_state": {"stage": "finalize"},
            "supervisor_execution": {"status": "success"},
            "work_item": {"id": "work_1", "state": "done"},
            "progress_state": {"current": 3, "total": 3},
        },
        compose_response=lambda _payload: composed,
    )

    assert outcome.kind == "completed"
    assert outcome.payload == {
        **composed,
        "cards": [{"title": "next step"}],
        "pending_questions": [{"question": "confirm facts"}],
        "report_links": [{"url": "/reports/report_1"}],
        "attachments": [{"attachment_id": "attachment_1"}],
        "reporting_payload": {"report_id": "report_1"},
        "supervisor_state": {"stage": "finalize"},
        "supervisor_execution": {"status": "success"},
        "work_item": {"id": "work_1", "state": "done"},
        "progress_state": {"current": 3, "total": 3},
    }


def test_completed_result_prepends_composed_deadline_card_to_persisted_cards() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    deadline_card = {
        "card_type": "deadline_guidance",
        "title": "deadline guidance",
        "status": "partial",
    }
    outcome = load_analysis_result(
        "job_deadline",
        load_job=lambda _job_id: {
            "job_id": "job_deadline",
            "status": "partial",
            "cards": [{"card_type": "verified_agent_result", "title": "law result"}],
            "agent_results": [],
        },
        compose_response=lambda _payload: {
            "contract_version": "analysis_result.v2",
            "status": "partial",
            "deadline_guidance": {
                "contract_version": "deadline_guidance.v1",
                "status": "due_soon",
            },
            "cards": [deadline_card],
        },
    )

    assert outcome.payload["deadline_guidance"]["status"] == "due_soon"
    assert outcome.payload["cards"] == [
        deadline_card,
        {"card_type": "verified_agent_result", "title": "law result"},
    ]


def test_completed_result_uses_canonical_persisted_terminal_status() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    outcome = load_analysis_result(
        "job_blocked",
        load_job=lambda _job_id: {
            "job_id": "job_blocked",
            "status": "failed",
            "status_counts": {"success": 2, "failed": 1},
            "agent_results": [
                {"node_code": "fine_notice_analysis", "status": "success"},
                {"node_code": "law_ground_search", "status": "failed"},
            ],
        },
        compose_response=lambda _payload: {
            "contract_version": "analysis_result.v2",
            "status": "partial",
        },
    )

    assert outcome.kind == "completed"
    assert outcome.payload["status"] == "failed"


def test_result_reports_missing_job_without_calling_composer() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    composer_calls: list[dict[str, object]] = []

    outcome = load_analysis_result(
        "job_missing",
        load_job=lambda _job_id: None,
        compose_response=lambda payload: composer_calls.append(payload),
    )

    assert outcome.kind == "not_found"
    assert outcome.payload == {}
    assert composer_calls == []
