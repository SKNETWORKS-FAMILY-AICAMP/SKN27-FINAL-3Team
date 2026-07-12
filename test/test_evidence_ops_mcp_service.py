from importlib import import_module


def _evidence_module():
    return import_module("app.services.evidence_mcp_service")


def _ops_module():
    return import_module("app.services.aws_ops_mcp_service")


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
        "사고 관련 판례",
        provider_results={},
        retrieved_at="2026-07-12T12:00:00+09:00",
    )

    assert result["status"] == "dependency_unavailable"
    assert result["evidence"] == []
    assert result["limitations"]


def test_ops_mcp_blocks_production_changes_even_with_valid_approval():
    run_aws_ops_command = _ops_module().run_aws_ops_command
    calls = []

    result = run_aws_ops_command(
        "restart_worker",
        environment="production",
        approval_token="ok",
        expected_approval_token="ok",
        adapter=lambda command: calls.append(command) or {"status": "ok"},
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "production changes are not allowed"
    assert calls == []


def test_ops_mcp_requires_approval_for_staging_mutations():
    run_aws_ops_command = _ops_module().run_aws_ops_command
    result = run_aws_ops_command(
        "replay_failed_work_item",
        environment="staging",
        approval_token="",
        expected_approval_token="ok",
        adapter=lambda command: {"status": "ok"},
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "approval_token_required"
