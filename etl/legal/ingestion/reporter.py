"""법령 수집 및 전처리 파이프라인 수행 후 결과물 파일(.jsonl) 생성 및 보고서(요약 통계, 커버리지)를 작성하는 통합 리포터 모듈입니다."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path


RUN_SUMMARY_CONTRACT_VERSION = "legal_ingestion_run_summary.v2"


# ==========================================
# 1. 파일 쓰기 및 결과 보관 영역 (Artifact Writer)
# ==========================================

def write_jsonl(path: str | Path, rows: list[dict]) -> None:
    """리스트 객체를 개행 구분 형식의 JSONL 파일로 씁니다."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: str | Path, data: dict) -> None:
    """사전 객체를 들여쓰기가 포함된 JSON 파일로 씁니다."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def write_artifacts(result: dict, output_dir: str | Path) -> None:
    """파이프라인 실행 중 생성된 전체 산출물 데이터셋을 지정된 디렉토리 하위에 나누어 저장합니다."""
    base = Path(output_dir)
    write_jsonl(base / "normalized" / "legal_sources.jsonl", result["sources"])
    write_jsonl(base / "normalized" / "legal_source_versions.jsonl", result["versions"])
    write_jsonl(base / "normalized" / "raw_law_documents.jsonl", result["raw_records"])
    write_jsonl(base / "chunks" / "law_chunks.jsonl", result["chunks"])
    write_jsonl(base / "relations" / "law_relations.jsonl", result["relations"])
    write_jsonl(base / "relations" / "law_extra_relations.jsonl", result.get("extra_relations", []))
    write_jsonl(base / "embeddings" / "embedding_inputs.jsonl", result["embedding_inputs"])
    write_jsonl(base / "publish" / "searchable_law_chunks.jsonl", result["searchable_chunks"])
    write_json(base / "reports" / "quality_report.json", result["quality_report"])


# ==========================================
# 2. 실행 로그 및 요약 작성 영역 (Report Writer)
# ==========================================

def build_embedding_inputs(chunks: list[dict]) -> list[dict]:
    """임베딩 작업에 투입하기 위해 pending 상태를 포함한 임베딩 인풋 포맷을 조립합니다."""
    return [
        {
            "chunk_id": chunk["chunk_id"],
            "embedding_model": None,
            "embedding_version": None,
            "embedding_text": chunk["embedding_text"],
            "embedding_text_hash": chunk["embedding_text_hash"],
            "embedding_vector": None,
            "status": "pending",
        }
        for chunk in chunks
    ]


def build_run_summary(
    *,
    run_id: str,
    mode: str,
    sources: list[dict],
    versions: list[dict],
    raw_records: list[dict],
    chunks: list[dict],
    searchable_chunks: list[dict],
    relations: list[dict],
    extra_relations: list[dict] | None = None,
    embedding_inputs: list[dict],
    quality_report: dict,
    failed_items: list[dict],
    started_at: str,
    source_summaries: list[dict] | None = None,
    dataset_version: str | None = None,
) -> dict:
    """파이프라인 구동 시간, 성공 개수, 에러 항목을 통합 요약 보고서용 사전 구조로 구성합니다."""
    failed_chunks = quality_report.get("failed_chunks", 0)
    status = "success"
    if failed_items or failed_chunks:
        status = "partial" if chunks else "failed"

    finished_at = datetime.now(timezone.utc).isoformat()
    resolved_source_summaries = (
        source_summaries
        if source_summaries is not None
        else _source_summaries(
            sources=sources,
            versions=versions,
            raw_records=raw_records,
            chunks=chunks,
            searchable_chunks=searchable_chunks,
            failed_items=failed_items,
            finished_at=finished_at,
        )
    )
    resolved_dataset_version = dataset_version or sha256_version(
        [
            f"{row['source_id']}:{row['data_version']}"
            for row in resolved_source_summaries
        ]
    )
    if any(row.get("status") != "success" for row in resolved_source_summaries):
        status = "partial" if chunks else "failed"
    return {
        "contract_version": RUN_SUMMARY_CONTRACT_VERSION,
        "run_id": run_id,
        "mode": mode,
        "status": status,
        "dataset_version": resolved_dataset_version,
        "source_summaries": resolved_source_summaries,
        "total_sources": len(sources),
        "total_versions": len(versions),
        "total_raw_documents": len(raw_records),
        "total_chunks": len(chunks),
        "searchable_chunks": len(searchable_chunks),
        "failed_chunks": failed_chunks,
        "partial_chunks": quality_report.get("status_counts", {}).get("partial_text_only", 0),
        "relation_count": len(relations),
        "extra_relation_count": len(extra_relations or []),
        "embedding_input_count": len(embedding_inputs),
        "started_at": started_at,
        "finished_at": finished_at,
        "limitations": [
            _safe_failed_item_code(item)
            for item in failed_items
            if item.get("error")
        ],
    }


def _source_summaries(
    *,
    sources: list[dict],
    versions: list[dict],
    raw_records: list[dict],
    chunks: list[dict],
    searchable_chunks: list[dict],
    failed_items: list[dict],
    finished_at: str,
) -> list[dict]:
    rows = []
    for source in sorted(sources, key=lambda item: item["source_id"]):
        source_id = source["source_id"]
        source_versions = [
            row for row in versions if row.get("source_id") == source_id
        ]
        source_raw = [
            row for row in raw_records if row.get("source_id") == source_id
        ]
        source_chunks = [
            row for row in chunks if row.get("source_id") == source_id
        ]
        source_searchable = [
            row
            for row in searchable_chunks
            if row.get("source_id") == source_id
        ]
        errors = [
            _safe_failed_item_code(item)
            for item in failed_items
            if item.get("source_id") == source_id and item.get("error")
        ]
        effective_dates = sorted(
            str(row["enforce_date"])
            for row in source_versions
            if row.get("enforce_date")
        )
        collected_dates = sorted(
            str(row["fetched_at"]) for row in source_raw if row.get("fetched_at")
        )
        if not source_versions:
            status = "failed" if errors else "missing"
        elif errors or not source_raw or not source_chunks or not source_searchable:
            status = "partial"
        else:
            status = "success"

        rows.append(
            {
                "source_id": source_id,
                "source_name": source.get("source_name"),
                "source_type": source.get("source_type"),
                "provider": source.get("provider"),
                "provider_source_id": source.get("provider_source_id"),
                "status": status,
                "version_count": len(source_versions),
                "raw_document_count": len(source_raw),
                "chunk_count": len(source_chunks),
                "searchable_chunk_count": len(source_searchable),
                "first_effective_at": effective_dates[0] if effective_dates else None,
                "last_effective_at": effective_dates[-1] if effective_dates else None,
                "collected_at": collected_dates[-1] if collected_dates else None,
                "last_verified_at": finished_at if status == "success" else None,
                "data_version": sha256_version(
                    [
                        str(row.get("source_version_id") or "")
                        for row in source_versions
                    ]
                    + [
                        f"{row.get('chunk_id', '')}:{row.get('content_hash', '')}"
                        for row in source_chunks
                    ]
                ),
                "errors": errors,
            }
        )
    return rows


def sha256_version(rows: list[str]) -> str:
    payload = "\n".join(sorted(value for value in rows if value))
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _safe_failed_item_code(item: dict) -> str:
    error = str(item.get("error") or "").strip()
    if re.fullmatch(r"[a-z][a-z0-9_]{2,63}", error):
        return error

    stage = str(item.get("stage") or "pipeline").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", stage):
        stage = "pipeline"
    normalized_error = error.lower()
    if "timeout" in normalized_error or "timed out" in normalized_error:
        return f"{stage}_timeout"
    if any(
        token in normalized_error
        for token in ("unauthorized", "forbidden", "authentication", "401", "403")
    ):
        return f"{stage}_auth_failed"
    return f"{stage}_failed"


def write_reports(output_dir: str | Path, run_summary: dict, ingestion_log: list[dict]) -> None:
    """수행 요약 리포트와 예외 발생 기록 로그를 보고서 폴더 아래에 씁니다."""
    base = Path(output_dir)
    write_json(base / "reports" / "run_summary.json", run_summary)
    write_jsonl(base / "reports" / "ingestion_log.jsonl", ingestion_log)


# ==========================================
# 3. 수집 완성도 분석 영역 (Coverage Report)
# ==========================================

def build_coverage_report(
    *,
    sources: list[dict],
    versions: list[dict],
    base_date: date,
    history_years: int,
) -> dict:
    """매니페스트 법률 목록 대비 실제 기간 내 몇 개의 연혁 조항이 확보되었는지 진척률 보고서를 작성합니다."""
    window_start = date(base_date.year - history_years, base_date.month, base_date.day)
    window_end = base_date
    versions_by_source: dict[str, list[dict]] = {}
    for version in versions:
        versions_by_source.setdefault(version["source_id"], []).append(version)

    rows = []
    for source in sources:
        source_versions = versions_by_source.get(source["source_id"], [])
        enforce_dates = sorted(
            {
                value
                for value in (version.get("enforce_date") for version in source_versions)
                if value
            }
        )
        rows.append(
            {
                "source_id": source["source_id"],
                "source_name": source["source_name"],
                "source_type": source["source_type"],
                "collected_version_count": len(source_versions),
                "first_enforce_date": enforce_dates[0] if enforce_dates else None,
                "last_enforce_date": enforce_dates[-1] if enforce_dates else None,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "coverage_status": _coverage_status(source_versions),
                "notes": _coverage_notes(source_versions),
            }
        )

    return {
        "status": "complete" if all(row["collected_version_count"] for row in rows) else "partial",
        "history_years": history_years,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "total_sources": len(sources),
        "sources_with_versions": len([row for row in rows if row["collected_version_count"]]),
        "total_versions": len(versions),
        "sources": rows,
        "limitations": [
            "coverage is based on law.go.kr search/list responses and does not prove absence of undisclosed historical versions",
            "for legal audit, compare collected versions with a dedicated official history endpoint or manual law history page",
        ],
    }


def write_coverage_report(output_dir: str | Path, report: dict) -> None:
    """수집 진척률(Coverage) 결과 보고서를 디렉토리 아래에 씁니다."""
    write_json(Path(output_dir) / "reports" / "coverage_report.json", report)


def _coverage_status(versions: list[dict]) -> str:
    if not versions:
        return "missing"
    return "collected"


def _coverage_notes(versions: list[dict]) -> list[str]:
    notes = []
    if len(versions) == 1:
        notes.append("single version returned by law.go.kr for this source/window")
    return notes
