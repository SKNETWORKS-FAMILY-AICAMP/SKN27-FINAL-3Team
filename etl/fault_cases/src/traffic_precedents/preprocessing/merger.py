"""동일 판례를 검증 가능한 근거로만 병합하고 전처리 필드를 생성합니다."""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Any

from .cleaner import clean_text, split_sections


MERGER_VERSION = "safe_duplicate_merge_v2.0.0"


def _normalized_text(text: Any) -> str:
    return re.sub(r"\s+", "", clean_text(text, preserve_newlines=False))


def text_similarity(text1: str, text2: str) -> float:
    """전체 정규화 원문으로 동일 판례 유사도를 계산합니다."""

    normalized1 = _normalized_text(text1)
    normalized2 = _normalized_text(text2)
    if not normalized1 or not normalized2:
        return 0.0
    if hashlib.sha256(normalized1.encode("utf-8")).digest() == hashlib.sha256(
        normalized2.encode("utf-8")
    ).digest():
        return 1.0
    return SequenceMatcher(
        None,
        normalized1,
        normalized2,
        autojunk=False,
    ).ratio()


def _record_id(record: dict[str, Any]) -> str:
    return str(
        record.get("판례정보일련번호")
        or record.get("판례일련번호")
        or record.get("_case_id")
        or ""
    ).strip()


def _case_number(record: dict[str, Any]) -> str:
    matched = record.get("_matched_case_numbers") or []
    raw = (
        record.get("_normalized_case_number")
        or (matched[0] if matched else "")
        or record.get("사건번호")
        or record.get("_requested_case_number")
        or ""
    )
    return re.sub(r"[\s\-]", "", str(raw))


def _identity_key(
    record: dict[str, Any],
) -> tuple[str, str, str, str]:
    case_number = _case_number(record)
    court = clean_text(record.get("법원명", ""))
    decision_date = re.sub(r"\D", "", str(record.get("선고일자") or ""))
    if case_number and court and decision_date:
        return ("VERIFIED_META", case_number, court, decision_date)
    # 불완전 메타데이터끼리 서로 병합되지 않도록 레코드별 고유 그룹을 사용합니다.
    return ("INCOMPLETE_META", _record_id(record), "", "")


def _source_text(record: dict[str, Any]) -> str:
    return str(
        record.get("판례내용")
        or record.get("판결요지")
        or record.get("판시사항")
        or ""
    )


def _deduplicate_provenance(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = repr(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def preprocess_record(record: dict[str, Any]) -> dict[str, Any]:
    """원본 필드를 보존한 새 레코드에 C단계 결과 필드를 추가합니다."""

    item = dict(record)
    parts = split_sections(item)
    item.update(
        {
            "holding_text": parts.holding_text,
            "summary_text": parts.summary_text,
            "body_preamble_text": parts.body_preamble_text,
            "order_text": parts.order_text,
            "reason_text": parts.reason_text,
            "unlabeled_body_text": parts.unlabeled_body_text,
            "clean_body_text": parts.clean_body_text,
            "body_section_offsets": parts.body_section_offsets,
            "full_text": parts.full_text,
            "full_text_section_offsets": parts.full_text_section_offsets,
            "preprocessor_version": "safe_preprocessing_v2.0.0",
        }
    )
    return item


def merge_duplicate_precedents(
    records: list[dict[str, Any]],
    similarity_threshold: float = 0.90,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """메타데이터가 일치하고 전체 원문 유사도가 통과한 판례만 병합합니다."""

    if not 0.0 <= similarity_threshold <= 1.0:
        raise ValueError("similarity_threshold는 0과 1 사이여야 합니다.")

    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for raw_record in records:
        item = preprocess_record(raw_record)
        groups.setdefault(_identity_key(item), []).append(item)

    representatives: list[dict[str, Any]] = []
    merged_records: list[dict[str, Any]] = []

    for identity_key, members in groups.items():
        sorted_members = sorted(
            members,
            key=lambda item: (
                1
                if item.get("internal_grade") == "SEED_READY"
                or item.get("force_ready") is True
                else 0,
                len(_source_text(item)),
                _record_id(item),
            ),
            reverse=True,
        )
        clusters: list[dict[str, Any]] = []

        for item in sorted_members:
            matched_cluster: dict[str, Any] | None = None
            matched_similarity = 0.0
            if identity_key[0] == "VERIFIED_META":
                for cluster in clusters:
                    similarity = text_similarity(
                        _source_text(cluster["representative"]),
                        _source_text(item),
                    )
                    if (
                        similarity >= similarity_threshold
                        and similarity > matched_similarity
                    ):
                        matched_cluster = cluster
                        matched_similarity = similarity

            if matched_cluster is None:
                clusters.append(
                    {
                        "representative": item,
                        "duplicates": [],
                        "provenance": list(
                            item.get("collection_provenance", [])
                        ),
                    }
                )
                continue

            representative = matched_cluster["representative"]
            duplicate = dict(item)
            duplicate.update(
                {
                    "record_status": "DUPLICATE_MERGED",
                    "merged_into": _record_id(representative),
                    "merge_similarity": round(matched_similarity, 6),
                    "merge_reason_codes": [
                        "CASE_NUMBER_COURT_DATE_MATCH",
                        "FULL_TEXT_SIMILARITY_PASSED",
                    ],
                    "merger_version": MERGER_VERSION,
                }
            )
            matched_cluster["duplicates"].append(duplicate)
            matched_cluster["provenance"].extend(
                duplicate.get("collection_provenance", [])
            )
            merged_records.append(duplicate)

        for cluster in clusters:
            representative = dict(cluster["representative"])
            duplicates = cluster["duplicates"]
            representative.update(
                {
                    "record_status": "REPRESENTATIVE",
                    "merged_record_ids": [
                        _record_id(duplicate) for duplicate in duplicates
                    ],
                    "collection_provenance": _deduplicate_provenance(
                        cluster["provenance"]
                    ),
                    "merger_version": MERGER_VERSION,
                }
            )
            representatives.append(representative)

    return representatives, merged_records
