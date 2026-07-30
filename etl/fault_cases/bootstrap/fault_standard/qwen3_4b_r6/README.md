# 인정기준 Qwen3-Embedding-4B R6 부트스트랩

이 디렉터리는 인정기준 R10 데이터베이스의 최초 구축에 사용하는 검증 완료
Qwen3-Embedding-4B R6 임베딩 묶음이다. 런타임 코드나 임베딩 생성 코드가 아니라
Git으로 전달되는 immutable seed다.

## 포함 파일

- `qwen3_4b_r6_embeddings.jsonl.gz`
  - 전체 레코드: 6,175건
  - 문서 레코드: 6,145건
  - 평가 질의 레코드: 30건
  - 임베딩 차원: 2,560
  - L2 정규화
  - SHA-256: `cd6d031ff775beb7401dcb729007190685a687b43afcad4c7c96207f171b8e8d`
- `qwen3_4b_r6_embeddings_manifest.json`
  - 모델·revision·pooling·dtype·입력 hash와 생성 환경을 기록한다.

## 생성 파이프라인과의 경계

원본 생성·검증 코드는 `etl/fault_cases/standard_TEST/` 아래 자체 artifact 경로를
사용한다. 해당 Python 파일들은 이 bootstrap 경로를 읽거나 쓰지 않으며, 이
디렉터리 이동 때문에 수정하지 않는다.

## 적재 규칙

- 최초 R10 적재기는 manifest와 GZ의 SHA-256을 먼저 검증한다.
- `record_type`이 문서인 6,145건만 운영 DB에 적재한다.
- 평가 질의 30건은 운영 문서 인덱스에 적재하지 않는다.
- 문서 corpus를 다시 임베딩하지 않고 검증된 벡터를 그대로 사용한다.

