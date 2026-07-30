"""국가법령정보센터 Open API 사건번호 정확 일치 수집기."""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .case_number import (
    case_number_search_variants,
    extract_case_numbers,
    normalize_case_number,
)


LIST_URL = "https://www.law.go.kr/DRF/lawSearch.do"
DETAIL_URL = "https://www.law.go.kr/DRF/lawService.do"


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _flat_dict(node: ET.Element) -> dict[str, str]:
    record: dict[str, str] = {}
    for child in node.iter():
        if child is node:
            continue
        key = _local_name(child.tag)
        value = _clean("".join(child.itertext()))
        if key and value and key not in record:
            record[key] = value
    return record


def _direct_dict(node: ET.Element) -> dict[str, str]:
    """목록의 한 행처럼 바로 아래 자식이 필드인 XML 노드를 변환합니다."""
    record: dict[str, str] = {}
    for child in list(node):
        key = _local_name(child.tag)
        value = _clean("".join(child.itertext()))
        if key and value:
            record[key] = value
    for key, value in node.attrib.items():
        cleaned = _clean(value)
        if cleaned:
            record[f"@{key}"] = cleaned
    return record


def _parse_xml(text: str) -> ET.Element:
    return ET.fromstring(text.lstrip("\ufeff").strip())


def parse_list_records(xml_text: str) -> list[dict[str, str]]:
    root = _parse_xml(xml_text)
    records: list[dict[str, str]] = []
    candidate_keys = {"판례일련번호", "사건명", "사건번호", "선고일자", "법원명"}

    # 공식 판례 목록 응답은 각 검색 결과를 <prec> 노드로 제공합니다.
    for node in root.iter():
        if _local_name(node.tag).lower() == "prec":
            record = _direct_dict(node)
            if record:
                records.append(record)

    # 응답 구조가 달라졌을 때만 루트 바로 아래 노드를 보조적으로 확인합니다.
    if not records:
        for node in list(root):
            record = _direct_dict(node)
            if candidate_keys.intersection(record):
                records.append(record)

    unique: dict[str, dict[str, str]] = {}
    for record in records:
        case_id = record.get("판례일련번호", "")
        if case_id:
            unique.setdefault(case_id, record)
    return list(unique.values())


def parse_detail_record(xml_text: str) -> dict[str, str]:
    return _flat_dict(_parse_xml(xml_text))


def build_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session = requests.Session()
    session.headers.update(
        {"User-Agent": "SKN27-precedent-seed-collector/1.0"}
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _request_xml(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    timeout: int,
) -> str:
    response = session.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.text


def _record_case_numbers(record: dict[str, Any]) -> set[str]:
    value = _clean(record.get("사건번호", ""))
    return {match.normalized for match in extract_case_numbers(value)}


def _exact_matches(
    records: list[dict[str, str]],
    requested_case_number: str,
) -> list[dict[str, str]]:
    target = normalize_case_number(requested_case_number)
    return [
        record for record in records if target in _record_case_numbers(record)
    ]


@dataclass
class CollectionOutcome:
    status: str
    requested_case_number: str
    detail: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] | None = None
    error: str | None = None


class LawGoKrClient:
    def __init__(
        self,
        oc: str,
        timeout: int = 30,
        sleep_seconds: float = 0.25,
    ) -> None:
        if not oc.strip():
            raise ValueError("LAW_GO_KR_OC가 비어 있습니다.")
        self._oc = oc.strip()
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds
        self.session = build_session()

    def search_exact(self, case_number: str) -> list[dict[str, str]]:
        """사건번호로 국가법령정보센터 판례 목록을 정확 매칭 검색합니다.

        1차로 사건번호 전용 변수(nb)로 검색하고, 결과가 없는 하급심/특수 사건의 경우
        2차로 일반 쿼리 변수(query) 및 공백 분리 패턴으로 보조 검색(fallback)을 수행합니다.
        """
        candidates: dict[str, dict[str, str]] = {}

        # 1차: nb (사건번호 전용) 검색
        for number_variant in case_number_search_variants(case_number):
            xml_text = _request_xml(
                self.session,
                LIST_URL,
                {
                    "OC": self._oc,
                    "target": "prec",
                    "type": "XML",
                    # 공식 판례 목록 API의 사건번호 전용 검색 변수입니다.
                    "nb": number_variant,
                    "display": 100,
                    "page": 1,
                    "sort": "ddes",
                },
                self.timeout,
            )
            for record in _exact_matches(
                parse_list_records(xml_text), case_number
            ):
                case_id = record.get("판례일련번호", "")
                if case_id:
                    candidates.setdefault(case_id, record)
            time.sleep(self.sleep_seconds)

        # 2차: 1차 검색 결과가 없는 하급심/특수 사건의 경우 query 파라미터를 활용한 보조 검색(fallback)
        if not candidates:
            query_variants = list(dict.fromkeys(case_number_search_variants(case_number)))
            # 사건구분 앞뒤 띄어쓰기 형태(예: 2019 나 2051234) 추가
            import re
            m = re.match(r"(?P<year>\d{2,4})(?P<kind>[가-힣]+)(?P<number>\d+)", normalize_case_number(case_number))
            if m:
                query_variants.append(f"{m.group('year')} {m.group('kind')} {m.group('number')}")
                query_variants.append(f"{m.group('kind')} {m.group('number')}")

            for q_variant in query_variants:
                xml_text = _request_xml(
                    self.session,
                    LIST_URL,
                    {
                        "OC": self._oc,
                        "target": "prec",
                        "type": "XML",
                        "query": q_variant,
                        "display": 100,
                        "page": 1,
                        "sort": "ddes",
                    },
                    self.timeout,
                )
                for record in _exact_matches(
                    parse_list_records(xml_text), case_number
                ):
                    case_id = record.get("판례일련번호", "")
                    if case_id:
                        candidates.setdefault(case_id, record)
                time.sleep(self.sleep_seconds)

        return list(candidates.values())

    def fetch_detail(self, case_id: str) -> dict[str, str]:
        xml_text = _request_xml(
            self.session,
            DETAIL_URL,
            {
                "OC": self._oc,
                "target": "prec",
                "ID": case_id,
                "type": "XML",
            },
            self.timeout,
        )
        time.sleep(self.sleep_seconds)
        return parse_detail_record(xml_text)

    def collect_target(self, target: dict[str, Any]) -> CollectionOutcome:
        requested = target["case_number"]
        try:
            candidates = self.search_exact(requested)
            if not candidates:
                return CollectionOutcome(
                    status="not_found",
                    requested_case_number=requested,
                    candidates=[],
                )
            if len(candidates) > 1:
                return CollectionOutcome(
                    status="ambiguous",
                    requested_case_number=requested,
                    candidates=candidates,
                )

            candidate = candidates[0]
            case_id = candidate["판례일련번호"]
            detail = self.fetch_detail(case_id)
            matched_numbers = sorted(_record_case_numbers(detail or candidate))
            detail.update(
                {
                    "_case_id": case_id,
                    "_requested_case_number": requested,
                    "_matched_case_numbers": matched_numbers,
                    "source_type": "precedent",
                    "source_provider": "국가법령정보센터 Open API",
                    "source_reference": (
                        f"{DETAIL_URL}?"
                        + urlencode(
                            {
                                "target": "prec",
                                "ID": case_id,
                                "type": "XML",
                            }
                        )
                    ),
                    "seed_source_pdfs": target.get("source_pdfs", []),
                    "seed_source_pages": target.get("source_pages", {}),
                    "inclusion_route": "official_fault_standard_citation",
                    "force_ready": True,
                }
            )
            return CollectionOutcome(
                status="collected",
                requested_case_number=requested,
                detail=detail,
                candidates=candidates,
            )
        except Exception as error:  # noqa: BLE001
            return CollectionOutcome(
                status="error",
                requested_case_number=requested,
                error=repr(error),
            )
