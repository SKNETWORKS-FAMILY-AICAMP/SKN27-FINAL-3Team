# NEW_ABC_TEST

인정기준 RAG의 `pgvector` / `PostgreSQL` / `Neo4j` 비교를 기존 작업과 분리해 실행하는 V5 실험 루트다.

## 경계

- 이 폴더 밖의 기존 실험 산출물은 읽기 전용 참조만 한다.
- 원본 PostgreSQL(`5432`)과 기존 Neo4j에는 쓰지 않는다.
- 이 폴더의 Lab 컨테이너는 PostgreSQL `55433`, Neo4j Bolt `17688`만 사용한다.
- 판례 B-1/C-2 트랙은 이 실험에 포함하지 않는다.

## Gate 순서

`G0 → G1-SCHEMA/TRUTH/INPUT/LABEL → G2 → G3-A/B/C/S → G4`

모든 결과는 `artifacts/run_v5_new_abc_test/`에만 기록한다.

실행 결과와 과학적 한계는 [EXECUTION_STATUS.md](EXECUTION_STATUS.md)에 기록한다.
