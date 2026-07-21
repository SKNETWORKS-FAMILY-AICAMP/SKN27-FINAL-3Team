"""Qwen 4B 세 코퍼스 운영 재색인의 변경 불가 계약을 정의한다.

이 모듈은 실행하지 않고, 로컬 입력 감사기와 RunPod 실행기가 같은 모델·입력·질의
지시문을 공유하도록 상수와 자료형만 제공한다.
"""

from __future__ import annotations

from dataclasses import dataclass  # 코퍼스별 입력 계약을 불변 자료형으로 묶는다.
from pathlib import Path  # Windows와 Linux에서 같은 방식으로 경로를 조합한다.


# 이 파일 위치에서 프로젝트 루트와 fault_cases 루트를 계산해 실행 위치 의존성을 없앤다.
PROJECT_ROOT = Path(__file__).resolve().parents[5]
FAULT_CASES_ROOT = PROJECT_ROOT / "etl" / "fault_cases"

# 운영 모델은 실험에서 승인된 이름·리비전·기본 차원으로 고정한다.
MODEL_NAME = "Qwen/Qwen3-Embedding-4B"
MODEL_REVISION = "5cf2132abc99cad020ac570b19d031efec650f2b"
MODEL_DIMENSION = 2560
NORMALIZATION = "l2_normalized"

# 현재 운영 재색인 입력의 예상 건수다. 변경하려면 새 입력 버전과 검수 보고서가 필요하다.
EXPECTED_COUNTS = {
    "fault_standard": {"source_documents": 277, "embedding_units": 277},
    "review_case": {"source_documents": 226, "embedding_units": 904},
    "precedent": {"source_documents": 987, "embedding_units": 8334},
}

# Qwen 공식 질의 형식에 맞춰 코퍼스별 검색 목적을 명시한다.
QUERY_INSTRUCTIONS = {
    "fault_standard": (
        "Instruct: Given a Korean traffic-accident description, retrieve the applicable "
        "Korean fault-ratio standard rule\nQuery: "
    ),
    "review_case": (
        "Instruct: Given a Korean traffic-accident description, retrieve the most relevant "
        "fault-ratio dispute review cases\nQuery: "
    ),
    "precedent": (
        "Instruct: Given a Korean traffic-accident description, retrieve the most relevant "
        "Korean traffic-accident fault-liability precedents\nQuery: "
    ),
}


@dataclass(frozen=True)
class CorpusSource:
    """한 코퍼스의 원본 문서·검색 단위·정답지 경로 계약이다.

    매개변수:
        key: 결과 디렉터리와 manifest에 기록할 영문 코퍼스 키다.
        database: 로컬 적재 검증에 사용할 PostgreSQL 데이터베이스 이름이다.
        target_type: 운영 벡터가 문서인지 청크인지를 나타낸다.
        source_document_paths: 상위 원본 문서 또는 Rule 파일 경로 묶음이다.
        embedding_unit_path: 실제 임베딩 검색 단위가 저장된 JSONL 경로다.
        qrels_path: 공통 50문항의 로컬 평가 정답지 경로다.
        qrel_target_field: 정답지가 가리키는 문서·사례 식별자 필드다.
    """

    key: str
    database: str
    target_type: str
    source_document_paths: tuple[Path, ...]
    embedding_unit_path: Path | None
    qrels_path: Path
    qrel_target_field: str


# 인정기준은 네 Rulebook의 Rule 자체가 검색 단위이므로 별도 청크 파일이 없다.
FAULT_STANDARD_RULE_PATHS = tuple(
    FAULT_CASES_ROOT
    / "artifacts"
    / "fault_standard_output"
    / "preprocessed"
    / rulebook
    / "99_tables_for_db"
    / "rules.jsonl"
    for rulebook in (
        "2023_official_auto_accident_rulebook",
        "2020_nontypical_accident_rulebook",
        "2021_pm_vs_auto_nontypical_rulebook",
        "2025_two_lane_roundabout_rulebook",
    )
)

# 세 코퍼스의 현재 승인 입력과 qrels를 한 곳에서 고정한다.
CORPUS_SOURCES = (
    CorpusSource(
        key="fault_standard",
        database="fault_standard_db",
        target_type="document",
        source_document_paths=FAULT_STANDARD_RULE_PATHS,
        embedding_unit_path=None,
        qrels_path=FAULT_CASES_ROOT
        / "evaluation"
        / "fault_standard"
        / "embedding_ab"
        / "v1"
        / "ground_truth"
        / "fault_standard_qrels_v1.2.jsonl",
        qrel_target_field="rule_id",
    ),
    CorpusSource(
        key="review_case",
        database="review_case_db",
        target_type="chunk",
        source_document_paths=(
            FAULT_CASES_ROOT / "artifacts" / "review_case_output" / "preprocessed" / "review_case_documents.jsonl",
        ),
        embedding_unit_path=(
            FAULT_CASES_ROOT / "artifacts" / "review_case_output" / "preprocessed" / "review_case_chunks.jsonl"
        ),
        qrels_path=FAULT_CASES_ROOT
        / "evaluation"
        / "review_case"
        / "embedding_ab"
        / "v1"
        / "ground_truth"
        / "review_case_qrels_v1.jsonl",
        qrel_target_field="review_case_id",
    ),
    CorpusSource(
        key="precedent",
        database="precedent_db",
        target_type="chunk",
        source_document_paths=(
            FAULT_CASES_ROOT
            / "artifacts"
            / "traffic_precedents_output"
            / "traffic_prec_fault_ratio_rag_verified"
            / "01_fault_ratio_rag_ready_cases.jsonl",
        ),
        embedding_unit_path=(
            FAULT_CASES_ROOT
            / "artifacts"
            / "traffic_precedents_output"
            / "precedent_chunking_v2"
            / "fault_ratio_precedent_chunks_v2.jsonl"
        ),
        qrels_path=FAULT_CASES_ROOT
        / "evaluation"
        / "precedent"
        / "embedding_ab"
        / "v1"
        / "ground_truth"
        / "precedent_qrels_v1.jsonl",
        qrel_target_field="case_id",
    ),
)

# 공통 50문항과 인정기준 Complete30의 승인 질문 파일을 분리해 고정한다.
COMMON_QUERY_PATH = (
    FAULT_CASES_ROOT / "evaluation" / "common" / "embedding_ab" / "v1" / "common_fault_queries_v1.jsonl"
)
COMPLETE30_QUERY_PATH = (
    FAULT_CASES_ROOT
    / "evaluation"
    / "fault_standard"
    / "complete30_v9"
    / "v1"
    / "complete30_consumer_questions_v1.jsonl"
)
COMPLETE30_ANSWER_PATH = (
    FAULT_CASES_ROOT
    / "evaluation"
    / "fault_standard"
    / "complete30_v9"
    / "v1"
    / "complete30_answer_key_with_explanations_v1.jsonl"
)

# 단계 6의 로컬 감사·ZIP 산출물 루트를 프로젝트 artifacts 아래로 제한한다.
STAGE6_ARTIFACT_ROOT = FAULT_CASES_ROOT / "artifacts" / "qwen4_operational" / "stage6_reindex"

