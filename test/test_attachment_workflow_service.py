from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("inputs", "expected_state", "expected_action"),
    [
        ({"scan_status": "pending"}, "scan_running", "wait_for_scan"),
        (
            {"scan_status": "clean"},
            "classification_running",
            "wait_for_classification",
        ),
        (
            {"classification": {"requires_confirmation": True}},
            "classified_waiting_confirmation",
            "confirm_classification",
        ),
        (
            {
                "classification": {"status": "success"},
                "active_node": "fine_notice_analysis",
            },
            "ocr_running",
            "wait_for_ocr",
        ),
        (
            {
                "classification": {"status": "success"},
                "ocr": {
                    "requires_confirmation": True,
                    "missing_fields": ["response_deadline"],
                },
            },
            "ocr_needs_confirmation",
            "confirm_ocr_fields",
        ),
        (
            {
                "classification": {"status": "success"},
                "ocr_confirmation": {"confirmed": True},
                "analysis_status": "success",
            },
            "analysis_ready",
            "review_analysis",
        ),
    ],
)
def test_attachment_workflow_state_table(
    inputs: dict[str, object],
    expected_state: str,
    expected_action: str,
) -> None:
    from app.services.attachment_workflow_service import build_attachment_workflows

    attachment = {
        "attachment_id": "att_notice",
        "status": inputs.get("status", "ready"),
        "scan_status": inputs.get("scan_status", "clean"),
    }
    structured: dict[str, object] = {}
    if "classification" in inputs:
        structured["attachment_document_classification"] = {
            "attachment_id": "att_notice",
            **inputs["classification"],
        }
    if "ocr" in inputs:
        structured["fine_notice_analysis"] = {
            "attachment_id": "att_notice",
            **inputs["ocr"],
        }

    result = build_attachment_workflows(
        attachments=[attachment],
        structured_results=structured,
        active_node=str(inputs.get("active_node", "")),
        overall_status=str(inputs.get("analysis_status", "")),
        ocr_confirmation=inputs.get("ocr_confirmation"),
    )

    assert result[0]["state"] == expected_state
    assert result[0]["next_action"] == expected_action


@pytest.mark.parametrize(
    ("structured_result", "active_node", "overall_status", "expected_state", "expected_action"),
    [
        ({}, "traffic_accident_confirmation_ocr", "running", "ocr_running", "wait_for_ocr"),
        (
            {"status": "success", "document_check": {"is_target_document": True}},
            "",
            "success",
            "analysis_ready",
            "review_analysis",
        ),
        (
            {"status": "partial", "document_check": {"is_target_document": True}},
            "",
            "partial",
            "partial",
            "provide_missing_information",
        ),
        (
            {"status": "failed"},
            "",
            "failed",
            "failed",
            "retry_or_reupload",
        ),
    ],
)
def test_traffic_accident_confirmation_bypasses_generic_classification(
    structured_result: dict[str, object],
    active_node: str,
    overall_status: str,
    expected_state: str,
    expected_action: str,
) -> None:
    from app.services.attachment_workflow_service import build_attachment_workflows

    structured_results = {}
    if structured_result:
        structured_results["traffic_accident_confirmation_ocr"] = {
            "attachment_id": "att_accident",
            **structured_result,
        }

    [workflow] = build_attachment_workflows(
        attachments=[
            {
                "attachment_id": "att_accident",
                "purpose": "traffic_accident_confirmation",
                "status": "ready",
                "scan_status": "clean",
            }
        ],
        structured_results=structured_results,
        active_node=active_node,
        overall_status=overall_status,
    )

    assert workflow["state"] == expected_state
    assert workflow["next_action"] == expected_action
    assert workflow["state"] != "classification_running"


@pytest.mark.parametrize(
    ("structured", "overall_status", "expected_state", "expected_action"),
    [
        (
            {
                "attachment_document_classification": {
                    "attachment_id": "att_notice",
                    "status": "partial",
                    "next_action": "rerun_classification",
                }
            },
            "",
            "partial",
            "rerun_classification",
        ),
        (
            {
                "attachment_document_classification": {
                    "attachment_id": "att_notice",
                    "status": "success",
                }
            },
            "partial",
            "partial",
            "provide_missing_information",
        ),
        (
            {
                "attachment_document_classification": {
                    "attachment_id": "att_notice",
                    "status": "success",
                }
            },
            "failed",
            "failed",
            "retry_or_reupload",
        ),
    ],
)
def test_partial_and_failed_states_have_safe_guidance(
    structured: dict[str, object],
    overall_status: str,
    expected_state: str,
    expected_action: str,
) -> None:
    from app.services.attachment_workflow_service import build_attachment_workflows

    [workflow] = build_attachment_workflows(
        attachments=[
            {
                "attachment_id": "att_notice",
                "status": "ready",
                "scan_status": "clean",
            }
        ],
        structured_results=structured,
        overall_status=overall_status,
    )

    assert workflow["state"] == expected_state
    assert workflow["next_action"] == expected_action
    assert workflow["limitations"]


@pytest.mark.parametrize(
    "attachment",
    [
        {"status": "rejected", "scan_status": "clean"},
        {"status": "deleted", "scan_status": "clean"},
        {"status": "ready", "scan_status": "infected"},
        {"status": "ready", "scan_status": "failed"},
        {"status": "mystery", "scan_status": "unexpected"},
    ],
)
def test_unsafe_or_unknown_attachment_status_fails_closed(
    attachment: dict[str, str],
) -> None:
    from app.services.attachment_workflow_service import build_attachment_workflows

    [workflow] = build_attachment_workflows(
        attachments=[{"attachment_id": "att_notice", **attachment}],
    )

    assert workflow["state"] == "failed"
    assert workflow["next_action"] == "reattach_file"
    assert workflow["limitations"]


def test_workflow_output_exposes_only_safe_contract_fields() -> None:
    from app.services.attachment_workflow_service import build_attachment_workflows

    [workflow] = build_attachment_workflows(
        attachments=[
            {
                "attachment_id": "att_notice",
                "status": "ready",
                "scan_status": "clean",
                "filename": "홍길동_고지서.pdf",
                "storage_uri": "s3://private-bucket/notices/att_notice",
                "raw_ocr_text": "주민등록번호 900101-1234567",
                "error": "C:\\private\\scanner.log",
            }
        ],
        structured_results={
            "attachment_document_classification": {
                "attachment_id": "att_notice",
                "requires_confirmation": True,
                "raw_model_output": "private",
            }
        },
    )

    assert set(workflow) == {
        "contract_version",
        "attachment_id",
        "state",
        "next_action",
        "retryable",
        "missing_fields",
        "limitations",
    }
    assert "홍길동" not in repr(workflow)
    assert "s3://" not in repr(workflow)
    assert "900101" not in repr(workflow)
    assert "private" not in repr(workflow)


def test_results_are_correlated_by_attachment_id() -> None:
    from app.services.attachment_workflow_service import build_attachment_workflows

    workflows = build_attachment_workflows(
        attachments=[
            {
                "attachment_id": "att_first",
                "status": "ready",
                "scan_status": "clean",
            },
            {
                "attachment_id": "att_second",
                "status": "ready",
                "scan_status": "clean",
            },
        ],
        structured_results={
            "attachment_document_classification": [
                {
                    "attachment_id": "att_first",
                    "requires_confirmation": True,
                },
                {
                    "attachment_id": "att_second",
                    "status": "success",
                },
            ],
            "fine_notice_analysis": [
                {
                    "attachment_id": "att_second",
                    "requires_confirmation": True,
                    "missing_fields": ["response_deadline"],
                }
            ],
        },
    )

    assert [item["state"] for item in workflows] == [
        "classified_waiting_confirmation",
        "ocr_needs_confirmation",
    ]


def test_completed_ocr_result_does_not_regress_to_classification_running() -> None:
    from app.services.attachment_workflow_service import build_attachment_workflows

    [workflow] = build_attachment_workflows(
        attachments=[
            {
                "attachment_id": "att_notice",
                "status": "ready",
                "scan_status": "clean",
            }
        ],
        structured_results={
            "fine_notice_analysis": {
                "attachment_id": "att_notice",
                "status": "success",
            }
        },
        overall_status="partial",
        ocr_confirmation={"attachment_id": "att_notice", "confirmed": True},
    )

    assert workflow["state"] == "partial"
    assert workflow["next_action"] == "provide_missing_information"
    assert workflow["state"] != "classification_running"
