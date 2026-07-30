"""NEW++-BGE 판례 검색 서비스의 고정 설정."""

from __future__ import annotations

from dataclasses import dataclass
@dataclass(frozen=True, slots=True)
class ServiceSettings:
    """실험에서 검증된 운영 계약을 한곳에 고정한다."""

    contract_version: str = "precedent-newplusplus-v1"
    corpus_version: str = "precedent_direct_seed_v1"
    document_case_count: int = 825
    document_block_count: int = 3339
    embedding_dimension: int = 2560
    candidate_top_k: int = 200
    evaluation_candidate_count: int = 50
    final_top_k: int = 5

    qwen_model_id: str = "Qwen/Qwen3-Embedding-4B"
    qwen_revision: str = "5cf2132abc99cad020ac570b19d031efec650f2b"
    qwen_query_instruction: str = (
        "Instruct: Given a Korean traffic-accident description, retrieve the most "
        "relevant Korean traffic-accident fault-liability precedents\nQuery: "
    )

    bge_model_id: str = "BAAI/bge-reranker-v2-m3"
    bge_revision: str = "324cc40576b08b305b9c65a867c26c173a477ae2"
    bge_max_length: int = 2048
    bge_batch_size: int = 4
