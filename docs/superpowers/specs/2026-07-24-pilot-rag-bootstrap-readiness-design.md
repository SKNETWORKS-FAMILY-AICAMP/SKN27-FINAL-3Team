# AWS 파일럿 RAG 부트스트랩 준비 설계

## 목적

새로운 서울 리전 RDS에서 법령과 심의사례 pgvector 검색을 실제로 준비한 뒤에만
첫 공개 릴리스를 허용한다. 기존 배포 흐름의 `load_production_rag_seed`는 법령만
적재하면서도 심의사례 readiness를 요구하므로, 현재 상태에서는 신규 RDS의 첫
부트스트랩이 반드시 실패한다.

## 승인된 방향

비용 절약형 파일럿에서는 별도의 RDS 인스턴스나 데이터베이스를 추가하지 않는다.
기존 `law_db` 안에서 Django 법령 테이블과 심의사례 전용 테이블을 분리하고, 동일한
OpenAI `text-embedding-3-large` 1024차원 공간을 사용한다.

판례 과실비율 corpus는 첫 공개의 필수 readiness가 아니라 선택 readiness로
유지한다. 다만 매니페스트에는 테스트 fixture가 아닌 법제처 공식 원문의 파일럿
부분집합을 포함해 데이터 출처와 향후 전체 재수집 경로를 보존한다.

## 운영 시드

검증된 파일럿 묶음은 다음 네 역할로 구성한다.

| 역할 | 행 수 | 용도 |
| --- | ---: | --- |
| `legal_chunks` | 97,394 | 법령 검색 원문 |
| `legal_embeddings` | 97,394 | OpenAI 1024차원 법령 벡터 |
| `review_case_chunks` | 904 | 심의사례 source-specific pgvector 입력 |
| `precedent_fault_ratio_chunks` | 343 | 법제처 실제 판례 88건의 파일럿 부분집합 |

매니페스트 계약은 `production_rag_seed_manifest.v1`이며, 독립 검증과 외부 쓰기 없는
dry-run을 모두 통과해야 한다. 현재 승인 대상 매니페스트 SHA-256은
`279e78cf70db05156c316ddfbddff2eb4c08ea8c199fcb1df1f0f40600eeed6c`다.

## 데이터 흐름

1. 데이터베이스 유지보수 역할로 `law_db`에 vector extension과 심의사례 전용
   스키마를 적용한다.
2. Django migration과 심의사례 스키마 적용이 성공한 뒤 앱 역할에 필요한 최소
   테이블·시퀀스 권한을 부여한다.
3. 공개 포트를 열지 않은 initial RAG stage에서 Redis, ClamAV, backend만 시작한다.
4. S3의 버전 관리된 시드 묶음을 내려받아 매니페스트 해시와 모든 artifact 해시를
   다시 검증한다.
5. 심의사례 청크 904개를 전용 테이블에 idempotent upsert한다.
6. 명시적인 유료 호출 승인 플래그가 있을 때만 미생성 심의사례 임베딩을 생성한다.
7. 심의사례 HNSW 인덱스를 만들고 행 수·임베딩 공간·인덱스를 검증한다.
8. 법령 청크와 임베딩을 하나의 트랜잭션으로 적재하고 법령 HNSW를 검증한다.
9. 법령·심의사례 readiness와 실제 검색 smoke를 모두 통과해야
   `.production-rag-seed.complete`를 기록한다.
10. 이 완료 표식과 동일한 매니페스트 해시가 확인된 릴리스만 공개 승격할 수 있다.

## 실패와 복구

- 매니페스트, 청크, 벡터, 스키마 또는 HNSW 검증이 하나라도 실패하면 공개 승격을
  수행하지 않는다.
- 유료 임베딩은 `--allow-paid-provider-call`과 배포 스크립트의 별도 승인 스위치가
  없으면 시작하지 않는다.
- 심의사례 적재는 동일 `chunk_id`에 대한 재실행이 가능해야 하고, 기존 검증된
  임베딩은 다시 결제하지 않는다.
- initial stage 실패 시 stage Compose와 stage 전용 Redis·ClamAV 볼륨 및 미완성
  release 디렉터리만 제거한다. RDS와 승인된 S3 시드는 보존한다.
- 로그에는 OpenAI 키, DB 암호, 원문 전체, OAuth code를 출력하지 않는다.

## 검증

- 신규 source-specific loader의 manifest role 제한, 빈 파일 차단, idempotent upsert,
  유료 호출 승인 차단을 단위 테스트한다.
- `Maintain-PilotDatabase.ps1`에서 심의사례 스키마 적용이 권한 부여보다 먼저
  실행되는지 계약 테스트한다.
- `Load-Rag-Seed-Pilot.ps1`에서 manifest 검증, 심의사례 적재·임베딩·HNSW,
  법령 적재, readiness, smoke, 완료 표식 순서를 계약 테스트한다.
- 관련 Django 테스트, AWS pilot 인프라 테스트, PowerShell parser, Docker Compose
  config를 다시 실행한다.

## 사람 작업

- 심의사례 904개 OpenAI 임베딩의 1회 유료 호출을 승인한다.
- 첫 공개 승격 직전에 Google OAuth 일회용 code를 발급한다.
- RunPod API key와 Endpoint ID를 발급해 private runtime에 입력한다.
