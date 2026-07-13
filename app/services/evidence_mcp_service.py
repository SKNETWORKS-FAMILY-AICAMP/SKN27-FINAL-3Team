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
UPSTREAM_PROVIDERS = ("taas", "supreme_court")
PROVIDER_ROLES = {
    **{provider: "gateway" for provider in MCP_PROVIDERS},
    **{provider: "upstream" for provider in UPSTREAM_PROVIDERS},
}
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
    successful_gateways = 0
    available_gateways = 0

    for provider in MCP_PROVIDERS:
        result = results.get(provider)
        if not isinstance(result, dict):
            limitations.append(f"{provider}: dependency unavailable")
            continue
        status = str(result.get("status") or "failed")
        provider_status[provider] = status
        if status == "success":
            successful_gateways += 1
            available_gateways += 1
        elif status == "partial":
            available_gateways += 1
            limitations.append(
                str(result.get("limitation") or f"{provider}: {status}")
            )
        else:
            limitations.append(
                str(result.get("limitation") or f"{provider}: {status}")
            )
        for item in result.get("evidence") or []:
            if isinstance(item, dict):
                normalized = _normalize_evidence(
                    item,
                    provider=provider,
                    retrieved_at=timestamp,
                )
                if normalized is None:
                    limitations.append(f"{provider}: invalid evidence item")
                else:
                    evidence.append(normalized)

    for provider in UPSTREAM_PROVIDERS:
        result = results.get(provider)
        if isinstance(result, dict):
            provider_status[provider] = str(result.get("status") or "failed")

    if available_gateways == 0:
        status = "dependency_unavailable"
    elif successful_gateways == len(MCP_PROVIDERS):
        if evidence:
            status = "success"
        else:
            status = "no_results"
            limitations.append("검색 조건과 일치하는 외부 근거가 없습니다.")
    else:
        status = "partial"

    return {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "query": query_text,
        "evidence": evidence,
        "provider_status": provider_status,
        "provider_roles": dict(PROVIDER_ROLES),
        "limitations": limitations,
        "retrieved_at": timestamp,
    }


def _normalize_evidence(
    item: dict[str, Any],
    *,
    provider: str,
    retrieved_at: str,
) -> dict[str, Any] | None:
    source_url = str(item.get("source_url") or "").strip()
    source_ref = str(item.get("source_ref") or source_url).strip()
    summary = str(item.get("summary") or item.get("excerpt") or "").strip()
    data_revision = str(item.get("data_revision") or "").strip()
    if not source_ref or not summary or not data_revision:
        return None
    return {
        "source_type": str(item.get("source_type") or provider),
        "source_url": source_url,
        "source_ref": source_ref,
        "summary": summary,
        "retrieved_at": str(item.get("retrieved_at") or retrieved_at),
        "data_revision": data_revision,
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
        "provider_roles": dict(PROVIDER_ROLES),
        "limitations": [reason],
        "retrieved_at": timestamp,
    }
