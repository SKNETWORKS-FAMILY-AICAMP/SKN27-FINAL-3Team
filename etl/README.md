# ETL

`etl/`은 외부 원천 데이터를 수집·정제하여 PostgreSQL/pgvector 적재에 사용할 수 있는
형태로 준비하는 공간입니다.

- `legal/`: 법령·시행령·시행규칙의 수집, 정제, 임베딩 적재
- `fault_cases/`: review case와 과실비율 판례의 전처리, 임베딩, HNSW 인덱스 준비
- `fine_rules/`: 과태료·범칙금 분석과 규칙 매핑 데이터 준비
- `common/`: source registry와 ingestion run 추적 유틸리티

현재 런타임 검색 경로는 다음과 같습니다.

```text
text_ml_case_search Agent
-> review_case pgvector search
-> fault_ratio_precedent pgvector search
-> source quota merge
-> Supervisor output schema
```

검색 대상의 원본 적재, 임베딩, HNSW 생성이 끝난 뒤에는 다음 명령으로 세 저장소의
readiness를 확인합니다.

```powershell
python backend/manage.py verify_pgvector_rag_readiness --format json
```
