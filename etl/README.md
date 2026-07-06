# etl

외부 또는 원천 데이터를 수집하고 정제해 저장소에 적재 가능한 형태로 만드는 공간이다.

## 하위 폴더 역할

| 폴더 | 역할 |
|---|---|
| `common/` | source registry, ingestion run tracking, 공통 ETL 유틸리티를 둔다. |
| `legal/` | 도로교통법, 시행령, 시행규칙, 고시, 행정 기준 수집과 전처리를 둔다. |
| `fine_rules/` | 과태료·범칙금·벌칙 분석용 룰과 매핑 데이터 준비 로직을 둔다. |
| `fault_cases/` | 판례, 유튜브 자막, 과실비율심의사례 수집과 전처리를 둔다. |
| `vision_manifest/` | 이미지/영상 dataset manifest와 metadata 준비 로직을 둔다. |

## 배치 원칙

- API 응답 로직과 화면 로직은 `etl/`에 두지 않는다.
- 법률 원문 데이터와 과태료 분석용 룰/매핑 데이터는 서로 분리한다.
- 원천 데이터 위치, 수집일, 이용 조건, 원문 reference를 추적 가능하게 남긴다.
- 저장소 구조와 migration은 `storage/`에 둔다.

## Local reranker model files

`models/bge-reranker-v2-m3/` is a local model directory used only for offline retrieval evaluation.

It was introduced for the fault-case and precedent search A/B experiments, where pgvector, BM25/Nori, Elasticsearch vector, and hybrid search candidates were normalized into a common candidate format and then rescored with a local reranker.

The model is not required for the default V1/V2 Agent runtime path.

Current runtime search path:

```text
text_ml_case_search Agent
-> BM25/Nori review_case search
-> BM25/Nori fault_ratio_precedent search
-> evidence merge
-> Supervisor output schema
```

The local reranker model is only needed when regenerating optional evaluation outputs such as:

```text
retrieval_ab_reranker_scores.jsonl
retrieval_ab_score_summary.json
판례 검색 A-B 정량 점수표.md
판례 검색 A-B 평가 결과 보고서.md
```

Do not commit the model files to GitHub.

Reason:

```text
models/bge-reranker-v2-m3/model.safetensors
size: about 2.3 GB
GitHub LFS single-object limit: 2,147,483,648 bytes
```

Even with Git LFS, GitHub rejects this file because it is larger than the single-file limit. The model should be downloaded locally when reranker evaluation is needed.

Recommended handling:

```text
1. Keep models/bge-reranker-v2-m3/ only on the local machine.
2. Add models/ or models/bge-reranker-v2-m3/ to .gitignore.
3. Commit only source code, schemas, Docker/config files, and Markdown reports.
4. If reranker evaluation is not being regenerated, the model is not needed.
```

Typical local reranker command, only when the model exists locally:

```powershell
.\.venv\Scripts\python.exe -B -m etl.fault_cases.src.traffic_precedents.precedent_search.evaluation.run_local_reranker --model models/bge-reranker-v2-m3 --input-field chunk_text --batch-size 4 --device cpu
```

If this model directory is missing, the Agent itself can still run. Only the optional reranker score comparison step is unavailable.
