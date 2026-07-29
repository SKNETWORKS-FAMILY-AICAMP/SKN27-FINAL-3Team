# 승인 기반 법령 RAG pgvector·Neo4j 적재 설계

## 목표

운영자가 명시적으로 승인한 실행에서만 법령 원문을 수집·청킹·임베딩하고, 검증 가능한 같은 데이터 버전을 PostgreSQL/pgvector와 법령 전용 Neo4j에 적재한다. 새 버전의 모든 검증이 통과하기 전까지 서비스는 마지막 정상 버전만 사용한다.

## 범위와 순서

이번 첫 단계는 과태료·범칙금·법령 근거 검색을 위한 법령 RAG다. 과실비율의 인정기준·심의사례·판례 RAG는 다음 단계에서 독립된 PostgreSQL/Neo4j 파이프라인으로 구현한다. 두 영역은 데이터베이스, Neo4j 컨테이너, Docker 볼륨, 자격증명, 데이터 버전을 공유하지 않는다.

## 선택한 접근

법령 수집부터 서비스 컨테이너 기동 때마다 실행하지 않는다. 승인된 ingestion job이 아래 순서로 실행한다.

1. 법령 원문을 수집하고 버전별 작업 디렉터리에 저장한다.
2. 원문을 검색 가능한 법령 chunk로 정규화한다.
3. OpenAI `text-embedding-3-large`의 1024차원 벡터를 생성한다.
4. `legal_chunks.jsonl`, `legal_embeddings.jsonl` 및 source-specific precedent JSONL을 만들고 SHA-256 manifest를 생성한다.
5. manifest와 모든 artifact의 해시·행 수·vector 유효성을 검증한다.
6. PostgreSQL `law_chunks`, `law_embeddings`과 source-specific precedent 저장소를 적재한다.
7. 법령 전용 Neo4j에 같은 version의 노드·관계를 idempotent `MERGE`로 적재한다.
8. 양쪽 적재 결과와 검색 smoke가 통과한 경우에만 새 버전을 active로 기록한다.

CSV는 법령명, 조문번호, chunk ID, 출처, version을 사람이 검토하기 위한 요약 export로만 생성한다. 임베딩 벡터 원본과 적재 계약은 JSONL과 manifest를 사용한다.

## 기존 계약과의 호환성

기존 `production_rag_seed_manifest.v1`과 승인된 seed SHA-256은 바꾸지 않는다. 법령 Neo4j graph는 이미 검증된 `legal_chunks` artifact와 versioned hint-term 설정에서 결정적으로 파생한다. 따라서 기존 PostgreSQL pgvector loader, artifact hash 검증, source-specific review-case 및 fault-ratio loader는 그대로 유지한다.

기존 문서의 “pgvector-only”는 벡터 검색 backend가 PostgreSQL/pgvector 하나라는 경계를 뜻한다. 이번 변경은 벡터 검색 backend를 추가하지 않는다. Neo4j는 pgvector의 top result와 사용자 용어를 관계적으로 확장하는 보조 evidence graph로만 사용한다.

기존 local Docker Compose의 `neo4j`와 운영 Pilot의 `law-neo4j`는 독립 서비스다. Pilot에는 운영 전용 `law-neo4j`만 추가하며, local 서비스·기존 볼륨·과실비율 전용 `fault-standard-neo4j`를 변경하거나 공유하지 않는다. local 기본값은 Neo4j 비활성으로 유지하고, Pilot은 전용 컨테이너 health, active dataset metadata, graph smoke가 모두 통과할 때만 Neo4j를 활성화한다.

## 법령 Neo4j 구조

Pilot EC2에 `law-neo4j` Docker 서비스를 추가한다. Neo4j는 외부 host port를 노출하지 않고 Pilot 내부 Docker network에서 backend와 ingestion job만 Bolt로 접근한다. 데이터와 로그는 `law_neo4j_data`, `law_neo4j_logs` 전용 named volume에 보관한다. 비밀번호는 runtime SecureString에서 주입하며 코드나 Git에 저장하지 않는다.

그래프는 다음 노드와 관계를 갖는다.

```text
LegalSource -[:HAS_VERSION]-> LawVersion -[:HAS_CHUNK]-> LawChunk
LawChunk -[:HAS_PENALTY|HAS_EXCEPTION|HAS_APPENDIX|RELATED_TO]-> LawChunk
UserTerm -[:NORMALIZES_TO]-> LegalTerm -[:SEARCHES_WITH]-> LawSearchTerm
```

`LawChunk`는 PostgreSQL의 `law_chunks`와 같은 `chunk_id`를 사용한다. `LegalSource`, `LawVersion`, `LawChunk`, 용어 노드에는 unique constraint를 만든다. `etl/legal/export_neo4j.py`의 기존 idempotent import 계약을 manifest bundle 입력으로 확장한다. 전체 chunk 간 `SIMILAR_TO` 그래프는 약 10만 벡터에서 비용이 과도하므로 기본 적재에서 만들지 않는다. 의미 유사도 검색은 PostgreSQL/pgvector가 담당한다.

## 서비스 검색 흐름

1. backend가 사용자 질문을 OpenAI embedding으로 변환한다.
2. PostgreSQL/pgvector가 같은 seed embedding space의 상위 법령 chunk를 검색한다.
3. law-neo4j가 사용자 표현을 법률 용어로 확장하고, 검색된 조문의 벌칙·예외·별표·참조 관계를 확장한다.
4. backend가 확장 근거와 pgvector 결과를 하나의 법령 근거 결과로 정리한다.

법령 Neo4j는 법령 RAG의 required dependency다. Neo4j가 연결되지 않거나 active dataset version의 manifest SHA와 graph metadata가 일치하지 않으면 새 version은 active로 전환하지 않는다. 이미 active인 정상 버전은 유지한다.

## 실행 및 복구

자동 적재는 예약 실행하지 않는다. 운영자가 dataset version을 지정해 SSM 기반 ingestion job을 시작할 때만 실행한다. job은 단일 maintenance lock을 사용하여 동시 실행을 막는다.

각 실행은 단계별 상태, manifest SHA, dataset version, PostgreSQL row count, Neo4j node/relationship count, 시작·종료 시각, 실패 원인을 운영 로그에 남긴다. 실패하면 active marker를 바꾸지 않고 새 staging version을 보존하여 조사와 재실행에 사용한다. 정상 active version과 해당 PostgreSQL/Neo4j 데이터는 새 버전 검증 성공 전까지 삭제하지 않는다.

## 검증 기준

새 법령 데이터 버전은 다음을 모두 만족해야 active가 될 수 있다.

1. JSONL artifact의 SHA-256, byte count, JSON row count가 manifest와 일치한다.
2. 모든 법령 embedding은 provider `openai`, model `text-embedding-3-large`, dimension `1024`이며 finite, non-zero vector다.
3. PostgreSQL `law_chunks`, `law_embeddings`에 searchable 법령 row와 같은 embedding space의 vector가 존재하고 HNSW index가 정상이다.
4. Neo4j의 `LawChunk` 수와 PostgreSQL의 active 법령 chunk 수가 일치하고 source/version별 canonical chunk ID hash가 일치한다.
5. Neo4j constraint와 법령 관계 수가 검증되며, 사용자 용어에서 법률 검색어로 확장하는 Cypher smoke가 결과를 반환한다.
6. `verify_pgvector_rag_readiness`, 법령 pgvector 검색 smoke, Neo4j graph expansion smoke가 모두 통과한다.

## 과실비율 후속 단계

과실비율은 별도 dataset version, source bundle, PostgreSQL source tables, `fault-standard-neo4j` 컨테이너, 전용 Docker volume과 환경변수를 사용한다. 그래프에는 사고 유형, 차량, 차로 진행, 신호, 수정요소, 적용 규칙, 가감 비율과 근거 관계를 적재한다. 법령 Neo4j와 과실비율 Neo4j 사이에는 공용 컨테이너, 볼륨, 비밀번호, 환경변수, active marker가 없다.
