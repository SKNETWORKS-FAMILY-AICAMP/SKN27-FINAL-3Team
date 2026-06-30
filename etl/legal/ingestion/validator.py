"""법령 데이터의 컬럼 무결성을 검증하고(Quality Gate) 조항 간의 관계(Relations)를 생성하는 통합 검증 모듈입니다."""

from __future__ import annotations

from datetime import datetime, timezone


# ==========================================
# 1. 조항 연관 관계 빌더 영역 (Relation Builder)
# ==========================================

def build_relations(chunks: list[dict]) -> list[dict]:
    """버전 정보와 개별 조문 청크 간의 부모-자식 연결 관계(HAS_ARTICLE)를 생성합니다."""
    relations = []
    by_version: dict[str, list[dict]] = {}
    for chunk in chunks:
        by_version.setdefault(chunk["source_version_id"], []).append(chunk)

    for version_id, version_chunks in by_version.items():
        for chunk in version_chunks:
            if chunk.get("chunk_type") == "article":
                relations.append(
                    {
                        "relation_id": f"rel:{version_id}:HAS_ARTICLE:{chunk['chunk_id']}",
                        "from_chunk_id": version_id,
                        "to_chunk_id": chunk["chunk_id"],
                        "relation_type": "HAS_ARTICLE",
                        "confidence": 1.0,
                        "evidence_text": chunk.get("article_no"),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
    return relations


# ==========================================
# 2. 품질 검증 관문 영역 (Quality Gate)
# ==========================================

# 검색 및 적재에 누락되어서는 안 되는 필수 수집 메타데이터 필드들
REQUIRED_SEARCH_FIELDS = [
    "source_id",
    "source_name",
    "source_type",
    "source_version_id",
    "chunk_id",
    "chunk_type",
    "provision_text",
    "source_url",
    "enforce_date",
    "content_hash",
]


def validate_chunk(chunk: dict) -> dict:
    """개별 청크의 필수 입력값 누락 여부를 전수 검사하고 상태 코드를 부여합니다."""
    missing = [field for field in REQUIRED_SEARCH_FIELDS if not chunk.get(field)]
    result = dict(chunk)
    result["validation_errors"] = missing

    if not chunk.get("provision_text"):
        result["validation_status"] = "failed_parse"
        result["is_searchable"] = False
    elif not chunk.get("enforce_date"):
        result["validation_status"] = "missing_enforce_date"
        result["is_searchable"] = False
    elif not chunk.get("source_url"):
        result["validation_status"] = "missing_source_url"
        result["is_searchable"] = False
    elif missing:
        result["validation_status"] = "partial_text_only"
        result["is_searchable"] = False
    else:
        result["validation_status"] = "validated"
        result["is_searchable"] = True

    return result


def run_quality_gate(chunks: list[dict]) -> tuple[list[dict], dict]:
    """전체 청크의 무결성 검증을 일괄 수행하고 요약 검증 보고서 정보를 구성합니다."""
    checked = [validate_chunk(chunk) for chunk in chunks]
    searchable = [chunk for chunk in checked if chunk["is_searchable"]]
    report = {
        "total_chunks": len(checked),
        "searchable_chunks": len(searchable),
        "failed_chunks": len([row for row in checked if not row["is_searchable"]]),
        "status_counts": {},
    }
    for chunk in checked:
        status = chunk["validation_status"]
        report["status_counts"][status] = report["status_counts"].get(status, 0) + 1
    return checked, report
