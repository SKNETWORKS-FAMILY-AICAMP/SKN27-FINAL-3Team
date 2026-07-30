"""판례 검색 요청·응답 계약과 런타임 검증."""

from __future__ import annotations

import math
from typing import Any, Literal, TypedDict

from .errors import SearchStageError


class SearchRequest(TypedDict):
    contract_version: str
    request_id: str
    query_text: str


class SearchResult(TypedDict):
    rank: int
    record_id: str
    case_number: str
    case_name: str
    court_name: str
    decision_date: str
    candidate_block_id: str
    candidate_block_type: str
    evidence_text: str
    retrieval_score: float
    rerank_score: float


class SearchError(TypedDict):
    code: str
    message: str
    stage: str
    retryable: bool


class SearchResponse(TypedDict):
    contract_version: str
    request_id: str
    domain: Literal["precedent"]
    status: Literal["success", "partial", "failed"]
    backend: str
    candidate_count: int
    results: list[SearchResult]
    latency_ms: dict[str, float]
    error: SearchError | None
    limitations: list[str]


_REQUEST_KEYS = {"contract_version", "request_id", "query_text"}
_LATENCY_KEYS = {"embedding", "retrieval", "context", "rerank", "total"}


def _contract_error(message: str) -> SearchStageError:
    return SearchStageError(
        code="CONTRACT_VIOLATION",
        message=message,
        stage="contract",
        retryable=False,
    )


def validate_request(payload: Any) -> SearchRequest:
    if not isinstance(payload, dict):
        raise SearchStageError(
            code="INVALID_REQUEST",
            message="요청은 JSON 객체여야 합니다.",
            stage="request",
        )

    extra_keys = set(payload) - _REQUEST_KEYS
    if extra_keys:
        raise SearchStageError(
            code="INVALID_REQUEST",
            message=f"허용되지 않은 요청 필드: {', '.join(sorted(extra_keys))}",
            stage="request",
        )

    version = payload.get("contract_version")
    request_id = payload.get("request_id")
    query_text = payload.get("query_text")
    if not isinstance(version, str) or not version.strip():
        raise SearchStageError(
            code="INVALID_REQUEST",
            message="contract_version이 필요합니다.",
            stage="request",
        )
    if not isinstance(request_id, str) or not request_id.strip():
        raise SearchStageError(
            code="INVALID_REQUEST",
            message="request_id가 필요합니다.",
            stage="request",
        )
    if not isinstance(query_text, str) or not query_text.strip():
        raise SearchStageError(
            code="EMPTY_QUERY",
            message="query_text는 비어 있을 수 없습니다.",
            stage="request",
        )

    return {
        "contract_version": version.strip(),
        "request_id": request_id.strip(),
        "query_text": query_text.strip(),
    }


def validate_response(payload: Any) -> SearchResponse:
    if not isinstance(payload, dict):
        raise _contract_error("응답은 JSON 객체여야 합니다.")

    status = payload.get("status")
    if status not in {"success", "partial", "failed"}:
        raise _contract_error("status는 success, partial, failed 중 하나여야 합니다.")

    results = payload.get("results")
    if not isinstance(results, list):
        raise _contract_error("results는 배열이어야 합니다.")

    if status == "success" and len(results) != 5:
        raise _contract_error("성공 응답은 판례 5건을 반환해야 합니다.")
    if status == "failed" and not payload.get("error"):
        raise _contract_error("실패 응답에는 error가 필요합니다.")

    candidate_count = payload.get("candidate_count")
    if status == "success" and candidate_count != 200:
        raise _contract_error("성공 응답의 후보 수는 200건이어야 합니다.")

    ranks = [item.get("rank") for item in results if isinstance(item, dict)]
    if len(ranks) != len(results) or ranks != list(range(1, len(results) + 1)):
        raise _contract_error("결과 rank는 1부터 연속이어야 합니다.")

    record_ids = [str(item.get("record_id", "")).strip() for item in results]
    if any(not record_id for record_id in record_ids) or len(record_ids) != len(
        set(record_ids)
    ):
        raise _contract_error("결과의 record_id는 비어 있지 않고 서로 달라야 합니다.")

    for item in results:
        for score_name in ("retrieval_score", "rerank_score"):
            score = item.get(score_name)
            if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
                raise _contract_error(f"{score_name}는 유한한 숫자여야 합니다.")

    latency = payload.get("latency_ms")
    if not isinstance(latency, dict) or not _LATENCY_KEYS.issubset(latency):
        raise _contract_error("latency_ms에 모든 검색 단계 시간이 필요합니다.")
    if any(
        not isinstance(latency[key], (int, float))
        or not math.isfinite(float(latency[key]))
        or latency[key] < 0
        for key in _LATENCY_KEYS
    ):
        raise _contract_error("검색 단계 시간은 0 이상의 유한한 숫자여야 합니다.")

    return payload
