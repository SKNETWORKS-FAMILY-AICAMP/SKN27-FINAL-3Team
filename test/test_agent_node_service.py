from app.services import agent_node_service
from app.services.agent_adapter_contract import (
    ADAPTER_CONTRACT_VERSION,
    build_agent_adapter_input,
    validate_adapter_context_envelope,
    validate_agent_input_envelope,
    validate_agent_output_envelope,
)
from app.services.agent_node_service import (
    execute_agent_node,
    execute_mock_node,
    execute_mock_plan,
    list_agent_nodes,
    list_public_agent_nodes,
)
from app.services.attachment_mock_service import register_attachment
from app.services.chatbot_mock_service import build_analysis_plan


def test_agent_node_registry_lists_all_integration_nodes():
    nodes = list_agent_nodes()
    node_codes = {node["node_code"] for node in nodes}

    assert {
        "input_context_validation",
        "fine_notice_analysis",
        "law_ground_search",
        "text_ml_case_search",
        "vision_media_analysis",
        "appeal_decision_flow",
        "objection_report_generation",
        "agent_result_validation",
    } <= node_codes
    assert {node["node_type"] for node in nodes} >= {"agent", "supervisor_internal"}
    fine_notice_node = next(node for node in nodes if node["node_code"] == "fine_notice_analysis")
    assert fine_notice_node["status"] == "sync_adapter_ready"
    assert "sync" in fine_notice_node["adapter_modes"]
    text_ml_node = next(node for node in nodes if node["node_code"] == "text_ml_case_search")
    law_node = next(node for node in nodes if node["node_code"] == "law_ground_search")
    vision_node = next(node for node in nodes if node["node_code"] == "vision_media_analysis")
    objection_node = next(node for node in nodes if node["node_code"] == "objection_report_generation")
    assert law_node["status"] == "sync_adapter_ready"
    assert law_node["adapter_modes"] == ["sync"]
    assert law_node["adapter_contract"]["execution_modes"] == ["sync"]
    assert text_ml_node["status"] == "sync_adapter_ready"
    assert text_ml_node["adapter_modes"] == ["sync"]
    assert text_ml_node["adapter_contract"]["execution_modes"] == ["sync"]
    assert vision_node["status"] == "mock_contract_only"
    assert vision_node["adapter_modes"] == ["mock"]
    assert vision_node["adapter_contract"]["execution_modes"] == ["mock"]
    assert objection_node["status"] == "sync_adapter_ready"
    assert objection_node["adapter_modes"] == ["sync"]
    assert objection_node["adapter_contract"]["execution_modes"] == ["sync"]


def test_only_vision_agent_advertises_mock_execution():
    agents = {
        node["node_code"]: node
        for node in list_agent_nodes()
        if node["node_type"] == "agent"
    }

    assert agents["vision_media_analysis"]["adapter_modes"] == ["mock"]
    for node_code in {
        "fine_notice_analysis",
        "law_ground_search",
        "text_ml_case_search",
        "appeal_decision_flow",
        "objection_report_generation",
    }:
        assert agents[node_code]["adapter_modes"] == ["sync"]
        assert agents[node_code]["adapter_contract"]["execution_modes"] == ["sync"]


def test_public_agent_registry_includes_every_non_dl_runtime_agent():
    public_codes = {node["node_code"] for node in list_public_agent_nodes()}

    assert public_codes == {
        "fine_notice_analysis",
        "law_ground_search",
        "text_ml_case_search",
        "appeal_decision_flow",
        "objection_report_generation",
    }
    assert "vision_media_analysis" not in public_codes


def test_legacy_mock_entrypoint_delegates_non_dl_agent_to_real_runtime(monkeypatch):
    calls = []

    def fake_execute_agent_node(payload):
        calls.append(payload)
        return {
            "execution_mode": "sync",
            "node_code": payload["node_code"],
            "agent_output": {"status": "success"},
        }

    monkeypatch.setattr(agent_node_service, "execute_agent_node", fake_execute_agent_node)

    result = execute_mock_node({"node_code": "law_ground_search", "user_text": "법률 근거"})

    assert result["execution_mode"] == "sync"
    assert len(calls) == 1
    assert calls[0]["node_code"] == "law_ground_search"
    assert calls[0]["user_text"] == "법률 근거"
    assert calls[0]["attachment_resolution"]["unresolved_attachment_ids"] == []


def test_legacy_mock_entrypoint_keeps_dl_agent_as_explicit_mock():
    result = execute_mock_node(
        {
            "node_code": "vision_media_analysis",
            "attachments": [{"attachment_id": "att_vision", "purpose": "evidence"}],
        }
    )

    assert result["execution_mode"] == "mock"
    assert result["node_code"] == "vision_media_analysis"


def test_appeal_decision_runtime_invokes_real_graph_with_upstream_results(monkeypatch):
    from ai.agents.appeal_decision_flow import graph as appeal_graph

    received_states = []

    def fake_invoke(state):
        received_states.append(state)
        return {
            "agent_results": {
                "appeal_judgment": {
                    "status": "success",
                    "summary": "이의신청 판단을 완료했습니다.",
                    "structured_result": {
                        "judgment_status": "success",
                        "overall_possibility": "review_available",
                        "guide": {"next_step": "review_report"},
                    },
                    "evidence": [],
                    "next_actions": ["review_report"],
                    "limitations": [],
                }
            }
        }

    monkeypatch.setattr(appeal_graph, "invoke", fake_invoke)

    execution = execute_agent_node(
        {
            "node_code": "appeal_decision_flow",
            "user_text": "표지판이 가려져 있었으므로 이의를 신청하고 싶습니다.",
            "context": {"fine_type": "administrative_fine", "notice_stage": "first_notice"},
            "upstream_results": {
                "fine_notice_analysis": {
                    "structured_result": {"violation_text": "신호위반"}
                }
            },
        }
    )

    assert execution["execution_mode"] == "sync"
    assert execution["agent_output"]["status"] == "success"
    assert execution["agent_output"]["structured_result"]["judgment_status"] == "success"
    assert execution["agent_output"]["structured_result"]["adapter_trace"]["adapter"] == (
        "ai.agents.appeal_decision_flow.graph"
    )
    assert received_states == [
        {
            "fine_type": "administrative_fine",
            "notice_stage": "first_notice",
            "violation_text": "신호위반",
            "user_appeal_reason": "표지판이 가려져 있었으므로 이의를 신청하고 싶습니다.",
            "agent_results": {},
        }
    ]


def test_appeal_decision_runtime_propagates_input_required_missing_fields(monkeypatch):
    """When reason_intake_node reports input_required, the adapter must surface
    missing_fields so downstream consumers (e.g. history_event_mock_service,
    which reads structured_result["missing_fields"]) can re-ask the user.
    """
    from ai.agents.appeal_decision_flow import graph as appeal_graph

    def fake_invoke(state):
        return {
            "agent_results": {
                "appeal_judgment": {
                    "status": "input_required",
                    "summary": "이의신청 사유 정보 필요",
                    "structured_result": {
                        "judgment_status": "input_required",
                        "fine_type": "administrative_fine",
                        "notice_stage": "first_notice",
                    },
                    "evidence": [],
                    "missing_fields": ["user_appeal_reason"],
                    "next_actions": [
                        "Supervisor가 사용자에게 이의신청 사유 질문 후 재호출"
                    ],
                    "limitations": [],
                }
            }
        }

    monkeypatch.setattr(appeal_graph, "invoke", fake_invoke)

    execution = execute_agent_node(
        {
            "node_code": "appeal_decision_flow",
            "user_text": "",
            "context": {"fine_type": "administrative_fine", "notice_stage": "first_notice"},
        }
    )

    output = execution["agent_output"]
    assert output["execution_status"] == "input_required"
    assert output["structured_result"]["missing_fields"] == ["user_appeal_reason"]


def test_agent_node_registry_exposes_real_adapter_contract():
    nodes = list_agent_nodes()
    law_node = next(node for node in nodes if node["node_code"] == "law_ground_search")
    contract = law_node["adapter_contract"]

    assert contract["signature_version"] == ADAPTER_CONTRACT_VERSION
    assert contract["adapter_key"] == "law_ground_search"
    assert contract["function_name"] == "run_law_ground_search"
    assert (
        contract["call_signature"]
        == "run_law_ground_search(agent_input: AgentAdapterInput, context: AgentAdapterContext) -> AgentAdapterOutput"
    )
    assert "upstream_results" in contract["required_input_fields"]
    assert "slot_state" in contract["required_input_fields"]
    assert "structured_result" in contract["required_output_fields"]
    assert contract["allowed_statuses"] == ["success", "partial", "failed"]
    assert contract["call_style"] == "sync_callable"
    assert contract["idempotency_scope"] == "job_id:node_code:analysis_plan_id"


def test_agent_adapter_input_and_context_envelopes_validate_signature_v1():
    law_node = next(
        node for node in list_agent_nodes() if node["node_code"] == "law_ground_search"
    )
    agent_input = build_agent_adapter_input(
        analysis_plan_id="plan_contract",
        job_id="job_contract",
        session_id="ses_contract",
        message_id="msg_contract",
        node=law_node,
        user_text="법률 근거를 확인해줘",
        attachments=[{"attachment_id": "att_contract", "purpose": "fine_notice"}],
        context={"locale": "ko-KR"},
        slot_state={"contract_version": "slot_filling_state.v1", "slots": {"location": {"status": "filled"}}},
        required_inputs=["law_code"],
        depends_on=["fine_notice_analysis"],
        upstream_results={"fine_notice_analysis": {"status": "success"}},
    )

    input_validation = validate_agent_input_envelope(
        agent_input,
        expected_node_code="law_ground_search",
    )
    execution = execute_mock_node(
        {
            "node_code": "law_ground_search",
            "analysis_plan_id": "plan_contract",
            "job_id": "job_contract",
            "session_id": "ses_contract",
            "message_id": "msg_contract",
            "user_text": "법률 근거를 확인해줘",
            "context": {"locale": "ko-KR"},
            "slot_state": {"contract_version": "slot_filling_state.v1", "slots": {}},
        }
    )
    context_validation = validate_adapter_context_envelope(
        execution["adapter_context"],
        expected_execution_mode="sync",
    )

    assert input_validation["valid"]
    assert agent_input["node_code"] == "law_ground_search"
    assert agent_input["slot_state"]["contract_version"] == "slot_filling_state.v1"
    assert agent_input["upstream_results"]["fine_notice_analysis"]["status"] == "success"
    assert context_validation["valid"]
    assert execution["adapter_context"]["signature_version"] == ADAPTER_CONTRACT_VERSION
    assert execution["agent_input"]["slot_state"]["contract_version"] == "slot_filling_state.v1"


def test_legacy_mock_entrypoint_returns_real_common_agent_output_envelope():
    execution = execute_mock_node(
        {
            "node_code": "law_ground_search",
            "user_text": "고지서 법률 근거를 확인해줘",
            "mock_status": "success",
        }
    )

    output = execution["agent_output"]

    assert execution["execution_mode"] == "sync"
    assert output["node_code"] == "law_ground_search"
    assert output["status"] in {"success", "partial", "failed"}
    assert "matched_laws" in output["structured_result"]
    assert execution["adapter_context"]["execution_id"] == execution["execution_id"]
    assert execution["adapter_context"]["node"]["adapter_contract"]["adapter_key"] == "law_ground_search"
    assert "upstream_results" in execution["agent_input"]
    assert "slot_state" in execution["agent_input"]
    assert {
        "node_name",
        "node_code",
        "status",
        "summary",
        "structured_result",
        "evidence",
        "next_actions",
        "limitations",
    } <= set(output)
    assert validate_agent_output_envelope(output, expected_node_code="law_ground_search")["valid"]


def test_agent_output_validator_reports_adapter_contract_errors():
    validation = validate_agent_output_envelope(
        {"node_code": "fine_notice_analysis", "status": "pending"},
        expected_node_code="law_ground_search",
    )

    assert not validation["valid"]
    assert validation["invalid_status"]
    assert validation["node_code_mismatch"]
    assert "summary" in validation["missing_fields"]


def test_hi_owned_agent_output_sample_validates_without_touching_other_agents():
    output = {
        "session_id": "ses_hi_contract",
        "message_id": "msg_hi_contract",
        "job_id": "job_hi_contract",
        "node_name": "Objection report generation",
        "node_code": "objection_report_generation",
        "node_type": "agent",
        "owner": "hi20260204-maker",
        "status": "partial",
        "summary": "Draft report structure is ready, but final user facts still need confirmation.",
        "structured_result": {
            "recipient_agency": "mock agency",
            "document_title": "Objection draft",
            "case_summary": "User facts and notice analysis are merged into a draft report.",
            "grounds": ["User-provided facts require final confirmation."],
            "attachment_list": ["fine_notice_image", "user_evidence"],
            "disclaimer": "This draft does not guarantee submission acceptance or disposition change.",
        },
        "evidence": [
            {
                "source_type": "user_uploaded_file",
                "title": "Fine notice attachment",
                "source_reference": "att_hi_contract",
                "metadata": {"purpose": "fine_notice"},
                "confidence": None,
            }
        ],
        "next_actions": ["confirm_user_facts", "review_report_draft"],
        "limitations": ["Final legal review and user confirmation are still required."],
        "created_at": "2026-07-01T00:00:00+00:00",
    }

    validation = validate_agent_output_envelope(
        output,
        expected_node_code="objection_report_generation",
    )

    assert validation["valid"]
    assert output["owner"] == "hi20260204-maker"


def test_hi_owned_supervisor_validation_sample_validates_as_internal_boundary():
    output = {
        "session_id": "ses_hi_supervisor",
        "message_id": "msg_hi_supervisor",
        "job_id": "job_hi_supervisor",
        "node_name": "Agent result validation",
        "node_code": "agent_result_validation",
        "node_type": "supervisor_internal",
        "owner": "hi20260204-maker",
        "status": "success",
        "summary": "Agent envelopes were checked before display DTO merge.",
        "structured_result": {
            "checked_contract_fields": [
                "node_code",
                "status",
                "summary",
                "structured_result",
                "evidence",
                "limitations",
            ],
            "rejected_results": [],
            "merge_ready": True,
        },
        "evidence": [],
        "next_actions": ["merge_display_dto"],
        "limitations": [],
        "created_at": "2026-07-01T00:00:00+00:00",
    }

    validation = validate_agent_output_envelope(
        output,
        expected_node_code="agent_result_validation",
    )

    assert validation["valid"]
    assert output["node_type"] == "supervisor_internal"
    assert output["owner"] == "hi20260204-maker"


def test_agent_contract_validators_report_malformed_collections():
    input_validation = validate_agent_input_envelope(
        {
            "analysis_plan_id": "plan_bad",
            "job_id": "job_bad",
            "session_id": "ses_bad",
            "message_id": "msg_bad",
            "node_code": "law_ground_search",
            "user_text": "법률 근거",
            "attachments": "att_bad",
            "context": {},
            "slot_state": [],
            "required_inputs": [],
            "depends_on": [],
            "upstream_results": {},
        }
    )
    output_validation = validate_agent_output_envelope(
        {
            "session_id": "ses_bad",
            "message_id": "msg_bad",
            "job_id": "job_bad",
            "node_name": "Law",
            "node_code": "law_ground_search",
            "node_type": "agent",
            "owner": "techshin31",
            "status": "success",
            "summary": "ok",
            "structured_result": [],
            "evidence": [],
            "next_actions": [],
            "limitations": [],
            "created_at": "2026-06-28T00:00:00+00:00",
        }
    )

    assert not input_validation["valid"]
    assert input_validation["invalid_collection_fields"] == ["attachments", "slot_state"]
    assert not output_validation["valid"]
    assert output_validation["invalid_collection_fields"] == ["structured_result"]


def test_execute_mock_plan_maps_analysis_steps_to_node_executions():
    plan = build_analysis_plan(
        scenario="fine_notice",
        requested_status="success",
        payload={"user_text": "고지서 이의신청서 만들어줘"},
        session_id="ses_plan",
        message_id="msg_plan",
        routing_intent="objection_request",
        pending_questions=[],
    )

    execution = execute_mock_plan(plan, {"user_text": "고지서 이의신청서 만들어줘"})

    assert execution["plan_id"] == plan["plan_id"]
    assert len(execution["executions"]) == len(plan["steps"])
    assert all(item["execution_mode"] == "sync" for item in execution["executions"])
    assert "fine_notice_analysis" in {
        item["agent_output"]["node_code"] for item in execution["executions"]
    }
    dependent_execution = next(
        item for item in execution["executions"] if item["agent_input"]["depends_on"]
    )
    assert dependent_execution["agent_input"]["upstream_results"]


def test_execute_mock_node_resolves_attachment_id_for_agent_input(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_UPLOAD_ROOT", str(tmp_path))
    attachment = register_attachment(
        {
            "session_id": "ses_agent_attachment",
            "filename": "accident_statement.pdf",
            "content_type": "application/pdf",
            "purpose": "accident_statement",
            "size_bytes": 1204,
        }
    )

    execution = execute_mock_node(
        {
            "node_code": "text_ml_case_search",
            "session_id": "ses_agent_attachment",
            "attachments": [{"attachment_id": attachment["attachment_id"]}],
        }
    )

    resolved_attachment = execution["agent_input"]["attachments"][0]
    assert resolved_attachment["purpose"] == "accident_statement"
    assert resolved_attachment["type"] == "pdf"
    assert resolved_attachment["storage_uri"] == attachment["storage_uri"]


def test_execute_sync_fine_notice_adapter_returns_supervisor_envelope_without_image():
    execution = execute_mock_node(
        {
            "execution_mode": "sync",
            "node_code": "fine_notice_analysis",
            "analysis_plan_id": "plan_sync_fine",
            "job_id": "job_sync_fine",
            "session_id": "ses_sync_fine",
            "message_id": "msg_sync_fine",
            "user_text": "고지서 분석해줘",
        }
    )

    output = execution["agent_output"]

    assert execution["execution_mode"] == "sync"
    assert execution["adapter_context"]["execution_mode"] == "sync"
    assert output["node_code"] == "fine_notice_analysis"
    assert output["status"] == "failed"
    assert output["execution_status"] == "failed"
    assert output["structured_result"]["ocr_error"] == "이미지 없음"
    assert output["structured_result"]["adapter_trace"]["execution_mode"] == "sync"
    assert validate_agent_output_envelope(output, expected_node_code="fine_notice_analysis")["valid"]


def test_execute_sync_fine_notice_adapter_reads_canonical_object_attachment(monkeypatch):
    captured_references = []

    def fake_read_object_bytes(reference):
        captured_references.append(reference)
        return b"canonical notice bytes"

    monkeypatch.setattr(agent_node_service, "read_object_bytes", fake_read_object_bytes)

    execution = execute_mock_node(
        {
            "execution_mode": "sync",
            "node_code": "fine_notice_analysis",
            "analysis_plan_id": "plan_sync_upload_bridge",
            "job_id": "job_sync_upload_bridge",
            "session_id": "ses_sync_upload_bridge",
            "message_id": "msg_sync_upload_bridge",
            "user_text": "uploaded notice attachment bridge",
            "attachments": [
                {
                    "attachment_id": "att_sync_upload_bridge",
                    "purpose": "fine_notice",
                    "content_type": "text/plain",
                    "storage_uri": "s3://skn27-demo-object-storage/canonical/uploads/usr/ses/att/notice.txt",
                    "object_storage": {
                        "provider": "mock_s3",
                        "bucket": "skn27-demo-object-storage",
                        "key": "canonical/uploads/usr/ses/att/notice.txt",
                        "storage_uri": "s3://skn27-demo-object-storage/canonical/uploads/usr/ses/att/notice.txt",
                    },
                }
            ],
        }
    )

    output = execution["agent_output"]

    assert captured_references
    assert captured_references[0]["storage_uri"].startswith("s3://")
    assert execution["execution_mode"] == "sync"
    assert output["structured_result"]["adapter_trace"]["input_source"] == "attachment"
    assert output["structured_result"]["ocr_status"] == "failed"
    assert validate_agent_output_envelope(output, expected_node_code="fine_notice_analysis")["valid"]


def test_legacy_plan_entrypoint_does_not_mock_supervisor_steps():
    plan = {
        "plan_id": "plan_hybrid_fine",
        "session_id": "ses_hybrid_fine",
        "message_id": "msg_hybrid_fine",
        "steps": [
            {"node_code": "input_context_validation", "status": "success"},
            {"node_code": "fine_notice_analysis", "status": "success", "execution_mode": "sync"},
            {"node_code": "agent_result_validation", "status": "success"},
        ],
    }

    execution = execute_mock_plan(plan, {"user_text": "고지서 분석해줘"})
    fine_execution = next(
        item for item in execution["executions"] if item["node_code"] == "fine_notice_analysis"
    )

    assert execution["execution_mode"] == "sync"
    assert fine_execution["execution_mode"] == "sync"
    assert fine_execution["agent_output"]["status"] == "failed"
    assert all(item["execution_mode"] == "sync" for item in execution["executions"])


def test_execute_sync_text_ml_case_search_adapter_returns_case_envelope(monkeypatch):
    from ai.agents.text_ml_case_search import agent as text_ml_agent

    class FakeElasticsearch:
        def __init__(self):
            self.calls = []

        def search(self, *, index, body):
            self.calls.append({"index": index, "body": body})
            if index == "precedent_fault_ratio_chunks_bm25_nori_v1":
                return {
                    "hits": {
                        "hits": [
                            {
                                "_index": "precedent_fault_ratio_chunks_bm25_nori_v1",
                                "_score": 31.5,
                                "_source": {
                                    "case_id": "616249",
                                    "chunk_id": "616249:structured_1500_250:0001",
                                    "chunk_type": "fault_ratio_evidence",
                                    "case_name": "precedent title",
                                    "case_number": "2022da287284",
                                    "court_name": "Supreme Court",
                                    "decision_date": "2025-05-15",
                                    "chunk_text": "valid precedent evidence text " * 5,
                                    "search_text": "sample search text",
                                },
                            }
                        ]
                    }
                }
            return {
                "hits": {
                    "hits": [
                        {
                            "_index": "review_case_chunks_bm25_nori_v1",
                            "_score": 10.1,
                            "_source": {
                                "review_case_id": "rc_001",
                                "review_no": "2017-032889",
                                "chunk_id": "rc_001:case_overview",
                                "chunk_type": "case_overview",
                                "case_title": "sample case",
                                "decision_fault_ratio": "A 70 : B 30",
                                "claimant_final_ratio": "70",
                                "respondent_final_ratio": "30",
                                "chunk_text": "valid review case evidence text " * 4,
                                "search_text": "sample search text",
                            },
                        }
                    ]
                }
            }

    fake_es = FakeElasticsearch()
    monkeypatch.setattr(
        text_ml_agent,
        "_optional_elasticsearch_client",
        lambda: (fake_es, ["test Elasticsearch client enabled"]),
    )

    execution = execute_mock_node(
        {
            "execution_mode": "sync",
            "node_code": "text_ml_case_search",
            "analysis_plan_id": "plan_sync_text_ml",
            "job_id": "job_sync_text_ml",
            "session_id": "ses_sync_text_ml",
            "message_id": "msg_sync_text_ml",
            "user_text": "intersection accident with side-entry collision and dashcam video",
            "attachments": [
                {
                    "attachment_id": "att_dashcam",
                    "purpose": "blackbox_video",
                    "content_type": "video/mp4",
                }
            ],
        }
    )

    output = execution["agent_output"]
    structured_result = output["structured_result"]

    assert execution["execution_mode"] == "sync"
    assert execution["adapter_context"]["execution_mode"] == "sync"
    assert output["node_code"] == "text_ml_case_search"
    assert output["status"] == "success"
    assert len(fake_es.calls) == 2
    assert structured_result["similar_cases"][0]["source_ref"] == "review_case_db:rc_001#rc_001:case_overview"
    assert structured_result["top_cases"] == structured_result["similar_cases"]
    assert structured_result["ratio_range_label"] == "A 70 : B 30"
    assert structured_result["retrieval"]["adapter_source"] == "fault_ratio_knowledge_agent"
    assert structured_result["retrieval"]["source_summary"]["source_counts"] == {
        "review_case": 1,
        "fault_ratio_precedent": 1,
    }
    assert structured_result["adapter_trace"]["execution_mode"] == "sync"
    assert output["evidence"][0]["source_type"] == "review_case"
    assert validate_agent_output_envelope(output, expected_node_code="text_ml_case_search")["valid"]


def test_execute_sync_text_ml_case_search_falls_back_to_django_review_case_rag(monkeypatch):
    from ai.agents.text_ml_case_search import agent as text_ml_agent

    monkeypatch.setattr(
        text_ml_agent,
        "_run_fault_ratio_knowledge_agent",
        lambda **_kwargs: None,
    )

    def fake_search_legal_rag(query, *, top_k, source_type):
        assert "교차로" in query
        assert top_k == 3
        assert source_type == "review_case"
        return {
            "contract_version": "legal_rag_search.v1",
            "status": "ready",
            "backend": "django_rag_tables",
            "query": query,
            "top_k": top_k,
            "result_count": 1,
            "results": [
                {
                    "source_reference": "review_case:local_chunk_001",
                    "source_type": "review_case",
                    "source_name": "local review case chunks",
                    "title": "신호 없는 교차로 직진/우측 진입 사고",
                    "summary": "선진입과 일시정지 여부가 과실 판단의 핵심 쟁점입니다.",
                    "score": 7.5,
                }
            ],
        }

    monkeypatch.setattr(text_ml_agent, "search_legal_rag", fake_search_legal_rag)

    execution = execute_mock_node(
        {
            "execution_mode": "sync",
            "node_code": "text_ml_case_search",
            "analysis_plan_id": "plan_sync_text_ml_rag",
            "job_id": "job_sync_text_ml_rag",
            "session_id": "ses_sync_text_ml_rag",
            "message_id": "msg_sync_text_ml_rag",
            "user_text": "신호 없는 교차로에서 나는 직진, 상대는 우측 진입 중 사고가 났어. 과실비율과 유사 판례를 봐줘.",
        }
    )

    output = execution["agent_output"]
    structured_result = output["structured_result"]

    assert output["status"] == "success"
    assert structured_result["similar_cases"][0]["source_ref"] == "review_case:local_chunk_001"
    assert structured_result["top_cases"] == structured_result["similar_cases"]
    assert structured_result["retrieval"]["backend"] == "django_rag_tables"
    assert structured_result["retrieval"]["source_type"] == "review_case"
    assert structured_result["retrieval"]["fallback_used"] is False
    assert output["evidence"][0]["metadata"]["retrieval_backend"] == "django_rag_tables"
    assert validate_agent_output_envelope(output, expected_node_code="text_ml_case_search")["valid"]


def test_execute_sync_law_ground_search_adapter_returns_law_envelope(monkeypatch):
    from ai.agents.law_ground_search import agent as law_agent

    calls = []

    def fake_search_law_provisions(
        *,
        query_text,
        article_refs,
        temporal_basis,
        scope,
        neo4j_session=None,
    ):
        calls.append(
            {
                "query_text": query_text,
                "article_refs": article_refs,
                "temporal_basis": temporal_basis,
                "scope": scope,
                "neo4j_session": neo4j_session,
            }
        )
        return [
            {
                "source_ref": "law_db:road_traffic#article_5",
                "chunk_id": "road_traffic:article_5",
                "source_name": "Road Traffic Act",
                "source_type": "law",
                "article_no": "5",
                "article_title": "Signal compliance",
                "source_url": "https://example.test/law/road-traffic#article-5",
                "provision_text": "Drivers must follow traffic signals.",
                "score": 0.82,
                "match_reason": "query_term_match",
            }
        ]

    monkeypatch.setattr(law_agent, "_get_neo4j_session", lambda: None)
    monkeypatch.setattr(law_agent, "search_law_provisions", fake_search_law_provisions)

    execution = execute_mock_node(
        {
            "execution_mode": "sync",
            "node_code": "law_ground_search",
            "analysis_plan_id": "plan_sync_law",
            "job_id": "job_sync_law",
            "session_id": "ses_sync_law",
            "message_id": "msg_sync_law",
            "user_text": "road traffic signal violation legal ground",
            "context": {
                "query": {
                    "raw_text": "road traffic signal violation article 5",
                    "search_query": "road traffic signal violation article 5",
                },
                "temporal_basis": {
                    "mode": "as_of",
                    "effective_at": "2026-07-06",
                },
                "scope": {"jurisdiction": "KR"},
            },
        }
    )

    output = execution["agent_output"]
    structured_result = output["structured_result"]

    assert execution["execution_mode"] == "sync"
    assert execution["adapter_context"]["execution_mode"] == "sync"
    assert output["node_code"] == "law_ground_search"
    assert output["status"] == "success"
    assert calls[0]["query_text"] == "road traffic signal violation article 5"
    assert structured_result["law_provisions"][0]["chunk_id"] == "road_traffic:article_5"
    assert structured_result["adapter_trace"]["execution_mode"] == "sync"
    assert structured_result["adapter_trace"]["input_source"] == "agent_input.context"
    assert output["evidence"][0]["source_type"] == "law"
    assert output["evidence"][0]["source_ref"] == "law_db:road_traffic#article_5"
    assert validate_agent_output_envelope(output, expected_node_code="law_ground_search")["valid"]


def test_law_ground_search_falls_back_to_django_rag(monkeypatch):
    from ai.agents.law_ground_search import search as law_search
    from app.services import legal_rag_service
    from etl.legal import search as etl_search

    monkeypatch.setattr(etl_search, "search_laws", lambda **_kwargs: [])
    monkeypatch.setattr(
        legal_rag_service,
        "search_legal_rag",
        lambda query, *, top_k, source_type: {
            "status": "ready",
            "backend": "django_rag_tables",
            "query": query,
            "top_k": top_k,
            "results": [
                {
                    "source_reference": "rag_smoke_school_zone_stop",
                    "source_type": source_type,
                    "source_name": "Road Traffic Act smoke fixture",
                    "title": "School zone emergency stopping",
                    "article": "Article 32",
                    "summary": "어린이보호구역 정차 과태료는 긴급 정차 증빙을 확인합니다.",
                    "source_url": "https://example.test/road-traffic-act",
                    "score": 4.0,
                }
            ],
        },
    )

    provisions = law_search.search_law_provisions(
        query_text="어린이보호구역 정차 과태료 이의신청",
        article_refs=[],
        temporal_basis={},
        scope={},
    )

    assert provisions[0]["chunk_id"] == "rag_smoke_school_zone_stop"
    assert provisions[0]["source_ref"] == "rag_smoke_school_zone_stop"
    assert provisions[0]["source_type"] == "law"
    assert provisions[0]["article_no"] == "Article 32"
    assert provisions[0]["provision_text"].startswith("어린이보호구역")
    assert provisions[0]["match_reason"] == "legal_rag_fallback:django_rag_tables"


def test_execute_sync_objection_report_generation_adapter_returns_form_envelope():
    execution = execute_mock_node(
        {
            "execution_mode": "sync",
            "node_code": "objection_report_generation",
            "analysis_plan_id": "plan_sync_objection",
            "job_id": "job_sync_objection",
            "session_id": "ses_sync_objection",
            "message_id": "msg_sync_objection",
            "user_text": "긴급 정차였고 표지판이 잘 보이지 않았습니다.",
            "context": {
                "user_facts": "어린이보호구역에서 갑작스러운 보행자 진입으로 안전 확보를 위해 짧게 정차했습니다.",
            },
            "upstream_results": {
                "fine_notice_analysis": {
                    "status": "success",
                    "structured_result": {
                        "notice_fields": {
                            "agency": "강남구청 교통과",
                            "violation_text": "어린이보호구역 정차 위반",
                            "violation_location": "서울특별시 강남구 테헤란로 123",
                            "violation_datetime": "2026.06.10 13:33",
                            "payment_deadline": "2026.07.02",
                        },
                        "required_documents": ["고지서 원본", "긴급 정차 사유 증빙"],
                    },
                    "evidence": [
                        {
                            "source_type": "user_uploaded_file",
                            "title": "과태료 고지서",
                            "source_reference": "att_notice",
                            "metadata": {"purpose": "fine_notice"},
                            "confidence": 0.91,
                        }
                    ],
                },
                "law_ground_search": {
                    "status": "success",
                    "structured_result": {
                        "matched_laws": [
                            {
                                "law_name": "도로교통법",
                                "article": "제32조",
                                "summary": "정차 및 주차 금지 장소 관련 조항입니다.",
                                "source_reference": "law:road_traffic:32",
                                "score": 0.82,
                            }
                        ],
                    },
                    "evidence": [
                        {
                            "source_type": "law",
                            "title": "도로교통법 제32조",
                            "source_reference": "law:road_traffic:32",
                            "metadata": {"article": "제32조"},
                            "confidence": 0.82,
                        }
                    ],
                },
            },
        }
    )

    output = execution["agent_output"]
    structured_result = output["structured_result"]
    action_types = {item["type"] for item in structured_result["report_actions"]}

    assert execution["execution_mode"] == "sync"
    assert execution["adapter_context"]["execution_mode"] == "sync"
    assert output["node_code"] == "objection_report_generation"
    assert output["status"] == "success"
    assert structured_result["document_type"] == "objection_form"
    assert structured_result["recipient_agency"] == "강남구청 교통과"
    assert structured_result["readiness"]["ready_for_download"] is True
    assert {"download_objection", "download_report"} <= action_types
    assert structured_result["adapter_trace"]["execution_mode"] == "sync"
    assert output["evidence"][0]["source_type"] == "user_uploaded_file"
    assert output["evidence"][-1]["source_type"] == "user_statement"
    assert validate_agent_output_envelope(output, expected_node_code="objection_report_generation")["valid"]


def test_execute_sync_objection_report_generation_adapter_supports_fault_ratio_inputs():
    execution = execute_mock_node(
        {
            "execution_mode": "sync",
            "node_code": "objection_report_generation",
            "analysis_plan_id": "plan_sync_objection_fault_ratio",
            "job_id": "job_sync_objection_fault_ratio",
            "session_id": "ses_sync_objection_fault_ratio",
            "message_id": "msg_sync_objection_fault_ratio",
            "user_text": "신호 없는 교차로에서 직진 중 우측 골목 차량과 접촉했습니다.",
            "upstream_results": {
                "text_ml_case_search": {
                    "status": "success",
                    "structured_result": {
                        "query_text": "신호 없는 교차로에서 직진 중 우측 골목 차량과 접촉했습니다.",
                        "normalized_description": "무신호 교차로 직진 차량과 우측 진입 차량 접촉 사고",
                        "accident_type_candidates": ["intersection_no_signal", "side_entry_collision"],
                        "issue_tags": ["선진입", "일시정지", "시야 제한"],
                        "similar_cases": [
                            {
                                "case_id": "case_fault_001",
                                "title": "무신호 교차로 직진/진입 사고",
                                "summary": "선진입과 감속 여부를 함께 본 사례입니다.",
                                "source_ref": "case_fault_001",
                            }
                        ],
                        "recommended_evidence": [
                            "original blackbox or dashcam video",
                            "scene photos including lane, signal, and impact position",
                        ],
                    },
                    "evidence": [
                        {
                            "source_type": "review_case",
                            "title": "무신호 교차로 직진/진입 사고",
                            "source_reference": "case_fault_001",
                            "metadata": {"case_id": "case_fault_001"},
                            "confidence": 0.76,
                        }
                    ],
                },
                "law_ground_search": {
                    "status": "success",
                    "structured_result": {
                        "law_provisions": [
                            {
                                "source_name": "도로교통법",
                                "article_no": "제25조",
                                "provision_text": "교차로 통행방법 및 우선순위 관련 조항입니다.",
                                "source_ref": "law:road_traffic:25",
                                "retrieval_score": 0.79,
                            }
                        ],
                    },
                    "evidence": [
                        {
                            "source_type": "law",
                            "title": "도로교통법 제25조",
                            "source_reference": "law:road_traffic:25",
                            "metadata": {"article": "제25조"},
                            "confidence": 0.79,
                        }
                    ],
                },
            },
        }
    )

    output = execution["agent_output"]
    structured_result = output["structured_result"]

    assert execution["execution_mode"] == "sync"
    assert output["node_code"] == "objection_report_generation"
    assert output["status"] == "success"
    assert structured_result["document_type"] == "objection_form"
    assert structured_result["document_variant"] == "traffic_accident"
    assert structured_result["document_title"] == "교통사고 이의신청서 초안"
    assert structured_result["recipient_agency"] == "관할 경찰서 또는 분쟁조정 기관"
    assert structured_result["requested_action"] == "사고 사실관계 재검토 및 과실비율 조정 검토"
    assert structured_result["readiness"]["ready_for_download"] is True
    assert any("선진입" in item for item in structured_result["objection_reasons"])
    assert any("블랙박스" in item for item in structured_result["required_attachments"])
    assert any(item["source_type"] == "review_case" for item in output["evidence"])
    assert validate_agent_output_envelope(output, expected_node_code="objection_report_generation")["valid"]


def test_law_ground_sync_adapter_can_feed_sync_objection_when_sync_requested(monkeypatch):
    from ai.agents.law_ground_search import agent as law_agent

    monkeypatch.setattr(law_agent, "_get_neo4j_session", lambda: None)
    monkeypatch.setattr(
        law_agent,
        "search_law_provisions",
        lambda **_kwargs: [
            {
                "source_ref": "law_db:road_traffic#article_5",
                "chunk_id": "road_traffic:article_5",
                "source_name": "Road Traffic Act",
                "source_type": "law",
                "article_no": "5",
                "article_title": "Signal compliance",
                "source_url": "https://example.test/law/road-traffic#article-5",
                "provision_text": "Drivers must follow traffic signals.",
                "score": 0.82,
            }
        ],
    )

    plan = {
        "plan_id": "plan_law_hybrid",
        "session_id": "ses_law_hybrid",
        "message_id": "msg_law_hybrid",
        "steps": [
            {
                "node_code": "law_ground_search",
                "status": "success",
                "execution_mode": "sync",
                "context": {
                    "query": {"raw_text": "road traffic signal violation article 5"},
                    "temporal_basis": {"mode": "as_of", "effective_at": "2026-07-06"},
                    "scope": {"jurisdiction": "KR"},
                },
            },
            {
                "node_code": "objection_report_generation",
                "status": "success",
                "execution_mode": "sync",
            },
        ],
    }

    execution = execute_mock_plan(
        plan,
        {
            "execution_mode": "sync",
            "user_text": "prepare legal grounds and objection report",
        },
    )

    executions_by_node = {item["node_code"]: item for item in execution["executions"]}
    assert execution["execution_mode"] == "sync"
    assert executions_by_node["law_ground_search"]["execution_mode"] == "sync"
    assert executions_by_node["objection_report_generation"]["execution_mode"] == "sync"
    assert executions_by_node["law_ground_search"]["adapter_context"]["execution_mode"] == "sync"
    assert executions_by_node["objection_report_generation"]["adapter_context"]["execution_mode"] == "sync"
    assert (
        executions_by_node["objection_report_generation"]["agent_output"]["structured_result"]["document_type"]
        == "objection_form"
    )


def test_text_ml_sync_adapter_can_mix_with_mock_vision_when_sync_requested():
    plan = {
        "plan_id": "plan_mock_only_agents",
        "session_id": "ses_mock_only_agents",
        "message_id": "msg_mock_only_agents",
        "steps": [
            {"node_code": "text_ml_case_search", "status": "success", "execution_mode": "sync"},
            {"node_code": "vision_media_analysis", "status": "success", "execution_mode": "sync"},
        ],
    }

    execution = execute_mock_plan(
        plan,
        {
            "execution_mode": "sync",
            "user_text": "사고 과실비율과 블랙박스 장면을 분석해줘",
        },
    )

    executions_by_node = {item["node_code"]: item for item in execution["executions"]}
    assert execution["execution_mode"] == "hybrid"
    assert executions_by_node["text_ml_case_search"]["execution_mode"] == "sync"
    assert executions_by_node["vision_media_analysis"]["execution_mode"] == "mock"
    assert executions_by_node["text_ml_case_search"]["adapter_context"]["execution_mode"] == "sync"
    assert executions_by_node["vision_media_analysis"]["adapter_context"]["execution_mode"] == "mock"
