import pytest

from app.services import supervisor_llm_service
from app.services.chat_orchestration_service import submit_message


def _candidate_from_request(request_payload):
    fallback = request_payload["user"]["fallback_state"]
    return {
        "conversation_summary": "Structured Supervisor summary",
        "collected_facts": [],
        "missing_fields": [],
        "next_questions": [],
        "agent_input_packages": [
            {
                "node_code": package["node_code"],
                "payload": {},
            }
            for package in fallback["agent_input_packages"]
        ],
    }


def _enable_supervisor(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_LLM_ENABLED", "1")
    monkeypatch.setenv("SUPERVISOR_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("SUPERVISOR_LLM_MODEL", "gpt-test")
    monkeypatch.setattr(
        supervisor_llm_service,
        "_request_supervisor_json",
        lambda _config, request_payload, _response_format: _candidate_from_request(
            request_payload
        ),
    )


@pytest.mark.parametrize(
    ("routing_intent", "user_text"),
    [
        ("general_consultation", "교통 관련 일반 상담이 필요해"),
        ("traffic_law_search", "어린이보호구역 정차 관련 법령을 찾아줘"),
        ("fine_notice_procedure", "과태료 고지서를 받은 뒤 절차를 알려줘"),
        ("fine_notice_analysis", "과태료 고지서 내용을 분석해줘"),
    ],
)
def test_production_submit_message_accepts_registry_enriched_llm_candidate(
    monkeypatch,
    routing_intent,
    user_text,
):
    _enable_supervisor(monkeypatch)

    response = submit_message(
        {
            "session_id": f"ses_{routing_intent}",
            "user_text": user_text,
            "attachments": [],
        },
        routing_intent_override=routing_intent,
    )

    assert response["status"] != "supervisor_unavailable"
    assert response["supervisor_state"]["llm"]["status"] == "used"
    assert (
        response["supervisor_state"]["contract_version"]
        == "supervisor_conversation_state.v2"
    )
    assert response["supervisor_state"]["reporting_payload"] is None
    for package in response["supervisor_state"]["agent_input_packages"]:
        assert package["owner"]
        assert isinstance(package["missing_fields"], list)


def test_accident_consultation_accepts_empty_agent_package_contract(monkeypatch):
    _enable_supervisor(monkeypatch)

    response = submit_message(
        {
            "session_id": "ses_accident_contract",
            "user_text": "교차로에서 사고가 났고 과실 상담이 필요해",
            "attachments": [],
        },
        routing_intent_override="accident_initial_consultation",
    )

    state = response["supervisor_state"]
    assert state["llm"]["status"] == "used"
    assert state["stage"] in {"need_more_input", "need_fact_confirmation"}
    assert state["agent_input_packages"] == []
    assert state["reporting_payload"] is None


def test_confirmed_ocr_server_packages_receive_registry_controls(monkeypatch):
    _enable_supervisor(monkeypatch)

    response = submit_message(
        {
            "session_id": "ses_confirmed_ocr_contract",
            "user_text": "고지서 OCR 내용을 확인했어",
            "attachments": [],
            "ocr_confirmation": {
                "confirmed": True,
                "fields": {
                    "fine_type": "과태료",
                    "notice_stage": "사전통지",
                },
            },
        },
        routing_intent_override="fine_notice_analysis",
    )

    assert response["status"] != "supervisor_unavailable"
    packages = {
        package["node_code"]: package
        for package in response["supervisor_state"]["agent_input_packages"]
    }
    assert packages["law_ground_search"]["owner"] == "techshin31"
    assert packages["law_ground_search"]["missing_fields"] == []
    assert packages["appeal_decision_flow"]["owner"] == "hi20260204-maker"
    assert packages["appeal_decision_flow"]["missing_fields"] == []
