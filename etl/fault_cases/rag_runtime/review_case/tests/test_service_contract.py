from __future__ import annotations

from etl.fault_cases.rag_runtime.review_case import service


def test_handle_request_preserves_public_service_entrypoint(
    monkeypatch,
) -> None:
    expected = {
        "contract_version": "v1",
        "domain": "review_case",
        "status": "partial",
        "evidence": [],
        "calculation_result": None,
        "limitations": ["test"],
        "missing_fields": [],
    }
    monkeypatch.setattr(
        service,
        "search_review_case",
        lambda request: expected,
    )

    result = service.handle_request({"query_text": "사고"})

    assert result == expected
    assert result["calculation_result"] is None
