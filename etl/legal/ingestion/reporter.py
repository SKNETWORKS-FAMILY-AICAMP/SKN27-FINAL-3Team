"""법령 수집 및 전처리 파이프라인 수행 후 결과물 파일(.jsonl) 생성 및 보고서(요약 통계, 커버리지)를 작성하는 통합 리포터 모듈입니다."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path


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
    embedding_inputs: list[dict],
    quality_report: dict,
    failed_items: list[dict],
    started_at: str,
) -> dict:
    """파이프라인 구동 시간, 성공 개수, 에러 항목을 통합 요약 보고서용 사전 구조로 구성합니다."""
    failed_chunks = quality_report.get("failed_chunks", 0)
    status = "success"
    if failed_items or failed_chunks:
        status = "partial" if chunks else "failed"

    return {
        "run_id": run_id,
        "mode": mode,
        "status": status,
        "total_sources": len(sources),
        "total_versions": len(versions),
        "total_raw_documents": len(raw_records),
        "total_chunks": len(chunks),
        "searchable_chunks": len(searchable_chunks),
        "failed_chunks": failed_chunks,
        "partial_chunks": quality_report.get("status_counts", {}).get("partial_text_only", 0),
        "relation_count": len(relations),
        "embedding_input_count": len(embedding_inputs),
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "limitations": [item["error"] for item in failed_items if item.get("error")],
    }


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
