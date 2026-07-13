from __future__ import annotations

# ruff: noqa: E402 -- Django must be initialized before importing chatbot modules.

from copy import deepcopy
import importlib
import inspect
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import django


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from ai.agents.appeal_decision_flow import law_refs
from ai.agents.law_ground_search import agent as law_ground_search_agent
from ai.agents.law_ground_search import llm_extractor, query_understanding, search
from app.security.pii_masking import MASK_TOKEN
from app.services import agent_node_service
from app.services.agent_node_service import execute_mock_node
from app.services.history_event_mock_service import build_history_event
from chatbot import file_scan_service, object_storage


PRIVATE_ERROR = (
    "홍길동 010-1234-5678 900101-1234567 "
    "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature secret provider detail"
)


def test_history_summary_and_metadata_never_persist_raw_pii_or_secrets() -> None:
    event = build_history_event(
        event_type="ocr_completed",
        status="failed",
        summary="성명: 홍길동, 전화: 010-1234-5678 OCR 실패",
        metadata={
            "safe_note": "차량 12가3456, 주민등록번호 900101-1234567",
            "api_key": "secret-api-key-value",
        },
    )
    serialized = repr(event)

    for value in (
        "홍길동",
        "010-1234-5678",
        "12가3456",
        "900101-1234567",
        "secret-api-key-value",
    ):
        assert value not in serialized
    assert event["metadata"]["api_key"] == MASK_TOKEN


def test_agent_adapter_error_exposes_only_stable_error_metadata(monkeypatch) -> None:
    def raise_private_error(*_args, **_kwargs):
        raise RuntimeError(PRIVATE_ERROR)

    monkeypatch.setattr(agent_node_service, "_run_sync_adapter", raise_private_error)

    execution = execute_mock_node(
        {
            "execution_mode": "sync",
            "node_code": "law_ground_search",
            "job_id": "job_private_adapter_error",
            "session_id": "ses_private_adapter_error",
            "user_text": "safe legal query",
        }
    )

    assert PRIVATE_ERROR not in repr(execution)
    assert execution["adapter_error"] == {
        "error_code": "RuntimeError",
        "message": "Sync adapter execution failed.",
    }
    assert execution["agent_output"]["structured_result"]["error_message"] == (
        "Sync adapter execution failed."
    )


def test_fine_notice_adapter_internal_error_never_exposes_exception_message(monkeypatch) -> None:
    graph_module = importlib.import_module("ai.agents.fine_notice_analysis.graph")

    def raise_private_error(*_args, **_kwargs):
        raise RuntimeError(PRIVATE_ERROR)

    monkeypatch.setattr(graph_module.graph, "invoke", raise_private_error)

    execution = execute_mock_node(
        {
            "execution_mode": "sync",
            "node_code": "fine_notice_analysis",
            "job_id": "job_private_fine_notice_error",
            "session_id": "ses_private_fine_notice_error",
            "user_text": "safe fine notice query",
        }
    )

    structured = execution["agent_output"]["structured_result"]
    assert PRIVATE_ERROR not in repr(execution)
    assert structured["ocr_error"] == "Fine notice analysis failed."


def test_law_agent_does_not_print_raw_or_boosted_query(monkeypatch, capsys) -> None:
    raw_query = "홍길동 010-1234-5678 사고 법률 문의"
    monkeypatch.setattr(
        law_ground_search_agent,
        "validate_input_envelope",
        lambda _context: {"valid": True, "errors": []},
    )
    monkeypatch.setattr(
        law_ground_search_agent,
        "process_query",
        lambda **_kwargs: SimpleNamespace(
            original_query=raw_query,
            boosted_query=raw_query,
            searchability=False,
            missing_fields=["query"],
            hint_terms=[],
        ),
    )

    law_ground_search_agent.run_law_ground_search(
        {"node_code": "law_ground_search", "context": {"query": {"raw_text": raw_query}}},
        {},
    )

    captured = capsys.readouterr()
    assert raw_query not in captured.out
    assert raw_query not in captured.err


def test_law_runtime_modules_do_not_use_print_for_provider_failures() -> None:
    for module in (
        law_ground_search_agent,
        llm_extractor,
        query_understanding,
        search,
        law_refs,
    ):
        assert "print(" not in inspect.getsource(module)


def test_object_storage_error_does_not_expose_exception_message() -> None:
    details = object_storage._storage_error_kwargs(RuntimeError(PRIVATE_ERROR))

    assert PRIVATE_ERROR not in repr(details)
    assert details == {
        "reason": "s3_operation_failed",
        "error_class": "RuntimeError",
        "message": "Object storage provider operation failed.",
    }


def test_external_file_scan_metadata_is_recursively_sanitized() -> None:
    metadata = {
        "safe": "retained",
        "source_storage_uri": "mock://uploads/private/raw.bin",
        "upload_storage_lifecycle": {
            "quarantine": {"bucket": "private-quarantine-bucket"}
        },
        "nested": {
            "apiKey": "secret-api-key-value",
            "providerApiKeyBackup": "backup-provider-secret",
            "auth_token_hint": "provider-token-hint",
            "note": "010-1234-5678",
        },
    }
    original = deepcopy(metadata)

    sanitized = file_scan_service._safe_external_metadata(metadata)

    assert metadata == original
    assert sanitized == {
        "safe": "retained",
        "nested": {
            "apiKey": MASK_TOKEN,
            "providerApiKeyBackup": MASK_TOKEN,
            "auth_token_hint": MASK_TOKEN,
            "note": MASK_TOKEN,
        },
    }


def test_file_scan_unexpected_provider_responses_use_stable_messages() -> None:
    clamav = file_scan_service._clamav_findings_from_response(PRIVATE_ERROR)
    external = file_scan_service._external_findings_from_response(
        {"status": "unexpected", "message": PRIVATE_ERROR}
    )
    rejected = file_scan_service._external_findings_from_response(
        {"status": "rejected", "code": "password=synthetic-secret-value"}
    )

    assert PRIVATE_ERROR not in repr(
        {"clamav": clamav, "external": external, "rejected": rejected}
    )
    assert clamav[0]["message"] == "ClamAV returned an unexpected response."
    assert external[0]["message"] == "External scan provider returned an unexpected response."
    assert rejected[0]["code"] == "external_scan_rejected"


def test_file_scan_empty_provider_responses_fail_closed() -> None:
    clamav = file_scan_service._clamav_findings_from_response("")
    external = file_scan_service._external_findings_from_response({})

    assert clamav[0]["code"] == "scanner_unavailable"
    assert clamav[0]["reason"] == "empty_response"
    assert external[0]["code"] == "scanner_unavailable"
    assert external[0]["reason"] == "missing_verdict"

    missing_verdict_with_findings = file_scan_service._external_findings_from_response(
        {"findings": [{"category": "provider", "severity": "low"}]}
    )
    malicious_with_low_finding = file_scan_service._external_findings_from_response(
        {
            "status": "malicious",
            "findings": [{"category": "provider", "severity": "low"}],
        }
    )
    assert missing_verdict_with_findings[0]["code"] == "scanner_unavailable"
    assert malicious_with_low_finding[-1]["code"] == "external_scan_rejected"


def test_external_provider_findings_drop_untrusted_diagnostic_fields() -> None:
    finding = file_scan_service._normalize_provider_finding(
        {
            "category": "malware",
            "code": "provider_signature_match",
            "severity": "critical",
            "message": PRIVATE_ERROR,
            "diagnostic": "password=synthetic-secret-value",
            "raw_response": {"providerApiKeyBackup": "backup-provider-secret"},
        },
        provider="external",
    )

    assert finding == {
        "category": "malware",
        "code": "external_finding",
        "severity": "critical",
        "message": "File scan provider returned a finding.",
    }
