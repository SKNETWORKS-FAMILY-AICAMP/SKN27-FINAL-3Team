# 판례 RAG 교체 인수 문서

## 활성 파이프라인

```text
collect
→ validate-collection
→ preprocess
→ semantic-blocks
→ classify
→ validate-classification
→ build-rag-records
→ embed
→ load
```

전체 실행은 stage별 CLI 인자 배열을 담은 JSON 파일과 함께 실행한다.

```powershell
python -m etl.fault_cases.src.traffic_precedents.run_pipeline `
  --stage all `
  --pipeline-config C:\deployment\precedent_pipeline.json
```

최초 배포에서는 문서 임베딩을 다시 실행하지 않는다. 저장소에 포함된 다음 두 파일을
loader에 직접 전달한다.

```text
etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/
├─ 01_document_embeddings_qwen3_4b.npy
└─ 02_document_embedding_metadata.jsonl
```

DB 연결 없는 사전 검증:

```powershell
python -m etl.fault_cases.src.traffic_precedents.run_pipeline `
  --stage load `
  --embeddings etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/01_document_embeddings_qwen3_4b.npy `
  --metadata etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/02_document_embedding_metadata.jsonl
```

실제 적재 시 위 명령에 `--apply`와 `--dsn`을 추가한다. loader는 다음 조건을 모두
통과한 뒤에만 transaction을 시작한다.

- NPY SHA-256 일치
- metadata SHA-256 일치
- 원본 4,185행과 metadata 행 정렬 일치
- `enabled_in_general_accident_search=true` 선택 결과 3,339블록/825판례
- 선택 등급이 `GENERAL_READY_DIRECT` 또는 `SEED_READY`
- 임베딩 차원 2,560, float32, 유한값

고정 bootstrap의 운영 identity는 다음과 같다. 이 값은 파일 내용, 모델 revision,
건수와 차원의 canonical JSON으로 계산하므로 provider 호출이나 DB 상태에 의존하지
않는다.

| 항목 | 승인값 |
|---|---|
| NPY SHA-256 | `bc4bc1146b76784f2ba95f9287e7f1b8d0280e41fa249d0154c94789d453126c` |
| metadata SHA-256 | `ab6ab0bedafd3152f9b5ee668b503c35d28288e0c6b421e872866b2f014ff9ff` |
| model | `Qwen/Qwen3-Embedding-4B` |
| revision | `5cf2132abc99cad020ac570b19d031efec650f2b` |
| seed version | `sha256:af0a4a40f983dcdaeaaeb57e54962a514338b8644c33a6a807f1e6214878b2db` |
| exact corpus | 3,339 blocks / 825 cases / 2,560 dimensions |

## 파일럿 versioned seed 운영

`precedent_newplusplus.seed_releases`와 `block_versions`는 immutable version을
보관하고, `active_seed`가 현재·직전 version을 가리킨다. 애플리케이션은
`precedent_newplusplus.blocks` view를 통해 active version만 읽는다. app role에는
schema `USAGE`와 `blocks`, `seed_releases`, `active_seed`의 `SELECT`만 부여하며
inactive `block_versions`와 쓰기 권한은 노출하지 않는다.

운영 반영 순서는 다음과 같다. 한 단계가 실패하면 다음 단계로 진행하지 않는다.

1. 검증된 브랜치를 병합하고 12자리 immutable release SHA를 고정한다.
2. 기존 private runtime SSM parameter와 운영 legal seed 97,394건이 복구된 상태인지
   확인한다. legal seed와 NEW++ precedent seed는 서로 다른 적재·version 경계다.
3. database-maintenance profile과 공통 host lock을 사용하는 다음 명령으로 schema,
   stage, compare-and-swap promotion, master/app read-only verification, SSM version
   동기화를 수행한다.

   ```powershell
   pwsh -File .\deploy\aws-pilot\Maintain-PilotDatabase.ps1 `
     -RuntimeEnvFile <PRIVATE_RUNTIME_ENV_PATH> `
     -ReleaseTag <12_CHAR_RELEASE_SHA> `
     -TerraformDirectory <TERRAFORM_PILOT_DIRECTORY>
   ```

4. SSM SecureString에 정확히 한 줄의
   `PRECEDENT_NEWPLUSPLUS_SEED_VERSION=sha256:<64 lowercase hex>`가 있고 DB active
   pointer와 일치하는지 확인한다. `Deploy-Pilot.ps1`은 이 SSM 값을 권위값으로
   다시 주입한다.
5. 별도 승인된 legal/review seed 작업이 필요할 때만 `Load-Rag-Seed-Pilot.ps1`을
   실행한다. NEW++ 고정 bootstrap 적재 자체는 embedding provider를 호출하지
   않는다.
6. app-release는 target backend image에서 `verify_precedent_newplusplus_seed`와
   `verify_pgvector_rag_readiness`를 모두 통과해야 container와 evidence를 승격한다.
7. 600초 acceptance, G8 smoke, 13/13 E2E와 GO/NO-GO는 운영 실행 후 별도로
   기록한다.

seed pointer만 되돌릴 때는 이미지 롤백과 결합하지 않고 다음 전용 명령을 사용한다.

```powershell
pwsh -File .\deploy\aws-pilot\Rollback-PilotPrecedentSeed.ps1 `
  -ExpectedActiveSeedVersion <CURRENT_SHA256_SEED_VERSION> `
  -ReleaseTag <12_CHAR_RELEASE_SHA> `
  -TerraformDirectory <TERRAFORM_PILOT_DIRECTORY>
```

명령은 전달한 active version이 실제 pointer와 다르거나 verified previous version이
없으면 변경 없이 실패한다. 성공 시 active/previous를 원자적으로 교환하고 SSM을
반환된 active version으로 갱신·재조회한 뒤 master와 app credential로 다시
검증한다. app image/release rollback은 계속 `Rollback-Pilot.ps1`이 담당한다.

## 검색 연결

과실비율 에이전트의 호출부는 수정하지 않았다.

```python
from etl.fault_cases.src.traffic_precedents.precedent_search.pgvector.retriever import (
    search_query,
)
```

활성 `search_query("fault_ratio", query, top_k)` 내부 흐름:

```text
Qwen3-Embedding-4B 질문 임베딩
→ 3,339 의미 블록 cosine 검색
→ 판례별 최고 블록
→ 고유 판례 Top 200
→ ACCIDENT_FACT + FAULT_DECISION 문맥
→ BGE rerank
→ 기존 에이전트 row 계약으로 Top K 반환
```

## 이번 작업에서 실행하지 않은 외부 작업

- 국가법령정보센터 실제 재수집
- Qwen 문서 재임베딩
- 운영 PostgreSQL schema 생성 및 NEW++ 데이터 적재
- Qwen/BGE GPU 실검색
- AWS 배포
- app-release, 600초 acceptance와 배포 후 13개 E2E
- supervisor, 인정기준 RAG, 심의사례 RAG 변경
