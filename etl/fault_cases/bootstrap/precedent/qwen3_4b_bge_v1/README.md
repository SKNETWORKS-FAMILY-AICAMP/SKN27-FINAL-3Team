# 판례 NEW++ Qwen 임베딩 부트스트랩

이 디렉터리의 두 데이터 파일은 배포 담당자가 판례 문서를 다시 임베딩하지 않고
바로 PostgreSQL/pgvector에 적재할 수 있도록 Git으로 전달하는 고정 부트스트랩이다.
런타임 Python 패키지나 실험 출력 디렉터리가 아니며, 판례 도메인의
`qwen3_4b_bge_v1` 적재 계약을 나타내는 canonical 위치다.

## 포함 파일

- `01_document_embeddings_qwen3_4b.npy`
  - shape: `(4185, 2560)`
  - dtype: `float32`
  - L2 normalized
  - SHA-256: `bc4bc1146b76784f2ba95f9287e7f1b8d0280e41fa249d0154c94789d453126c`
- `02_document_embedding_metadata.jsonl`
  - rows: `4185`
  - unique cases: `1221`
  - SHA-256: `ab6ab0bedafd3152f9b5ee668b503c35d28288e0c6b421e872866b2f014ff9ff`

## 실제 판례 RAG 적재 범위

metadata에서 `enabled_in_general_accident_search`가 `true`인 행만 적재한다.

- `GENERAL_READY_DIRECT`: 3,109블록 / 768판례
- eligible `SEED_READY`: 230블록 / 57판례
- 합계: 3,339블록 / 825판례

`GENERAL_READY_LEGAL_SUPPORT`, `GENERAL_QUARANTINE`, `GENERAL_EXCLUDED`는 적재하지 않는다.
이 두 파일은 모델 설치 파일이 아니며, 문서 임베딩 재실행 없이 초기 DB를 채우는
입력 데이터다.
