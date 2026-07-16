"""Canonical output contract helpers for law-ground retrieval results."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


LAW_RETRIEVAL_CONTRACT_VERSION = "law_retrieval.v1"


def normalize_law_structured_result(value: Any) -> dict[str, Any]:
    """Return source-backed law matches and explicit retrieval metadata."""

    structured = deepcopy(value) if isinstance(value, dict) else {}
    provisions = _canonical_provisions(structured.get("law_provisions"))
    existing_matches = _canonical_matches(structured.get("matched_laws"))
    matched_laws = [_match_from_provision(item) for item in provisions] or existing_matches

    retrieval = _retrieval_metadata(structured, provisions)
    for provision in provisions:
        provision.pop("_retrieval", None)
    backend = _text(retrieval.get("backend")) or _backend_from_provisions(provisions)
    retrieval["backend"] = backend or None

    attempted_backends = _attempted_backends(retrieval.get("attempted_backends"))
    attempted_names = {
        _text(item.get("backend")) if isinstance(item, dict) else _text(item)
        for item in attempted_backends
    }
    if backend and backend not in attempted_names:
        attempted_backends.append(backend)
    retrieval["attempted_backends"] = attempted_backends
    if not _text(retrieval.get("contract_version")):
        retrieval["contract_version"] = LAW_RETRIEVAL_CONTRACT_VERSION

    current_status = _text(retrieval.get("status"))
    if matched_laws:
        retrieval["status"] = current_status or "ready"
    elif current_status in {"failed", "error", "unavailable"}:
        retrieval["status"] = current_status
    else:
        retrieval["status"] = "empty"

    if "law_provisions" in structured:
        structured["law_provisions"] = provisions
    structured["matched_laws"] = matched_laws
    structured["retrieval"] = retrieval
    structured["retrieval_quality"] = (
        _text(structured.get("retrieval_quality")) or backend or "unavailable"
    )
    return structured


def normalize_law_evidence(value: Any) -> list[dict[str, Any]]:
    """Accept legacy aliases at the adapter boundary and emit canonical provenance."""

    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source_reference = _source_reference(item)
        if not source_reference:
            continue
        record = deepcopy(item)
        record["source_reference"] = source_reference
        record.pop("source_ref", None)
        normalized.append(record)
    return normalized


def _canonical_provisions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    provisions: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source_reference = _source_reference(item)
        if not source_reference:
            continue
        provision = deepcopy(item)
        provision["source_reference"] = source_reference
        provision.pop("source_ref", None)
        provisions.append(provision)
    return provisions


def _canonical_matches(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    matches: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source_reference = _source_reference(item)
        if not source_reference:
            continue
        match = deepcopy(item)
        match["source_reference"] = source_reference
        match.pop("source_ref", None)
        matches.append(match)
    return matches


def _match_from_provision(provision: dict[str, Any]) -> dict[str, Any]:
    return {
        "law_name": provision.get("law_name") or provision.get("source_name"),
        "article": provision.get("article") or provision.get("article_no"),
        "title": provision.get("title") or provision.get("article_title"),
        "summary": provision.get("summary") or provision.get("provision_text"),
        "source_url": provision.get("source_url"),
        "source_reference": provision["source_reference"],
        "score": (
            provision.get("retrieval_score")
            if provision.get("retrieval_score") is not None
            else provision.get("score")
        ),
    }


def _retrieval_metadata(
    structured: dict[str, Any],
    provisions: list[dict[str, Any]],
) -> dict[str, Any]:
    if isinstance(structured.get("retrieval"), dict):
        return deepcopy(structured["retrieval"])
    for provision in provisions:
        if isinstance(provision.get("_retrieval"), dict):
            return deepcopy(provision["_retrieval"])
    return {}


def _backend_from_provisions(provisions: list[dict[str, Any]]) -> str:
    marker = "legal_rag_fallback:"
    for provision in provisions:
        reason = _text(provision.get("match_reason"))
        if reason.startswith(marker):
            return reason.removeprefix(marker)
    return ""


def _source_reference(item: dict[str, Any]) -> str:
    return (
        _text(item.get("source_reference"))
        or _text(item.get("source_ref"))
        or _text(item.get("chunk_id"))
    )


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _attempted_backends(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return deepcopy(value)
