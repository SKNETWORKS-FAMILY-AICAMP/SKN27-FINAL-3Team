"""일반 판례 B1 목록 수집, B2 목록 중복 제거 및 시드 대조, B3 상세 원문 수집 모듈."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..seed.case_number import normalize_case_number
from ..seed.law_api import (
    LIST_URL,
    LawGoKrClient,
    _request_xml,
    parse_list_records,
)
from .queries import SearchQuery, get_all_queries


@dataclass
class CandidateListRecord:
    """B1 단계에서 수집된 후보 목록 레코드 및 수집 출처(provenance)."""

    case_id: str
    case_number: str
    normalized_case_number: str
    case_name: str
    court_name: str
    decision_date: str
    collection_provenance: list[dict[str, Any]]


def search_query_list(
    client: LawGoKrClient,
    query: SearchQuery,
    display_count: int = 20,
    page: int = 1,
) -> list[dict[str, str]]:
    """질의어 1건으로 국가법령정보센터 목록 API를 호출합니다."""

    xml_text = _request_xml(
        client.session,
        LIST_URL,
        {
            "OC": client._oc,
            "target": "prec",
            "type": "XML",
            "query": query.query_text,
            "display": display_count,
            "page": page,
            "sort": "ddes",
        },
        client.timeout,
    )
    time.sleep(client.sleep_seconds)
    return parse_list_records(xml_text)


def collect_b1_candidate_lists(
    client: LawGoKrClient,
    queries: list[SearchQuery] | None = None,
    display_per_query: int = 100,
    max_pages: int = 0,
) -> list[CandidateListRecord]:
    """B1 단계: 모든 질의어로 목록을 수집하고 질의 정보(provenance)를 누적합니다.

    max_pages <= 0 인 경우 API 결과가 더 이상 없을 때까지 무제한 전수 수집합니다.
    """
    target_queries = queries or get_all_queries()
    aggregated: dict[str, CandidateListRecord] = {}

    for query in target_queries:
        page = 1
        while True:
            if max_pages > 0 and page > max_pages:
                break

            records = search_query_list(
                client=client,
                query=query,
                display_count=display_per_query,
                page=page,
            )
            if not records:
                break

            for rank_offset, rec in enumerate(records, 1):
                case_id = rec.get("판례일련번호", "")
                raw_case_num = rec.get("사건번호", "")
                if not case_id or not raw_case_num:
                    continue

                rank = (page - 1) * display_per_query + rank_offset
                norm_case_num = normalize_case_number(raw_case_num)
                prov_entry = {
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "category": query.category,
                    "result_rank": rank,
                }

                if case_id in aggregated:
                    aggregated[case_id].collection_provenance.append(prov_entry)
                else:
                    aggregated[case_id] = CandidateListRecord(
                        case_id=case_id,
                        case_number=raw_case_num,
                        normalized_case_number=norm_case_num,
                        case_name=rec.get("사건명", ""),
                        court_name=rec.get("법원명", ""),
                        decision_date=rec.get("선고일자", ""),
                        collection_provenance=[prov_entry],
                    )

            page += 1

    return list(aggregated.values())


def filter_b2_with_seed_registry(
    candidates: list[CandidateListRecord],
    seed_case_numbers: set[str],
) -> tuple[list[CandidateListRecord], list[CandidateListRecord]]:
    """B2 단계: 시드 레지스트리 사건번호와 사전 대조하여 시드 중복건을 스킵합니다.

    반환: (상세 수집 대상 후보 리스트, 시드 중복 스킵 리스트)
    """
    to_fetch: list[CandidateListRecord] = []
    skipped_seeds: list[CandidateListRecord] = []

    for item in candidates:
        if item.normalized_case_number in seed_case_numbers:
            skipped_seeds.append(item)
        else:
            to_fetch.append(item)

    return to_fetch, skipped_seeds


def fetch_b3_details(
    client: LawGoKrClient,
    candidates: list[CandidateListRecord],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """B3 단계: 중복 필터링된 일반 후보 판례들의 상세 원문 XML을 수집합니다."""

    collected_details: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    total = len(candidates)

    for index, item in enumerate(candidates, 1):
        if index % 50 == 0 or index == total:
            print(f"API 상세 수집 진행: {index}/{total} 완료...", flush=True)

        try:
            detail = client.fetch_detail(item.case_id)
            detail.update(
                {
                    "_case_id": item.case_id,
                    "_requested_case_number": item.case_number,
                    "_normalized_case_number": item.normalized_case_number,
                    "source_type": "precedent",
                    "source_provider": "국가법령정보센터 Open API",
                    "collection_provenance": item.collection_provenance,
                    "inclusion_route": "general_query_collection",
                    "force_ready": False,
                    "internal_grade": "GENERAL_UNCLASSIFIED",
                }
            )
            collected_details.append(detail)
        except Exception as e:  # noqa: BLE001
            errors.append(
                {
                    "case_id": item.case_id,
                    "case_number": item.case_number,
                    "error": str(e),
                }
            )

    return collected_details, errors
