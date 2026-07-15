from __future__ import annotations

from copy import deepcopy

from app.services.supervisor_reporting_handoff_service import (
    build_supervisor_reporting_handoff,
)


REQUIRED_NODES = (
    "fine_notice_analysis",
    "law_ground_search",
    "appeal_decision_flow",
)
AWS_ACCESS_KEY_FIXTURE = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
GOOGLE_ACCESS_TOKEN_FIXTURE = "ya" + "29." + "A0AfH6SMexampleGoogleAccessToken193"
GITHUB_TOKEN_FIXTURE = "gh" + "p_" + "0123456789abcdefghijABCDEFGHIJ"
GITHUB_FINE_TOKEN_FIXTURE = (
    "github" + "_pat_" + "11AA0_FAKEfineGrainedToken193xyz"
)
JWT_FIXTURE = (
    "ey" + "JhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c3JfMTkzIn0.signature193"
)
PRIVATE_KEY_FIXTURE = (
    "-----BEGIN PRIVATE" + " KEY-----\nprivate-pem-body\n"
    "-----END PRIVATE" + " KEY-----"
)
OPENAI_TOKEN_FIXTURE = "s" + "k-live-secret-value"


def _result(node_code: str, status: str = "success") -> dict:
    return {
        "result_id": f"res_job_193_{node_code}",
        "node_code": node_code,
        "status": status,
        "summary": f"{node_code} summary",
        "structured_result": {
            "value": node_code,
            "notes": [
                f"Authorization: Bearer {OPENAI_TOKEN_FIXTURE}",
                "Authorization: Basic dXNlcjpwYXNzd29yZA==",
                f"AWS key {AWS_ACCESS_KEY_FIXTURE}",
                f"jwt {JWT_FIXTURE}",
                f"oauth {GOOGLE_ACCESS_TOKEN_FIXTURE}",
                f"github {GITHUB_TOKEN_FIXTURE}",
                f"github fine {GITHUB_FINE_TOKEN_FIXTURE}",
                PRIVATE_KEY_FIXTURE,
            ],
            "oauth": {"access_token": "must-not-cross-handoff"},
            "debug": {
                "raw_text": "private raw OCR text",
                "accessToken": "camel-case-token",
                "id_token": "identity-token",
                "signed_url": "https://signed.example/private",
                "local_path": "C:/private/file",
                "debug_url": "https://storage.example/file?X-Amz-Signature=url-secret",
                "links": [
                    "https://storage.example/list-item?X-Amz-Signature=list-url-secret",
                    "https://storage.googleapis.com/private?X-Goog-Credential=gcs-user&X-Goog-Signature=gcs-secret&X-Goog-Security-Token=gcs-token",
                    "https://userinfo-user:userinfo-password@example.com/private",
                ],
                "session_cookie": "cookie-secret",
                "credentials": {"private_key": "private-key-secret"},
                "aws_secret_access_key": "aws-key-must-not-cross",
                "password_hash": "password-hash-must-not-cross",
                "bearer_token_value": "bearer-value-must-not-cross",
                "storage_uri": "s3://private-bucket/private-object",
                "chain_of_thought": "private-reasoning",
            },
        },
        "evidence": [{"source": node_code}],
        "next_actions": [f"review {node_code}"],
        "limitations": [],
        "raw_output": {
            "agent_input": {"user_text": "private raw text", "token": "secret"},
            "reasoning": "must not cross the handoff boundary",
        },
    }


def _build(results: list[dict]) -> dict:
    return build_supervisor_reporting_handoff(
        job={
            "job_id": "job_193",
            "session_id": "ses_193",
            "message_id": "msg_193",
            "analysis_plan_id": "plan_193",
            "routing_intent": "fine_notice_objection",
        },
        results=results,
        required_node_codes=REQUIRED_NODES,
        target_node_code="objection_report_generation",
        report_type="fine_notice_objection",
        case_context={
            "user_facts": "confirmed safe facts",
            "attachment_refs": [
                {
                    "attachment_id": "att_193",
                    "purpose": "fine_notice password=purpose-secret",
                    "filename": "notice Authorization: Bearer sk-filename-secret",
                    "storage_uri": "s3://private/raw/location",
                }
            ],
        },
    )


def test_handoff_is_deterministic_and_excludes_raw_output() -> None:
    ordered = [_result(node_code) for node_code in REQUIRED_NODES]
    reversed_results = list(reversed(deepcopy(ordered)))

    first = _build(ordered)
    second = _build(reversed_results)

    assert first == second
    assert first["contract_version"] == "supervisor_reporting_handoff.v1"
    assert first["gate"]["status"] == "ready"
    assert first["ready_for_reporting"] is True
    assert first["gate"]["ready_for_reporting"] is True
    assert first["source_node_codes"] == list(REQUIRED_NODES)
    assert first["source"]["persistence"] == "agent_results"
    assert first["source"]["persisted"] is True
    assert first["source"]["fingerprint"].startswith("sha256:")
    assert list(first["results"]) == list(REQUIRED_NODES)
    assert "raw_output" not in repr(first)
    assert "private raw text" not in repr(first)
    assert "secret" not in repr(first)
    assert "must-not-cross-handoff" not in repr(first)
    assert "access_token" not in repr(first)
    assert "private raw OCR text" not in repr(first)
    assert "camel-case-token" not in repr(first)
    assert "identity-token" not in repr(first)
    assert "signed.example" not in repr(first)
    assert "C:/private/file" not in repr(first)
    assert "url-secret" not in repr(first)
    assert "list-url-secret" not in repr(first)
    assert "gcs-user" not in repr(first)
    assert "gcs-secret" not in repr(first)
    assert "gcs-token" not in repr(first)
    assert "userinfo-user" not in repr(first)
    assert "userinfo-password" not in repr(first)
    assert "cookie-secret" not in repr(first)
    assert "private-key-secret" not in repr(first)
    assert "aws-key-must-not-cross" not in repr(first)
    assert "password-hash-must-not-cross" not in repr(first)
    assert "bearer-value-must-not-cross" not in repr(first)
    assert OPENAI_TOKEN_FIXTURE not in repr(first)
    assert "dXNlcjpwYXNzd29yZA" not in repr(first)
    assert AWS_ACCESS_KEY_FIXTURE not in repr(first)
    assert JWT_FIXTURE.split(".", 1)[0] not in repr(first)
    assert GOOGLE_ACCESS_TOKEN_FIXTURE not in repr(first)
    assert GITHUB_TOKEN_FIXTURE not in repr(first)
    assert GITHUB_FINE_TOKEN_FIXTURE not in repr(first)
    assert "private-pem-body" not in repr(first)
    assert "END PRIVATE KEY" not in repr(first)
    assert "[REDACTED_CREDENTIAL]" in repr(first)
    assert "private-bucket" not in repr(first)
    assert "private-reasoning" not in repr(first)
    assert first["case_context"]["attachment_refs"] == [
        {
            "attachment_id": "att_193",
            "purpose": "fine_notice [REDACTED_CREDENTIAL]",
            "filename": "notice [REDACTED_CREDENTIAL]",
        }
    ]
    assert "purpose-secret" not in repr(first)
    assert "filename-secret" not in repr(first)


def test_partial_required_result_makes_draft_gate() -> None:
    results = [_result(node_code) for node_code in REQUIRED_NODES]
    results[1]["status"] = "partial"

    handoff = _build(results)

    assert handoff["gate"]["status"] == "draft"
    assert handoff["ready_for_reporting"] is False
    assert handoff["gate"]["ready_for_reporting"] is False
    assert handoff["gate"]["partial_required_node_codes"] == ["law_ground_search"]
    assert handoff["gate"]["reason_codes"] == ["required_result_partial"]


def test_missing_failed_or_duplicate_required_result_blocks_reporting() -> None:
    missing = _build([_result("fine_notice_analysis"), _result("law_ground_search")])
    failed = _build(
        [
            _result("fine_notice_analysis"),
            _result("law_ground_search", "failed"),
            _result("appeal_decision_flow"),
        ]
    )
    duplicate = _build(
        [_result(node_code) for node_code in REQUIRED_NODES]
        + [_result("law_ground_search")]
    )

    assert missing["gate"]["status"] == "blocked"
    assert missing["ready_for_reporting"] is False
    assert missing["gate"]["missing_required_node_codes"] == ["appeal_decision_flow"]
    assert failed["gate"]["status"] == "blocked"
    assert failed["gate"]["failed_required_node_codes"] == ["law_ground_search"]
    assert duplicate["gate"]["status"] == "blocked"
    assert duplicate["gate"]["duplicate_required_node_codes"] == ["law_ground_search"]


def test_unknown_status_fails_closed_and_handoff_id_is_bounded() -> None:
    results = [_result(node_code) for node_code in REQUIRED_NODES]
    results[0]["status"] = "unexpected"

    handoff = build_supervisor_reporting_handoff(
        job={
            "job_id": "job_" + ("x" * 100),
            "session_id": "ses_long",
            "analysis_plan_id": "plan_long",
            "routing_intent": "fine_notice_objection",
        },
        results=results,
        required_node_codes=REQUIRED_NODES,
        target_node_code="objection_report_generation",
        report_type="fine_notice_objection",
    )

    assert handoff["gate"]["status"] == "blocked"
    assert handoff["gate"]["invalid_required_node_codes"] == ["fine_notice_analysis"]
    assert len(handoff["handoff_id"]) <= 64
