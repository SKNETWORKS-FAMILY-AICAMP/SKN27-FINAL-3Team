"""Source-aware external evidence aggregation boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


CONTRACT_VERSION = "external_evidence.v1"
MCP_PROVIDERS = (
    "traffic_context_mcp",
    "police_context_mcp",
    "court_law_mcp",
)
DEFAULT_PROVIDER_STATUS = {
    "traffic_context_mcp": "disabled",
    "police_context_mcp": "disabled",
    "court_law_mcp": "disabled",
    "taas": "disabled",
    "supreme_court": "disabled",
}


def collect_external_evidence(
    query: str,
    *,
    provider_results: dict[str, dict[str, Any]] | None = None,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Merge MCP provider results without converting outages into success."""

    query_text = str(query or "").strip()
    if not query_text:
        return _unavailable_result("query_required", retrieved_at=retrieved_at)

    timestamp = retrieved_at or datetime.now(timezone.utc).isoformat()
    results = provider_results or {}
    provider_status = dict(DEFAULT_PROVIDER_STATUS)
    evidence: list[dict[str, Any]] = []
    limitations: list[str] = []

    for provider in MCP_PROVIDERS:
        result = results.get(provider)
        if not isinstance(result, dict):
            limitations.append(f"{provider}: dependency unavailable")
            continue
        status = str(result.get("status") or "failed")
        provider_status[provider] = status
        if status != "success":
            limitations.append(
                str(result.get("limitation") or f"{provider}: {status}")
            )
        for item in result.get("evidence") or []:
            if isinstance(item, dict):
                evidence.append(
                    _normalize_evidence(
                        item,
                        provider=provider,
                        retrieved_at=timestamp,
                    )
                )

    if not evidence:
        status = "dependency_unavailable"
    elif all(provider_status[name] == "success" for name in MCP_PROVIDERS):
        status = "success"
    else:
        status = "partial"

    return {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "query": query_text,
        "evidence": evidence,
        "provider_status": provider_status,
        "limitations": limitations,
        "retrieved_at": timestamp,
    }


def _normalize_evidence(
    item: dict[str, Any],
    *,
    provider: str,
    retrieved_at: str,
) -> dict[str, Any]:
    return {
        "source_type": str(item.get("source_type") or provider),
        "source_url": str(item.get("source_url") or ""),
        "source_ref": str(item.get("source_ref") or item.get("source_url") or ""),
        "summary": str(item.get("summary") or item.get("excerpt") or ""),
        "retrieved_at": str(item.get("retrieved_at") or retrieved_at),
        "data_revision": str(item.get("data_revision") or "unknown"),
        "limitation": str(
            item.get("limitation") or "원문과 적용 시점을 추가 확인해야 합니다."
        ),
    }


def _unavailable_result(reason: str, *, retrieved_at: str | None) -> dict[str, Any]:
    timestamp = retrieved_at or datetime.now(timezone.utc).isoformat()
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "dependency_unavailable",
        "query": "",
        "evidence": [],
        "provider_status": dict(DEFAULT_PROVIDER_STATUS),
        "limitations": [reason],
        "retrieved_at": timestamp,
    }
