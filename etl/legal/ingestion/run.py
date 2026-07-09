"""법률 데이터 수집, 전처리, 청킹 및 검증 파이프라인의 통합 CLI 실행기입니다."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

# 통합된 4대 핵심 도메인 모듈로부터 함수 참조
from .collector import (
    load_manifest,
    validate_manifest,
    collect_sources,
    normalize_versions,
    save_raw_documents,
    create_law_api_client,
)
from .parser import (
    preprocess_raw_documents,
    parse_all,
    build_chunks,
    enrich_metadata,
)
from .validator import (
    build_relations,
    run_quality_gate,
)
from etl.legal.extract_extra_relations import build_extra_relations
from .reporter import (
    write_artifacts,
    write_coverage_report,
    write_reports,
    write_json,
    build_embedding_inputs,
    build_run_summary,
    build_coverage_report,
)


# ==========================================
# 1. 파이프라인 구성 및 설정 검증 (Pipeline Config)
# ==========================================

ALLOWED_MODES = {"dry_run", "artifact", "publish"}


@dataclass(frozen=True)
class PipelineConfig:
    """파이프라인 실행 시 명령행 인자 검증 및 환경 설정을 래핑하는 설정 데이터 클래스입니다."""
    manifest: Path
    base_date: date
    history_years: int
    mode: str
    output_dir: Path
    source_id: str | None = None
    step: str | None = None
    client: str = "auto"

    def validate(self) -> None:
        if self.mode not in ALLOWED_MODES:
            raise ValueError(f"지원하지 않는 실행 모드입니다: {self.mode}")
        if self.mode == "publish":
            raise ValueError("publish 모드는 활성화되지 않았습니다. artifact 모드를 권장합니다.")
        if self.history_years < 0:
            raise ValueError("이력 수집 연도(history_years)는 0 이상이어야 합니다.")
        if self.client not in {"auto", "offline", "law_go_kr"}:
            raise ValueError(f"지원하지 않는 API 클라이언트 종류입니다: {self.client}")


# ==========================================
# 2. 파이프라인 실행 제어 (Orchestration Run)
# ==========================================

def run_pipeline(config: PipelineConfig) -> dict:
    """수집기, 파서, 검증기, 리포터를 순차 가동하여 법률 데이터를 정제하고 임베딩 인풋을 추출합니다."""
    started_at = datetime.now(timezone.utc).isoformat()
    run_id = f"legal_ingestion:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    # 1. 수집 법령 목록 로드 및 유효성 판단
    sources = validate_manifest(load_manifest(config.manifest))
    if config.source_id:
        sources = [source for source in sources if source["source_id"] == config.source_id]

    config.output_dir.mkdir(parents=True, exist_ok=True)

    # 드라이런(Dry Run) 모드일 경우 통계 리포트만 기록 후 즉시 종료
    if config.mode == "dry_run":
        report = {
            "run_id": run_id,
            "mode": config.mode,
            "source_count": len(sources),
            "sources": sources,
            "started_at": started_at,
        }
        write_json(config.output_dir / "reports" / "dry_run_report.json", report)
        return report

    # 2. 법제처 API를 통한 조문 및 버전 연혁 다운로드
    collected = collect_sources(
        sources,
        config.base_date.isoformat(),
        config.history_years,
        client=create_law_api_client(config.client),
    )
    
    # 3. 이력 수집 범위 내(예: 최근 3년) 연혁만 걸러내어 버전 정보 정규화
    versions = normalize_versions(
        collected["versions"], config.base_date, config.history_years
    )
    
    # 4. 수집 진척 수준 요약 보고서 구성
    coverage_report = build_coverage_report(
        sources=sources,
        versions=versions,
        base_date=config.base_date,
        history_years=config.history_years,
    )
    
    # 5. 수집된 조문 정보의 원본 파일(.xml) 보존 처리
    included_version_ids = {version["source_version_id"] for version in versions}
    raw_documents = [
        raw
        for raw in collected["raw_documents"]
        if raw["source_version_id"] in included_version_ids
    ]
    raw_records = save_raw_documents(raw_documents, config.output_dir)
    
    # 6. 본문 텍스트 내 태그 및 연속 개행 정제
    preprocessed = preprocess_raw_documents(raw_records)
    
    # 7. XML 분석을 통해 조문 및 부칙/별표 구조 분할 (긴 본문 1800자 분할 및 오버랩 생성)
    structures = parse_all(preprocessed)
    
    # 8. 상위 법률명 및 조문번호를 결합하여 최종 검색용 청크 조립
    chunks = build_chunks(structures, sources, versions)
    
    # 9. 키워드 검출을 통한 추가 메타데이터 부여
    chunks = enrich_metadata(chunks)
    
    # 10. 상위 버전과 하위 조문 조각 간의 관계 그래프 선언
    relations = build_relations(chunks)
    extra_relations = build_extra_relations(chunks)
    
    # 11. 무결성 품질 검증(Quality Gate) 실행
    chunks, quality_report = run_quality_gate(chunks)
    
    # 유효성 검사를 통과한 검색용 최종 청크 리스트 분류
    searchable_chunks = [chunk for chunk in chunks if chunk["is_searchable"]]
    
    # 12. 임베딩 모델 인풋용 pending 데이터셋 구성
    embedding_inputs = build_embedding_inputs(chunks)

    # 13. output/ 내 각 경로에 결과물 JSONL 파일 일괄 생성
    result = {
        "sources": sources,
        "versions": versions,
        "raw_records": raw_records,
        "chunks": chunks,
        "relations": relations,
        "extra_relations": extra_relations,
        "embedding_inputs": embedding_inputs,
        "searchable_chunks": searchable_chunks,
        "quality_report": quality_report,
    }
    write_artifacts(result, config.output_dir)
    write_coverage_report(config.output_dir, coverage_report)

    # 14. 파이프라인 최종 가동 요약 정보 출력 및 기록
    run_summary = build_run_summary(
        run_id=run_id,
        mode=config.mode,
        sources=sources,
        versions=versions,
        raw_records=raw_records,
        chunks=chunks,
        searchable_chunks=searchable_chunks,
        relations=relations,
        extra_relations=extra_relations,
        embedding_inputs=embedding_inputs,
        quality_report=quality_report,
        failed_items=collected["failed_items"],
        started_at=started_at,
    )
    write_reports(config.output_dir, run_summary, collected["failed_items"])
    return run_summary


def main(argv: list[str] | None = None) -> int:
    """명령 인자를 파싱하여 파이프라인 구동을 시작합니다."""
    config = parse_args(argv)
    run_pipeline(config)
    return 0


def parse_args(argv: list[str] | None = None) -> PipelineConfig:
    """CLI 인자들을 해석하여 PipelineConfig 객체로 파싱합니다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="수집할 법률 목록 명세서 경로")
    parser.add_argument("--base-date", default=date.today().isoformat(), help="수집 기준 시작일")
    parser.add_argument("--history-years", type=int, default=3, help="연혁 수집 연도 범위")
    parser.add_argument("--mode", default="artifact", choices=["dry_run", "artifact", "publish"], help="실행 모드")
    parser.add_argument("--output-dir", required=True, help="결과물이 쓰일 경로")
    parser.add_argument("--source-id", help="특정 단일 법령만 선별 실행 시 사용")
    parser.add_argument("--step", help="개별 전처리 단계만 실행 시 사용")
    parser.add_argument("--client", default="auto", choices=["auto", "offline", "law_go_kr"], help="연동 API 클라이언트 모드")
    
    args = parser.parse_args(argv)
    config = PipelineConfig(
        manifest=Path(args.manifest),
        base_date=date.fromisoformat(args.base_date),
        history_years=args.history_years,
        mode=args.mode,
        output_dir=Path(args.output_dir),
        source_id=args.source_id,
        step=args.step,
        client=args.client,
    )
    config.validate()
    return config


if __name__ == "__main__":
    raise SystemExit(main())
