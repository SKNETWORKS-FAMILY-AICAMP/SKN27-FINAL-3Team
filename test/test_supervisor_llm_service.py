from app.services import supervisor_llm_service as service


def _fallback_builder(_payload, _scenario):
    return {
        "contract_version": "supervisor_conversation.v1",
        "stage": "need_more_input",
        "conversation_turn_count": 1,
        "conversation_summary": "fallback summary",
        "collected_facts": [{"field": "notice_or_disposition", "label": "고지/처분", "value": "과태료"}],
        "missing_fields": [{"field": "evidence_status", "label": "증빙 보유 여부"}],
        "next_questions": [{"field": "evidence_status", "question": "보유한 증빙이 있나요?"}],
        "agent_input_packages": [
            {
                "schema_version": "agent_input_schema.v1",
                "node_code": "fine_notice_analysis",
                "owner": "workzion2",
                "status": "waiting_for_fields",
                "missing_fields": ["evidence_status"],
                "payload": {"notice_text": "과태료", "evidence_status": None},
            },
            {
                "schema_version": "agent_input_schema.v1",
                "node_code": "objection_report_generation",
                "owner": "hi20260204-maker",
                "status": "waiting_for_fields",
                "missing_fields": ["evidence_status"],
                "payload": {"draft_goal": "의견제출서"},
            },
        ],
        "reporting_payload": {
            "contract_version": "reporting_payload.v1",
            "scenario": "fine_notice",
            "stage": "need_more_input",
            "title": "Supervisor 상담 분석 리포트",
            "summary": "fallback summary",
            "sections": [],
        },
    }


def _fallback_plan():
    return {
        "plan_id": "plan_fallback",
        "session_id": "ses_plan",
        "message_id": "msg_plan",
        "routing_intent": "objection_request",
        "input_summary": {"has_user_command": True, "missing_fields": []},
        "required_inputs": ["fine_notice_image_or_text", "user_facts"],
        "pending_questions": [],
        "agent_input_packages": [
            {
                "schema_version": "agent_input_schema.v1",
                "node_code": "fine_notice_analysis",
                "owner": "workzion2",
                "status": "ready",
                "missing_fields": [],
                "payload": {"notice_text": "fallback"},
            },
            {
                "schema_version": "agent_input_schema.v1",
                "node_code": "law_ground_search",
                "owner": "techshin31",
                "status": "ready",
                "missing_fields": [],
                "payload": {"search_query": "fallback"},
            },
        ],
        "steps": [
            {
                "order": 1,
                "node_code": "input_context_validation",
                "status": "success",
                "required_inputs": ["user_text|attachments"],
                "depends_on": [],
                "fallback": "missing_input_question",
            },
            {
                "order": 2,
                "node_code": "fine_notice_analysis",
                "status": "success",
                "required_inputs": ["attachments[purpose=fine_notice]|user_text"],
                "depends_on": ["input_context_validation"],
                "fallback": "missing_input_question",
            },
            {
                "order": 3,
                "node_code": "law_ground_search",
                "status": "success",
                "required_inputs": ["law_code|violation_text|search_query"],
                "depends_on": ["fine_notice_analysis"],
                "fallback": "semantic_search_or_limitations",
            },
            {
                "order": 4,
                "node_code": "agent_result_validation",
                "status": "success",
                "required_inputs": ["agent_results"],
                "depends_on": ["law_ground_search"],
                "fallback": "limitations",
            },
        ],
        "blocked_reason": None,
        "limitations": ["fallback limitation"],
    }


def test_supervisor_llm_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_LLM_ENABLED", raising=False)

    state = service.build_supervisor_state_with_optional_llm(
        payload={"user_text": "과태료 고지서를 받았어요."},
        scenario="fine_notice",
        fallback_builder=_fallback_builder,
    )

    assert state["conversation_summary"] == "fallback summary"
    assert state["llm"]["status"] == "disabled"
    assert state["reporting_payload"]["model_trace"]["status"] == "disabled"


def test_supervisor_llm_planner_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_LLM_ENABLED", raising=False)

    plan = service.build_analysis_plan_with_optional_llm(
        payload={"user_text": "plan this"},
        scenario="fine_notice",
        requested_status="success",
        fallback_plan=_fallback_plan(),
        supervisor_state=_fallback_builder({}, "fine_notice"),
    )

    assert plan["llm_planner"]["status"] == "disabled"
    assert plan["steps"][0]["node_code"] == "input_context_validation"
    assert plan["steps"][-1]["node_code"] == "agent_result_validation"


def test_supervisor_llm_falls_back_without_api_key(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_LLM_ENABLED", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SUPERVISOR_LLM_API_KEY", raising=False)

    state = service.build_supervisor_state_with_optional_llm(
        payload={"user_text": "과태료 고지서를 받았어요."},
        scenario="fine_notice",
        fallback_builder=_fallback_builder,
    )

    assert state["llm"]["status"] == "fallback"
    assert state["llm"]["reason"] == "missing_config:api_key"
    assert state["agent_input_packages"][0]["owner"] == "workzion2"


def test_supervisor_llm_planner_normalizes_registry_safe_steps(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_LLM_ENABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUPERVISOR_LLM_MODEL", "gpt-test")

    def fake_request(_config, request_payload):
        assert request_payload["user"]["contract_version"] == "supervisor_analysis_plan.v1"
        return {
            "routing_intent": "objection_request",
            "input_summary": {"planner_hint": "llm"},
            "required_inputs": ["fine_notice_image_or_text"],
            "pending_questions": [{"field": "evidence_status", "question": "evidence?"}],
            "agent_input_packages": [
                {
                    "node_code": "law_ground_search",
                    "missing_fields": [],
                    "payload": {"search_query": "school zone emergency stopping"},
                },
                {"node_code": "unknown_agent", "payload": {"unsafe": True}},
            ],
            "steps": [
                {
                    "node_code": "law_ground_search",
                    "status": "success",
                    "required_inputs": ["search_query"],
                    "depends_on": ["fine_notice_analysis", "unknown_agent"],
                    "fallback": "semantic_search_or_limitations",
                },
                {"node_code": "unknown_agent", "status": "success"},
            ],
            "blocked_reason": "",
        }

    monkeypatch.setattr(service, "_request_supervisor_json", fake_request)

    plan = service.build_analysis_plan_with_optional_llm(
        payload={"user_text": "plan this"},
        scenario="fine_notice",
        requested_status="success",
        fallback_plan=_fallback_plan(),
        supervisor_state=_fallback_builder({}, "fine_notice"),
    )

    assert plan["llm_planner"]["status"] == "used"
    assert [step["node_code"] for step in plan["steps"]] == [
        "input_context_validation",
        "law_ground_search",
        "agent_result_validation",
    ]
    assert plan["steps"][1]["required_inputs"] == ["search_query"]
    assert plan["steps"][1]["depends_on"] == []
    assert plan["agent_input_packages"][0]["node_code"] == "law_ground_search"
    assert plan["agent_input_packages"][0]["payload"]["search_query"] == "school zone emergency stopping"
    assert "unknown_agent" not in {item["node_code"] for item in plan["agent_input_packages"]}


def test_supervisor_llm_normalizes_agent_package_ownership(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_LLM_ENABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUPERVISOR_LLM_MODEL", "gpt-test")

    def fake_request(_config, _request_payload):
        return {
            "contract_version": "supervisor_conversation.v1",
            "stage": "agent_execution_ready",
            "conversation_turn_count": 2,
            "conversation_summary": "LLM summary",
            "collected_facts": [{"field": "evidence_status", "label": "증빙", "value": "블랙박스"}],
            "missing_fields": [],
            "next_questions": [],
            "agent_input_packages": [
                {
                    "node_code": "fine_notice_analysis",
                    "owner": "wrong-owner",
                    "status": "ready",
                    "missing_fields": [],
                    "payload": {"evidence_status": "블랙박스 보유"},
                },
                {
                    "node_code": "unknown_agent",
                    "owner": "wrong-owner",
                    "status": "ready",
                    "missing_fields": [],
                    "payload": {},
                },
            ],
            "reporting_payload": {
                "contract_version": "reporting_payload.v1",
                "scenario": "fine_notice",
                "stage": "agent_execution_ready",
                "title": "LLM 리포트",
                "summary": "LLM summary",
                "sections": [],
            },
        }

    monkeypatch.setattr(service, "_request_supervisor_json", fake_request)

    state = service.build_supervisor_state_with_optional_llm(
        payload={"user_text": "블랙박스가 있어요."},
        scenario="fine_notice",
        fallback_builder=_fallback_builder,
    )

    assert state["llm"]["status"] == "used"
    assert state["stage"] == "agent_execution_ready"
    assert [item["node_code"] for item in state["agent_input_packages"]] == [
        "fine_notice_analysis",
        "objection_report_generation",
    ]
    assert state["agent_input_packages"][0]["owner"] == "workzion2"
    assert state["agent_input_packages"][0]["payload"]["evidence_status"] == "블랙박스 보유"
    assert state["agent_input_packages"][1]["owner"] == "hi20260204-maker"
