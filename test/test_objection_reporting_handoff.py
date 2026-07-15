from __future__ import annotations

from ai.agents.objection_report_generation import run_objection_report_generation
from app.services.supervisor_reporting_handoff_service import (
    build_supervisor_reporting_handoff,
)


def _persisted_result(node_code: str, structured_result: dict) -> dict:
    return {
        "result_id": f"res_handoff_{node_code}",
        "node_code": node_code,
        "status": "success",
        "summary": f"persisted {node_code}",
        "structured_result": structured_result,
        "evidence": [{"source_type": "database", "source_reference": node_code}],
        "next_actions": [],
        "limitations": [],
    }


def _handoff() -> dict:
    return build_supervisor_reporting_handoff(
        job={
            "job_id": "job_handoff_report",
            "session_id": "ses_handoff_report",
            "message_id": "msg_handoff_report",
            "analysis_plan_id": "plan_handoff_report",
            "routing_intent": "fine_notice_objection",
        },
        results=[
            _persisted_result(
                "fine_notice_analysis",
                {
                    "notice_fields": {
                        "agency": "Persisted Agency",
                        "violation_text": "persisted violation",
                    },
                    "required_documents": ["notice"],
                },
            ),
            _persisted_result(
                "law_ground_search",
                {
                    "matched_laws": [
                        {
                            "law_name": "Road Traffic Act",
                            "article": "Article 1",
                            "summary": "Persisted legal ground",
                            "source_reference": "law:1",
                        }
                    ]
                },
            ),
            _persisted_result(
                "appeal_decision_flow",
                {
                    "judgment_status": "success",
                    "overall_possibility": "medium",
                    "merit": "supported",
                    "merit_basis": ["persisted basis"],
                    "merit_relief_type": "reduction",
                    "risk_flag": False,
                    "risk_basis": [],
                    "guide": {"summary": "persisted guide"},
                },
            ),
        ],
        required_node_codes=(
            "fine_notice_analysis",
            "law_ground_search",
            "appeal_decision_flow",
        ),
        target_node_code="objection_report_generation",
        report_type="fine_notice_objection",
        case_context={"user_facts": "persisted confirmed facts"},
    )


def test_reporting_uses_strict_persisted_handoff_and_ignores_poisoned_upstream() -> None:
    handoff = _handoff()

    output = run_objection_report_generation(
        {
            "job_id": "job_handoff_report",
            "session_id": "ses_handoff_report",
            "message_id": "msg_handoff_report",
            "context": {
                "handoff_required": True,
                "supervisor_reporting_handoff": handoff,
                "recipient_agency": "Poisoned context Agency",
            },
            "attachments": [
                {"filename": "RAW-ATTACHMENT-SECRET-193.pdf"},
            ],
            "upstream_results": {
                "fine_notice_analysis": {
                    "status": "success",
                    "structured_result": {
                        "notice_fields": {"agency": "Poisoned in-memory Agency"}
                    },
                }
            },
        },
        {"node": {"node_name": "Reporting", "node_type": "agent", "owner": "test"}},
    )

    structured = output["structured_result"]
    assert output["status"] == "success"
    assert structured["recipient_agency"] == "Persisted Agency"
    assert "Poisoned in-memory Agency" not in repr(output)
    assert "Poisoned context Agency" not in repr(output)
    assert "RAW-ATTACHMENT-SECRET-193" not in repr(output)
    assert structured["supervisor_handoff"]["handoff_id"] == handoff["handoff_id"]
    assert (
        structured["supervisor_handoff"]["source_fingerprint"]
        == handoff["source"]["fingerprint"]
    )
    assert structured["appeal_decision"]["overall_possibility"] == "medium"
    assert structured["appeal_decision"]["guide"] == {"summary": "persisted guide"}


def test_reporting_fails_closed_when_strict_handoff_is_missing() -> None:
    output = run_objection_report_generation(
        {
            "job_id": "job_missing_handoff",
            "context": {"handoff_required": True},
            "upstream_results": {
                "fine_notice_analysis": {
                    "status": "success",
                    "structured_result": {"notice_fields": {"agency": "must be ignored"}},
                }
            },
        },
        {"node": {"node_name": "Reporting", "node_type": "agent", "owner": "test"}},
    )

    assert output["status"] == "failed"
    assert output["structured_result"]["error_code"] == "supervisor_reporting_handoff_required"
    assert "must be ignored" not in repr(output)
