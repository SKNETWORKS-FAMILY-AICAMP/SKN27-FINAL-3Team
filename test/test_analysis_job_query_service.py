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
        load_progress=lambda _job_id: {
            "policy_version": "progress_cache.v1",
            "backend": "locmem",
            "key": "analysis_job_progress:job_1",
            "ttl_seconds": 300,
            "fallback": "postgresql",
            "status": "hit",
            "snapshot": {
                "job_id": "job_1",
                "status": "running",
                "owner_id": "usr_private",
                "analysis_plan_id": "plan_private",
            },
        },
    )

    assert outcome.kind == "detail"
    assert outcome.payload["job_id"] == "job_1"
    assert outcome.payload["progress_cache"] == {
        "policy_version": "progress_cache.v1",
        "backend": "locmem",
        "key": "analysis_job_progress:job_1",
        "ttl_seconds": 300,
        "fallback": "postgresql",
        "status": "hit",
        "snapshot": {"job_id": "job_1", "status": "running"},
    }
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
        "evidence": [],
        "limitations": [],
        "work_item": {},
        "progress_state": {},
        "attachment_workflows": [],
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
    assert outcome.payload["contract_version"] == "analysis_result.v2"
    assert outcome.payload["status"] == "partial"
    assert expected == {"contract_version": "analysis_result.v2", "status": "partial"}
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


def test_completed_fine_notice_result_rebuilds_persisted_law_guidance_with_its_routing_intent() -> None:
    from app.services.analysis_job_query_service import load_analysis_result
    from app.services.chat_orchestration_service import compose_agent_response

    outcome = load_analysis_result(
        "job_persisted_law",
        load_job=lambda _job_id: {
            "job_id": "job_persisted_law",
            "status": "success",
            "routing_intent": "fine_notice_procedure",
            "agent_results": [
                {
                    "node_code": "law_ground_search",
                    "status": "success",
                    "summary": "조문 5건 검색됨 (관계 확장 포함)",
                    "structured_result": {
                        "law_provisions": [
                            {
                                "source_name": "도로교통법",
                                "article_no": "제32조",
                                "provision_text": "정차 및 주차의 금지 장소에 관한 규정입니다.",
                                "source_reference": "law:query:1",
                            }
                        ]
                    },
                    "evidence": [{"source_reference": "law:query:1"}],
                    "limitations": [],
                },
                {
                    "node_code": "agent_result_validation",
                    "status": "success",
                    "structured_result": {
                        "accepted_results": ["law_ground_search"],
                        "rejected_results": [],
                        "report_ready": False,
                    },
                    "evidence": [],
                    "limitations": [],
                },
            ],
        },
        compose_response=compose_agent_response,
    )

    answer = outcome.payload["assistant_message"]["answer"]

    assert outcome.kind == "completed"
    assert "조문 5건 검색됨" not in answer
    assert "도로교통법 제32조" in answer


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
        "report_links": [],
        "attachments": [{"attachment_id": "attachment_1"}],
        "attachment_workflows": [
            {
                "contract_version": "attachment_workflow.v1",
                "attachment_id": "attachment_1",
                "state": "failed",
                "next_action": "reattach_file",
                "retryable": True,
                "missing_fields": [],
                "limitations": [
                    "현재 파일은 안전한 분석 대상으로 사용할 수 없습니다."
                ],
            }
        ],
        "reporting_payload": {"report_id": "report_1"},
        "supervisor_state": {"stage": "finalize"},
        "user_claims": [],
        "supervisor_execution": {"status": "success", "node_results": []},
        "work_item": {},
        "progress_state": {},
    }


def test_completed_result_exposes_sanitized_user_claims_only() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    outcome = load_analysis_result(
        "job_claims",
        load_job=lambda _job_id: {
            "job_id": "job_claims",
            "status": "success",
            "supervisor_state": {
                "collected_facts": {"accident_date": "2026-07-20"},
                "case_evidence": {
                    "claims": {
                        "driver_statement": {
                            "value": "The signal was yellow.",
                            "evidence_source": {
                                "source_type": "user_statement",
                                "source_ref": "attachment/private-image.png",
                                "source_message_id": "message_private",
                            },
                        }
                    }
                },
            },
        },
        compose_response=lambda _payload: {
            "contract_version": "analysis_result.v2",
            "job_id": "job_claims",
            "status": "success",
        },
    )

    assert outcome.payload["user_claims"] == [
        {
            "field": "driver_statement",
            "value": "The signal was yellow.",
            "source_type": "user_statement",
        }
    ]
    assert "attachment/private-image.png" not in repr(outcome.payload)
    assert "message_private" not in repr(outcome.payload)


def test_completed_result_projects_only_public_agent_display_fields() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    stored = {
        "job_id": "job_public_contract",
        "status": "success",
        "agent_results": [
            {
                "node_code": "law_ground_search",
                "status": "success",
                "summary": "관련 법령을 찾았습니다.",
                        "structured_result": {
                            "matched_laws": [
                                {
                                    "law_name": "도로교통법",
                                    "article": "제160조",
                                    "summary": "과태료 절차 근거",
                                    "source_reference": "law:1",
                                }
                            ]
                        },
                "evidence": [{"source_reference": "law:1"}],
                "next_actions": ["근거를 확인해 주세요."],
                "limitations": ["개별 판단은 확인이 필요합니다."],
            }
        ],
        "reporting_payload": {
            "contract_version": "reporting_payload.v2",
            "title": "이의신청 초안",
            "sections": [{"title": "신청 이유", "content": "표시용 내용"}],
            "form_data": {"applicant_name": "internal-only"},
            "appeal_decision": {"internal": True},
        },
        "supervisor_state": {
            "stage": "agent_execution_ready",
            "conversation_summary": "신청 사유를 확인했습니다.",
            "agent_input_packages": [
                {
                    "node_code": "objection_report_generation",
                    "payload": {"secret": "hidden"},
                }
            ],
            "raw_supervisor_input": {"secret": "hidden"},
        },
        "supervisor_execution": {
            "contract_version": "supervisor_execution.v1",
            "execution_mode": "async_worker",
            "job_id": "job_public_contract",
            "plan_id": "plan_internal",
            "session_id": "ses_internal",
            "node_results": [
                {
                    "node_code": "law_ground_search",
                    "status": "success",
                    "summary": "관련 법령을 찾았습니다.",
                    "structured_result": {
                        "matched_laws": [
                            {
                                "law_name": "도로교통법",
                                "article": "제160조",
                                "summary": "과태료 절차 근거",
                                "source_reference": "law:1",
                            }
                        ]
                    },
                    "agent_input": {"secret": "hidden"},
                }
            ],
        },
        "work_item": {
            "contract_version": "agent_worker_queue.v1",
            "work_item_id": "work_public_contract",
            "job_id": "job_public_contract",
            "status": "success",
            "worker_payload": {"secret": "hidden"},
        },
        "progress_state": {
            "contract_version": "agent_worker_progress.v1",
            "state": "success",
            "job_status": "success",
            "worker_payload": {"secret": "hidden"},
        },
        "supervisor_reporting_handoff": {"secret": "hidden"},
        "reporting_pipeline": {"secret": "hidden"},
    }
    original = deepcopy(stored)

    outcome = load_analysis_result(
        "job_public_contract",
        load_job=lambda _job_id: stored,
        compose_response=lambda _payload: {
            "contract_version": "analysis_result.v2",
            "status": "partial",
            "assistant_message": {"answer": "분석 결과"},
            "structured_results": {"law_ground_search": {"internal": True}},
            "agent_results": [{"internal": True}],
            "evidence": [{"source_reference": "law:1"}],
            "limitations": ["개별 판단은 확인이 필요합니다."],
            "next_actions": ["근거를 확인해 주세요."],
            "deadline_guidance": {"contract_version": "deadline_guidance.v1"},
        },
    )

    assert outcome.kind == "completed"
    assert outcome.payload["assistant_message"] == {"answer": "분석 결과"}
    assert outcome.payload["limitations"] == ["개별 판단은 확인이 필요합니다."]
    assert outcome.payload["next_actions"] == ["근거를 확인해 주세요."]
    assert outcome.payload["deadline_guidance"] == {"contract_version": "deadline_guidance.v1"}
    assert outcome.payload["reporting_payload"] == {
        "contract_version": "reporting_payload.v2",
        "title": "이의신청 초안",
        "sections": [{"title": "신청 이유", "content": "표시용 내용"}],
    }
    assert outcome.payload["supervisor_state"] == {
        "stage": "agent_execution_ready",
        "conversation_summary": "신청 사유를 확인했습니다.",
        "agent_input_packages": [{"node_code": "objection_report_generation"}],
    }
    assert outcome.payload["supervisor_execution"] == {
        "contract_version": "supervisor_execution.v1",
        "execution_mode": "async_worker",
        "job_id": "job_public_contract",
        "node_results": [
            {
                "node_code": "law_ground_search",
                "status": "success",
                "summary": "관련 법령을 찾았습니다.",
                "structured_result": {
                    "matched_laws": [
                        {
                            "law_name": "도로교통법",
                            "article": "제160조",
                            "summary": "과태료 절차 근거",
                        }
                    ]
                },
            }
        ],
    }
    assert outcome.payload["work_item"] == {
        "contract_version": "agent_worker_queue.v1",
        "work_item_id": "work_public_contract",
        "job_id": "job_public_contract",
        "status": "success",
    }
    assert outcome.payload["progress_state"] == {
        "contract_version": "agent_worker_progress.v1",
        "state": "success",
        "job_status": "success",
    }
    for field in (
        "structured_results",
        "agent_results",
        "supervisor_reporting_handoff",
        "reporting_pipeline",
        "supervisor_handoff",
    ):
        assert field not in outcome.payload
    assert stored == original


def test_detail_projects_only_public_restore_fields() -> None:
    from app.services.analysis_job_query_service import load_analysis_job_detail

    stored = {
        "job_id": "job_public_detail",
        "session_id": "ses_public_detail",
        "message_id": "msg_public_detail",
        "status": "partial",
        "assistant_message": "A safe summary.",
        "assistant_message_payload": {
            "answer": "A safe answer.",
            "summary": "A safe summary.",
            "report_id": "rep_public",
            "report_status": "ready",
            "source_fingerprint": "must-not-leak",
        },
        "cards": [{"title": "Safe card"}],
        "pending_questions": [{"field": "incident_date", "question": "When?"}],
        "attachments": [{
            "attachment_id": "att_public",
            "filename": "notice.pdf",
            "storage_uri": "s3://private-bucket/notice.pdf",
        }],
        "report_links": [{
            "report_id": "rep_public",
            "action": "detail",
            "signed_url": "https://storage.example/report?sig=secret",
        }],
        "reporting_payload": {"report_id": "rep_public", "title": "Safe report"},
        "supervisor_state": {"stage": "finalize", "trace_id": "trace-private"},
        "supervisor_execution": {
            "status": "success",
            "node_results": [{
                "node_code": "fine_notice_analysis",
                "status": "success",
                "structured_result": {"storage_uri": "s3://private-bucket/raw.json"},
                "limitations": ["RuntimeError: raw exception"],
            }],
        },
        "reports": [{
            "report_id": "rep_public",
            "status": "ready",
            "title": "Safe report",
            "content_summary": "Safe report summary",
            "storage_uri": "s3://private-bucket/report.pdf",
            "object_storage": {"bucket": "private-bucket", "key": "report.pdf"},
            "report_quality": {
                "trace_id": "trace-private",
                "public_quality_summary": {
                    "status": "partial",
                    "limitations": ["Latest revision may not be reflected."],
                },
            },
        }],
        "report_count": 1,
        "latest_report_id": "rep_public",
        "created_at": "2026-07-27T10:00:00+09:00",
        "updated_at": "2026-07-27T10:01:00+09:00",
        "owner_id": "usr_private",
        "metadata": {"debug_blob": "private"},
        "agent_results": [{"raw_exception": "private"}],
        "storage_uri": "s3://private-bucket/job.json",
    }

    outcome = load_analysis_job_detail(
        "job_public_detail",
        load_job=lambda _job_id: stored,
        load_progress=lambda _job_id: {"state": "running", "debug_blob": "private"},
    )

    assert outcome.kind == "detail"
    assert outcome.payload["job_id"] == "job_public_detail"
    assert outcome.payload["assistant_message_payload"] == {
        "answer": "A safe answer.",
        "summary": "A safe summary.",
        "report_id": "rep_public",
        "report_status": "ready",
    }
    assert outcome.payload["attachments"] == [
        {"attachment_id": "att_public", "filename": "notice.pdf"}
    ]
    assert outcome.payload["report_links"] == [
        {"report_id": "rep_public", "action": "detail"}
    ]
    assert outcome.payload["supervisor_execution"]["node_results"] == [
        {"node_code": "fine_notice_analysis", "status": "success"}
    ]
    assert outcome.payload["reports"] == [{
        "report_id": "rep_public",
        "status": "ready",
        "title": "Safe report",
        "content_summary": "Safe report summary",
        "report_quality": {
            "public_quality_summary": {
                "status": "partial",
                "partial_result": True,
                "review_required": True,
                "freshness": {},
                "retrieval": {
                    "backend_label": None,
                    "result_count": None,
                    "used_fallback": False,
                },
                "limitation_count": 1,
                "limitations": ["Latest revision may not be reflected."],
            }
        },
    }]
    public_json = repr(outcome.payload)
    for private_value in (
        "private-bucket",
        "sig=secret",
        "trace-private",
        "debug_blob",
        "RuntimeError",
        "usr_private",
        "must-not-leak",
    ):
        assert private_value not in public_json


def test_completed_result_projects_only_safe_public_quality_summary() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    outcome = load_analysis_result(
        "job_quality",
        load_job=lambda _job_id: {
            "job_id": "job_quality",
            "status": "partial",
            "agent_results": [
                {
                    "node_code": "law_ground_search",
                    "status": "partial",
                    "structured_result": {
                        "matched_laws": [{"law_name": "Road Traffic Act", "source_reference": "law:1"}],
                        "retrieval": {
                            "status": "partial",
                            "backend": "postgres_pgvector",
                            "result_count": 1,
                            "retrieved_at": "2026-07-27T09:00:00+09:00",
                            "effective_at": "2026-07-20",
                            "query": "must-not-leak",
                            "embedding": {"model": "text-embedding-3-large"},
                            "sql_tables": ["law_embeddings"],
                        },
                        "public_quality_summary": {
                            "status": "partial",
                            "partial_result": True,
                            "review_required": True,
                            "freshness": {
                                "effective_at": "2026-07-20",
                                "retrieved_at": "2026-07-27T09:00:00+09:00",
                                "limitation": "Latest revision may not be reflected.",
                            },
                            "retrieval": {
                                "backend_label": "law retrieval",
                                "result_count": 1,
                                "used_fallback": False,
                            },
                            "limitation_count": 1,
                            "limitations": ["Latest revision may not be reflected."],
                        },
                    },
                    "limitations": ["Latest revision may not be reflected."],
                }
            ],
            "supervisor_execution": {
                "node_results": [
                    {
                        "node_code": "law_ground_search",
                        "status": "partial",
                        "structured_result": {
                            "matched_laws": [{"law_name": "Road Traffic Act", "source_reference": "law:1"}],
                            "retrieval": {
                                "status": "partial",
                                "backend": "postgres_pgvector",
                                "result_count": 1,
                                "retrieved_at": "2026-07-27T09:00:00+09:00",
                                "effective_at": "2026-07-20",
                                "query": "must-not-leak",
                                "embedding": {"model": "text-embedding-3-large"},
                                "sql_tables": ["law_embeddings"],
                            },
                            "public_quality_summary": {
                                "status": "partial",
                                "partial_result": True,
                                "review_required": True,
                                "freshness": {
                                    "effective_at": "2026-07-20",
                                    "retrieved_at": "2026-07-27T09:00:00+09:00",
                                    "limitation": "Latest revision may not be reflected.",
                                },
                                "retrieval": {
                                    "backend_label": "law retrieval",
                                    "result_count": 1,
                                    "used_fallback": False,
                                },
                                "limitation_count": 1,
                                "limitations": ["Latest revision may not be reflected."],
                            },
                        },
                    }
                ]
            },
        },
        compose_response=lambda _payload: {
            "contract_version": "analysis_result.v2",
            "job_id": "job_quality",
            "status": "partial",
        },
    )

    node = outcome.payload["supervisor_execution"]["node_results"][0]
    assert node["structured_result"]["public_quality_summary"]["retrieval"] == {
        "backend_label": "law retrieval",
        "result_count": 1,
        "used_fallback": False,
    }
    assert node["structured_result"]["retrieval"] == {
        "status": "partial",
        "backend": "postgres_pgvector",
        "result_count": 1,
        "retrieved_at": "2026-07-27T09:00:00+09:00",
        "effective_at": "2026-07-20",
    }
    assert "query" not in repr(node)
    assert "law_embeddings" not in repr(node)
    assert "text-embedding-3-large" not in repr(node)


def test_law_public_projection_drops_nested_private_metadata_and_unsafe_limitations() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    private = {
        "source_url": "https://storage.example/signed?sig=secret",
        "storage_uri": "s3://private-bucket/law.json",
        "provenance": {"bucket": "private-bucket", "key": "law.json"},
        "source_reference": "https://storage.example/signed?sig=secret",
        "law_name": "Road Traffic Act",
    }
    outcome = load_analysis_result(
        "job_private_law_metadata",
        load_job=lambda _job_id: {
            "job_id": "job_private_law_metadata",
            "status": "partial",
            "supervisor_execution": {
                "node_results": [
                    {
                        "node_code": "law_ground_search",
                        "status": "partial",
                        "structured_result": {
                            "matched_laws": [private],
                            "law_provisions": [
                                {
                                    "source_name": "Road Traffic Act",
                                    "provision_text": "Safe public text",
                                    "source_url": "https://storage.example/signed?sig=secret",
                                    "provenance": {"bucket": "private-bucket"},
                                }
                            ],
                            "freshness": {
                                "effective_at": "2026-07-20",
                                "retrieved_at": "2026-07-27T09:00:00+09:00",
                                "dataset_version": "sha256:private",
                                "storage_uri": "s3://private-bucket/law.json",
                                "limitation": "Latest revision may not be reflected.",
                            },
                            "retrieval": {
                                "status": "partial",
                                "backend": "postgres_pgvector",
                                "attempted_backends": [
                                    {"backend": "postgres_pgvector", "error": "RuntimeError: raw exception"},
                                    {"storage_uri": "https://storage.example/signed?sig=secret"},
                                ],
                            },
                            "public_quality_summary": {
                                "status": "partial",
                                "partial_result": True,
                                "review_required": True,
                                "limitations": ["RuntimeError: raw exception", "Latest revision may not be reflected."],
                            },
                        },
                    }
                ]
            },
        },
        compose_response=lambda _payload: {"contract_version": "analysis_result.v2"},
    )

    node = outcome.payload["supervisor_execution"]["node_results"][0]
    structured = node["structured_result"]
    assert structured["matched_laws"] == []
    assert "law_provisions" not in structured
    assert structured["freshness"] == {
        "effective_at": "2026-07-20",
        "retrieved_at": "2026-07-27T09:00:00+09:00",
        "limitation": "Latest revision may not be reflected.",
    }
    assert structured["retrieval"]["attempted_backends"] == "multiple"
    assert structured["public_quality_summary"]["limitations"] == [
        "Latest revision may not be reflected."
    ]
    assert "private-bucket" not in repr(node)
    assert "signed?sig=secret" not in repr(node)
    assert "RuntimeError: raw exception" not in repr(node)


def test_law_public_projection_drops_scalar_source_references() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    outcome = load_analysis_result(
        "job_scalar_law_refs",
        load_job=lambda _job_id: {
            "job_id": "job_scalar_law_refs",
            "status": "success",
            "supervisor_execution": {
                "node_results": [
                    {
                        "node_code": "law_ground_search",
                        "status": "success",
                        "structured_result": {
                            "matched_laws": ["law:server"],
                            "public_quality_summary": {"status": "ready"},
                        },
                    }
                ]
            },
        },
        compose_response=lambda payload: payload,
    )

    node = outcome.payload["supervisor_execution"]["node_results"][0]
    assert node["structured_result"]["matched_laws"] == []


def test_law_public_projection_does_not_invent_quality_summary_without_public_signals() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    outcome = load_analysis_result(
        "job_scalar_law_refs_without_summary",
        load_job=lambda _job_id: {
            "job_id": "job_scalar_law_refs_without_summary",
            "status": "success",
            "supervisor_execution": {
                "node_results": [
                    {
                        "node_code": "law_ground_search",
                        "status": "success",
                        "structured_result": {
                            "matched_laws": ["law:server"],
                        },
                    }
                ]
            },
        },
        compose_response=lambda payload: payload,
    )

    node = outcome.payload["supervisor_execution"]["node_results"][0]
    assert node["structured_result"] == {"matched_laws": []}


def test_law_public_projection_builds_summary_when_missing() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    outcome = load_analysis_result(
        "job_missing_quality_summary",
        load_job=lambda _job_id: {
            "job_id": "job_missing_quality_summary",
            "status": "success",
            "supervisor_execution": {
                "node_results": [
                    {
                        "node_code": "law_ground_search",
                        "status": "success",
                        "structured_result": {
                            "matched_laws": [{"law_name": "Road Traffic Act"}],
                            "retrieval": {
                                "status": "ready",
                                "backend": "postgres_pgvector",
                                "result_count": 1,
                            },
                        },
                    }
                ]
            },
        },
        compose_response=lambda _payload: {"contract_version": "analysis_result.v2"},
    )

    summary = outcome.payload["supervisor_execution"]["node_results"][0]["structured_result"][
        "public_quality_summary"
    ]
    assert summary == {
        "status": "ready",
        "partial_result": False,
        "review_required": False,
        "freshness": {},
        "retrieval": {
            "backend_label": "postgres_pgvector",
            "result_count": 1,
            "used_fallback": False,
        },
        "limitation_count": 0,
        "limitations": [],
    }


def test_law_node_projection_sanitizes_node_level_limitations() -> None:
    from app.services.analysis_job_query_service import _project_supervisor_execution

    projected = _project_supervisor_execution(
        {
            "node_results": [
                {
                    "node_code": "law_ground_search",
                    "status": "partial",
                    "limitations": [
                        "RuntimeError: raw exception",
                        "Latest revision may not be reflected.",
                    ],
                    "structured_result": {},
                }
            ]
        }
    )

    assert projected is not None
    assert projected["node_results"][0]["limitations"] == [
        "Latest revision may not be reflected."
    ]


def test_completed_result_projects_safe_attachments_links_and_non_law_nodes() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    outcome = load_analysis_result(
        "job_public_result",
        load_job=lambda _job_id: {
            "job_id": "job_public_result",
            "status": "success",
            "attachments": [{
                "attachment_id": "att_public",
                "purpose": "fine_notice",
                "storage_uri": "s3://private-bucket/notice.pdf",
            }],
            "report_links": [{
                "report_id": "rep_public",
                "action": "detail",
                "signed_url": "https://storage.example/report?sig=secret",
            }],
            "supervisor_execution": {
                "node_results": [{
                    "node_code": "fine_notice_analysis",
                    "status": "success",
                    "structured_result": {"storage_uri": "s3://private-bucket/raw.json"},
                    "limitations": ["RuntimeError: raw exception"],
                }],
            },
        },
        compose_response=lambda _payload: {"contract_version": "analysis_result.v2"},
    )

    assert outcome.payload["attachments"] == [
        {"attachment_id": "att_public", "purpose": "fine_notice"}
    ]
    assert outcome.payload["report_links"] == [
        {"report_id": "rep_public", "action": "detail"}
    ]
    assert outcome.payload["supervisor_execution"]["node_results"] == [
        {"node_code": "fine_notice_analysis", "status": "success"}
    ]
    assert "private-bucket" not in repr(outcome.payload)
    assert "sig=secret" not in repr(outcome.payload)
    assert "RuntimeError" not in repr(outcome.payload)


def test_pending_result_projects_only_worker_polling_fields() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    outcome = load_analysis_result(
        "job_queued",
        load_job=lambda _job_id: {
            "job_id": "job_queued",
            "status": "queued",
            "active_node": "attachment_document_classification",
            "attachments": [
                {
                    "attachment_id": "att_queued",
                    "status": "ready",
                    "scan_status": "clean",
                    "storage_uri": "s3://private/att_queued",
                }
            ],
            "work_item": {
                "contract_version": "agent_worker_queue.v1",
                "work_item_id": "work_1",
                "job_id": "job_queued",
                "status": "queued",
                "worker_payload": {"secret": "hidden"},
            },
            "progress_state": {
                "contract_version": "agent_worker_progress.v1",
                "state": "queued",
                "job_status": "queued",
                "worker_payload": {"secret": "hidden"},
            },
        },
        compose_response=lambda _payload: AssertionError("pending results do not compose"),
    )

    assert outcome.kind == "pending"
    assert outcome.payload["work_item"] == {
        "contract_version": "agent_worker_queue.v1",
        "work_item_id": "work_1",
        "job_id": "job_queued",
        "status": "queued",
    }
    assert outcome.payload["progress_state"] == {
        "contract_version": "agent_worker_progress.v1",
        "state": "queued",
        "job_status": "queued",
    }
    assert outcome.payload["attachment_workflows"][0]["state"] == (
        "classification_running"
    )
    assert "s3://" not in repr(outcome.payload["attachment_workflows"])
    assert "structured_results" not in outcome.payload


def test_completed_result_projects_normalized_fact_conflicts_only() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    outcome = load_analysis_result(
        "job_conflict",
        load_job=lambda _job_id: {
            "job_id": "job_conflict",
            "status": "partial",
            "supervisor_state": {
                "stage": "intake",
                "fact_conflicts": [
                    {
                        "field": "signal_priority",
                        "candidates": [
                            {
                                "value": "녹색 신호",
                                "source_message_id": "msg_conflict",
                                "confidence": 0.9,
                            },
                            {
                                "value": "적색 신호",
                                "source_message_id": "msg_conflict",
                                "confidence": 0.8,
                            },
                        ],
                    },
                    {
                        "field": "signal_priority",
                        "candidates": [],
                        "debug": "must-not-leak",
                    },
                ],
            },
            "agent_results": [],
        },
        compose_response=lambda _payload: {
            "contract_version": "analysis_result.v2",
            "status": "partial",
        },
    )

    assert outcome.payload["supervisor_state"]["fact_conflicts"] == [
        {
            "field": "signal_priority",
            "candidates": [
                {
                    "value": "녹색 신호",
                    "source_message_id": "msg_conflict",
                    "confidence": 0.9,
                },
                {
                    "value": "적색 신호",
                    "source_message_id": "msg_conflict",
                    "confidence": 0.8,
                },
            ],
        }
    ]
    assert "must-not-leak" not in repr(outcome.payload)


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


def test_completed_result_rebuilds_safe_attachment_workflow_from_persisted_data() -> None:
    from app.services.analysis_job_query_service import load_analysis_result

    stored = {
        "job_id": "job_attachment_workflow",
        "status": "partial",
        "active_node": "fine_notice_analysis",
        "attachments": [
            {
                "attachment_id": "att_notice",
                "purpose": "fine_notice",
                "status": "ready",
                "scan_status": "clean",
                "storage_uri": "s3://private/notices/att_notice",
                "filename": "private-notice.pdf",
            }
        ],
        "agent_results": [
            {
                "node_code": "attachment_document_classification",
                "status": "success",
                "structured_result": {
                    "attachment_id": "att_notice",
                    "status": "success",
                },
            },
            {
                "node_code": "fine_notice_analysis",
                "status": "partial",
                "structured_result": {
                    "attachment_id": "att_notice",
                    "requires_confirmation": True,
                    "missing_fields": ["response_deadline"],
                    "raw_ocr_text": "private OCR text",
                },
            },
        ],
    }

    outcome = load_analysis_result(
        "job_attachment_workflow",
        load_job=lambda _job_id: stored,
        compose_response=lambda _payload: {
            "contract_version": "analysis_result.v2",
            "status": "partial",
            "assistant_message": {"answer": "확인이 필요합니다."},
        },
    )

    assert outcome.payload["attachment_workflows"] == [
        {
            "contract_version": "attachment_workflow.v1",
            "attachment_id": "att_notice",
            "state": "ocr_needs_confirmation",
            "next_action": "confirm_ocr_fields",
            "retryable": False,
            "missing_fields": ["response_deadline"],
            "limitations": [],
        }
    ]
    assert "s3://" not in repr(outcome.payload["attachment_workflows"])
    assert "private OCR" not in repr(outcome.payload["attachment_workflows"])


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
