"""Qwen3-Embedding-4B 운영 인덱스의 공통 검색·평가 보조 기능.

실서비스 질의는 revision을 고정한 Qwen 4B 인코더를 통해 벡터화한다. 이관 직후
검증 단계에서는 이미 검증된 AB Parquet의 질의 벡터만 읽어 DB 적재 결과를 대조한다.
두 경로를 섞지 않아 평가용 사전 계산 벡터가 운영 질의 처리에 우연히 사용되지 않게 한다.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

import pyarrow.parquet as pq
import psycopg


# 이 파일 기준 `etl/fault_cases` 루트다. 모든 고정 입력은 이 경로 아래에 둔다.
FAULT_CASES_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = FAULT_CASES_ROOT.parents[1]
AB_REPEAT_ROOT = (
    FAULT_CASES_ROOT
    / "artifacts/embedding_ab_shared/track_a_6models_native_3repeats"
    / "run_native7_20260718_v1/repeat_01"
)
B4_QUERY_PATH = (
    FAULT_CASES_ROOT
    / "artifacts/embedding_ab_shared/track_c_precedent_search_enhancement"
    / "run_precedent_retrieval_v3/02_b4_all_top10_failures/b4_query_embeddings.parquet"
)


@dataclass(frozen=True)
class CorpusDatabase:
    """코퍼스마다 분리된 운영 DB와 검색 단위를 정의한다."""

    key: Literal["fault_standard", "precedent", "review_case"]
    database: str
    target_type: Literal["document", "chunk"]


CORPUS_DATABASES: dict[str, CorpusDatabase] = {
    "fault_standard": CorpusDatabase("fault_standard", "fault_standard_db", "document"),
    "precedent": CorpusDatabase("precedent", "precedent_db", "chunk"),
    "review_case": CorpusDatabase("review_case", "review_case_db", "chunk"),
}


def _read_password() -> str:
    """PostgreSQL 비밀번호를 환경변수에서만 읽고 로그나 결과에 남기지 않는다."""

    value = os.environ.get("POSTGRES_PASSWORD")
    if not value:
        raise RuntimeError("POSTGRES_PASSWORD 환경변수가 없어 운영 검색 DB에 연결할 수 없습니다.")
    return value


def _connect(corpus: str) -> psycopg.Connection[Any]:
    """해당 코퍼스 전용 DB에만 연결한다. 법률 DB는 이 목록에 존재하지 않는다."""

    spec = CORPUS_DATABASES[corpus]
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=_read_password(),
        dbname=spec.database,
        connect_timeout=15,
    )


def validate_vector(values: list[float]) -> None:
    """Qwen 4B의 고정 2,560차원·유한값·정규화 조건을 검사한다."""

    if len(values) != 2560:
        raise ValueError(f"Qwen 4B 질의 벡터 차원이 2560이 아닙니다: {len(values)}")
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("질의 벡터에 NaN 또는 Inf가 포함되어 있습니다.")
    norm = math.sqrt(sum(float(value) * float(value) for value in values))
    if not 0.99 <= norm <= 1.01:
        raise ValueError(f"질의 벡터가 L2 정규화되지 않았습니다: norm={norm:.6f}")


def vector_literal(values: list[float]) -> str:
    """검증된 float 벡터를 pgvector·halfvec 캐스팅용 문자열로 변환한다."""

    validate_vector(values)
    return "[" + ",".join(format(float(value), ".9g") for value in values) + "]"


def _parquet_vectors(path: Path) -> dict[str, list[float]]:
    """Parquet의 ID별 벡터를 읽고 중복 ID·차원 오류를 즉시 중단한다."""

    if not path.is_file():
        raise FileNotFoundError(f"승인된 질의 벡터 Parquet이 없습니다: {path}")
    rows = pq.read_table(path, columns=["id", "vector"]).to_pylist()
    output: dict[str, list[float]] = {}
    for row in rows:
        key = str(row["id"])
        if key in output:
            raise ValueError(f"질의 벡터 ID가 중복됐습니다: {key}")
        values = [float(value) for value in row["vector"]]
        validate_vector(values)
        output[key] = values
    return output


def precomputed_query_vectors(corpus: str, strategy: str = "baseline") -> dict[str, list[float]]:
    """운영 DB 이관 검증용 승인 질의 벡터를 반환한다.

    `baseline`은 AB repeat_01 Qwen 4B 질의 벡터다. 판례 `b4`만 B-1을 계승하고
    9개 사고 조건을 추가한 별도 Qwen 4B 질의 벡터를 사용한다.
    """

    if strategy == "baseline":
        path = AB_REPEAT_ROOT / "02_vectors/qwen3_4b_native_2560" / corpus / "query_embeddings.parquet"
    elif corpus == "precedent" and strategy == "b4":
        path = B4_QUERY_PATH
    else:
        raise ValueError(f"지원하지 않는 사전계산 질의 벡터 전략입니다: {corpus}/{strategy}")
    return _parquet_vectors(path)


def encode_live_query(query_text: str) -> list[float]:
    """운영 질의를 revision 고정 Qwen 4B로 임베딩한다.

    이 함수는 GPU 운영 환경에서 호출한다. 기존 AB 산출물은 revision이 고정되지
    않았으므로, 운영 환경에서는 `QWEN4_MODEL_REVISION`을 명시하지 않으면 실행을
    거부한다. 이는 서로 다른 가중치가 같은 운영 인덱스에 섞이는 것을 막는다.
    """

    if not query_text.strip():
        raise ValueError("검색할 질문이 비어 있습니다.")
    revision = os.environ.get("QWEN4_MODEL_REVISION")
    if not revision:
        raise RuntimeError("QWEN4_MODEL_REVISION이 없어 운영 질의 임베딩을 실행하지 않습니다.")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:  # pragma: no cover - GPU 운영 이미지에서 실행한다.
        raise RuntimeError("sentence-transformers가 설치된 GPU 운영 환경이 필요합니다.") from error
    # 모델·revision·device는 운영 환경에서 명시적으로 고정한다.
    model = SentenceTransformer(
        "Qwen/Qwen3-Embedding-4B",
        revision=revision,
        trust_remote_code=True,
        device=os.environ.get("QWEN4_DEVICE", "cuda"),
    )
    vector = model.encode([query_text], normalize_embeddings=True, show_progress_bar=False)[0]
    values = [float(value) for value in vector]
    validate_vector(values)
    return values


def search_by_vector(corpus: str, query_vector: list[float], top_k: int = 10, candidate_k: int = 200) -> list[dict[str, Any]]:
    """전용 `rag_qwen4` 스키마에서 cosine Top-K를 검색한다.

    청크 코퍼스는 후보 청크를 넉넉히 가져온 뒤 상위 문서(심의사례) 또는 판례
    단위로 중복 제거한다. 반환 cosine은 벡터 유사도이며 정답 확률은 아니다.
    """

    if corpus not in CORPUS_DATABASES:
        raise ValueError(f"지원하지 않는 코퍼스입니다: {corpus}")
    if top_k < 1 or candidate_k < top_k:
        raise ValueError("top_k와 candidate_k 범위가 올바르지 않습니다.")
    spec = CORPUS_DATABASES[corpus]
    literal = vector_literal(query_vector)
    # 인정기준은 277건뿐이므로 full vector exact 정렬을 사용해 Complete30의 기존
    # Qwen 기준선과 반올림 차이 없이 대조한다. 대형 청크 코퍼스만 halfvec HNSW를 쓴다.
    if corpus == "fault_standard":
        distance_expression = "e.embedding <=> %s::vector"
        score_expression = "1 - (e.embedding <=> %s::vector)"
    else:
        distance_expression = "e.embedding::halfvec(2560) <=> %s::halfvec(2560)"
        score_expression = "1 - (e.embedding::halfvec(2560) <=> %s::halfvec(2560))"
    sql = f"""
        SELECT
            e.target_id,
            e.document_id,
            e.chunk_id,
            d.source_reference,
            d.title,
            COALESCE(c.chunk_text, d.raw_text, d.embedding_input, '') AS evidence_text,
            COALESCE(c.metadata, d.metadata) AS metadata,
            {score_expression} AS cosine_similarity
        FROM rag_qwen4.embeddings AS e
        JOIN rag_qwen4.documents AS d ON d.document_id = e.document_id
        LEFT JOIN rag_qwen4.chunks AS c ON c.chunk_id = e.chunk_id
        WHERE e.target_type = %s
        ORDER BY {distance_expression}, e.target_id
        LIMIT %s
    """
    with _connect(corpus) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, (literal, spec.target_type, literal, candidate_k))
            columns = [column.name for column in cursor.description]
            rows = [dict(zip(columns, values, strict=True)) for values in cursor.fetchall()]

    unique: list[dict[str, Any]] = []
    seen_parent_ids: set[str] = set()
    for row in rows:
        # 판례/심의사례는 다수 청크가 하나의 원문을 공유하므로 원문 단위로 묶는다.
        parent_id = str(row["document_id"])
        if parent_id in seen_parent_ids:
            continue
        seen_parent_ids.add(parent_id)
        row["rank"] = len(unique) + 1
        row["cosine_similarity"] = float(row["cosine_similarity"])
        row["cosine_distance"] = 1.0 - row["cosine_similarity"]
        row["source_type"] = corpus
        unique.append(row)
        if len(unique) >= top_k:
            break
    return unique


def fetch_document_chunks(
    corpus: str,
    document_ids: Sequence[str],
) -> dict[str, list[dict[str, Any]]]:
    """리랭커 문맥용 청크를 한 번의 읽기 전용 쿼리로 조회한다."""

    if corpus != "review_case":
        raise ValueError(
            "전체 사례 문맥 조회는 review_case만 지원합니다."
        )
    unique_ids = list(dict.fromkeys(str(value) for value in document_ids))
    if not unique_ids:
        return {}

    sql = """
        SELECT
            c.document_id,
            c.chunk_id,
            c.chunk_type,
            c.chunk_text,
            c.metadata
        FROM rag_qwen4.chunks AS c
        WHERE c.document_id = ANY(%s)
        ORDER BY c.document_id, c.chunk_index, c.chunk_id
    """
    with _connect(corpus) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, (unique_ids,))
            columns = [
                column.name for column in cursor.description
            ]
            rows = [
                dict(zip(columns, values, strict=True))
                for values in cursor.fetchall()
            ]

    grouped: dict[str, list[dict[str, Any]]] = {
        document_id: [] for document_id in unique_ids
    }
    for row in rows:
        grouped.setdefault(str(row["document_id"]), []).append(row)
    return grouped
