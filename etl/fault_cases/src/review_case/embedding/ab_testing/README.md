# 심의사례 임베딩 모델 A/B 코드

이 패키지는 운영용 `review_case.embedding` 코드와 분리된 실험 전용 코드 위치다.

구현 순서:

1. `config.py`, `paths.py`
2. `build_corpus_snapshot.py`
3. `build_eval_candidates.py`, `validate_eval_set.py`
4. `run_openai_embeddings.py`, `run_local_embeddings.py`
5. `validate_vectors.py`, `load_pgvector.py`
6. `evaluate_retrieval.py`

첫 완료 기준은 현재 구조화 청크 904개로부터 `embedding_text_v1` 904개와 corpus manifest를 재현 가능하게 생성하는 것이다.

평가 query와 qrels의 원본은 다음 경로에서 관리한다.

```text
etl/fault_cases/evaluation/review_case/embedding_ab/v1/
```

생성 결과는 Git에서 제외되는 다음 경로에 저장한다.

```text
etl/fault_cases/artifacts/embedding_ab/review_case/
```
