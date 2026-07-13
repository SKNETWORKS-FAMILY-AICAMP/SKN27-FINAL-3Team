from importlib import import_module


def _evidence_module():
    return import_module("app.services.evidence_mcp_service")


def test_external_evidence_keeps_source_metadata_and_reports_partial_dependencies():
    result = _evidence_module().collect_external_evidence(
        "신호 없는 교차로 사고",
        provider_results={
            "traffic_context_mcp": {
                "status": "success",
                "evidence": [
                    {
                        "source_url": "https://example.test/road/1",
                        "data_revision": "2026-07-12",
                        "summary": "교차로 도로 구조",
                    }
                ],
            },
            "police_context_mcp": {"status": "disabled", "evidence": []},
            "court_law_mcp": {"status": "disabled", "evidence": []},
        },
        retrieved_at="2026-07-12T12:00:00+09:00",
    )

    assert result["contract_version"] == "external_evidence.v1"
    assert result["status"] == "partial"
    assert result["provider_status"]["traffic_context_mcp"] == "success"
    assert result["provider_status"]["police_context_mcp"] == "disabled"
    assert result["provider_status"]["taas"] == "disabled"
    assert result["provider_status"]["supreme_court"] == "disabled"
    assert result["evidence"][0]["source_url"] == "https://example.test/road/1"
    assert result["evidence"][0]["retrieved_at"] == "2026-07-12T12:00:00+09:00"
    assert result["evidence"][0]["data_revision"] == "2026-07-12"
    assert "limitation" in result["evidence"][0]


def test_external_evidence_does_not_fake_success_when_every_provider_is_unavailable():
    result = _evidence_module().collect_external_evidence(
        "사고 관련 자료",
        provider_results={},
        retrieved_at="2026-07-12T12:00:00+09:00",
    )

    assert result["status"] == "dependency_unavailable"
    assert result["evidence"] == []
    assert result["limitations"]


def test_external_evidence_preserves_partial_gateway_evidence():
    result = _evidence_module().collect_external_evidence(
        "일부 제공자만 응답한 질의",
        provider_results={
            "traffic_context_mcp": {
                "status": "partial",
                "limitation": "교통량 세부 정보는 조회하지 못했습니다.",
                "evidence": [
                    {
                        "source_ref": "traffic:partial:1",
                        "summary": "교차로 구조는 확인했습니다.",
                        "data_revision": "2026-07-12",
                    }
                ],
            },
            "police_context_mcp": {"status": "disabled", "evidence": []},
            "court_law_mcp": {"status": "disabled", "evidence": []},
        },
        retrieved_at="2026-07-12T12:00:00+09:00",
    )

    assert result["status"] == "partial"
    assert result["evidence"][0]["source_ref"] == "traffic:partial:1"


def test_external_evidence_distinguishes_successful_no_results_from_outage():
    result = _evidence_module().collect_external_evidence(
        "검색 결과가 없는 질의",
        provider_results={
            "traffic_context_mcp": {"status": "success", "evidence": []},
            "police_context_mcp": {"status": "success", "evidence": []},
            "court_law_mcp": {"status": "success", "evidence": []},
        },
        retrieved_at="2026-07-12T12:00:00+09:00",
    )

    assert result["status"] == "no_results"
    assert result["evidence"] == []
    assert result["limitations"] == ["검색 조건과 일치하는 외부 근거가 없습니다."]


def test_external_evidence_rejects_items_without_required_source_fields():
    result = _evidence_module().collect_external_evidence(
        "출처가 불완전한 근거",
        provider_results={
            "traffic_context_mcp": {"status": "success", "evidence": [{}]},
            "police_context_mcp": {"status": "success", "evidence": []},
            "court_law_mcp": {"status": "success", "evidence": []},
        },
        retrieved_at="2026-07-12T12:00:00+09:00",
    )

    assert result["status"] == "no_results"
    assert result["evidence"] == []
    assert "traffic_context_mcp: invalid evidence item" in result["limitations"]


def test_external_evidence_treats_taas_and_supreme_court_as_upstream_sources():
    result = _evidence_module().collect_external_evidence(
        "정상 근거",
        provider_results={
            "traffic_context_mcp": {
                "status": "success",
                "evidence": [
                    {
                        "source_ref": "traffic:1",
                        "summary": "도로 구조",
                        "data_revision": "2026-07-12",
                    }
                ],
            },
            "police_context_mcp": {"status": "success", "evidence": []},
            "court_law_mcp": {"status": "success", "evidence": []},
            "taas": {"status": "success"},
            "supreme_court": {"status": "disabled"},
        },
        retrieved_at="2026-07-12T12:00:00+09:00",
    )

    assert result["status"] == "success"
    assert result["provider_roles"]["traffic_context_mcp"] == "gateway"
    assert result["provider_roles"]["taas"] == "upstream"
    assert result["provider_status"]["taas"] == "success"
