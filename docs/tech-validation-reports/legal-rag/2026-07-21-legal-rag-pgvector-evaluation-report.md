# 법령 RAG PostgreSQL Lexical·pgvector 기술 검증 리포트

## 상태

**평가 설계 완료 · 실행 결과 대기**

이 문서는 Issue #280의 법령 RAG 평가 결과를 기록한다. 판례·심의사례·과실기준과 이재강 담당 RAG는 범위에 포함하지 않는다.

## 1. 문제와 목표

법령 RAG는 PostgreSQL lexical fallback과 pgvector 검색 경로를 함께 가진다. pgvector를 우선 사용하거나 단일화 후보로 검토하려면, 의미 검색의 장점뿐 아니라 조문·출처·시점 정확도와 실패율을 PostgreSQL lexical 기준선과 비교해야 한다.

## 2. 기술 구조와 선택 이유

| 구성요소 | 역할 | 선택 이유 |
| --- | --- | --- |
| PostgreSQL lexical | 기준선 검색 및 vector 미사용 시 fallback | 임베딩 API·모델 없이 조문·키워드 기반 검색을 제공한다. |
| PostgreSQL + pgvector | 법령 chunk의 의미 기반 후보 검색 | 표현이 다른 질의와 법령 문구 사이의 의미 유사도를 찾는다. |
| `law_chunks` | 조문 원문·출처·적용일 저장 | 검색 결과가 법령 원문과 적용 시점을 잃지 않게 한다. |
| `law_embeddings` | embedding vector와 provider/model/dimension 저장 | 서로 다른 모델·차원의 벡터 혼합을 차단한다. |
| Neo4j | 필터를 통과한 법령의 관계 확장 | 벡터 DB를 대체하지 않고 조문 관계 보강에만 사용한다. |
| RAGAS | retrieved context와 생성 답변의 품질 평가 | 검색 순위 지표만으로 판단할 수 없는 근거 충실성과 답변 관련성을 확인한다. |

## 3. 평가 대상과 제외 범위

### 대상

- `law`, `enforcement_decree`, `enforcement_rule`, `administrative_rule`, `notice`
- PostgreSQL lexical ↔ pgvector
- 공개 법령 질의, 출처 reference, 적용일·폐지일 필터
- 임베딩 모델과 조문 경계 기반 chunk 전략

### 제외

- Elasticsearch 비교
- 과실비율 판례·심의사례·텍스트 ML·과실기준
- 사용자 대화, OCR 원문, 첨부파일, 개인식별정보
- 운영 API 검색 우선순위 변경과 Elasticsearch 제거

## 4. 평가 방법

### 검색 A/B

동일 질의·기준일·source scope에 대해 두 backend의 후보를 수집하고 다음 지표를 계산한다.

- Recall@1, Recall@3, Recall@5
- MRR
- nDCG@5
- no-result rate
- p50/p95 latency
- 출처 URL, source reference, 시행일·폐지일 필터 보존 여부

### 임베딩과 chunk 실험

1. 현재 조문 경계 chunk를 고정한 상태에서 임베딩 후보를 비교한다.
2. 상위 두 모델만 남겨 조문·항·호 경계를 보존하는 chunk 전략과 overlap을 비교한다.
3. provider/model/dimension/chunk strategy/corpus snapshot을 `embedding_space_id`로 분리해 기록한다.

### RAGAS 파일럿

- 최대 20개 공개 법령 질의와 top-5 context로 실행한다.
- Context Precision, Context Recall, Faithfulness, Answer Relevancy를 기록한다.
- 한 A/B 실행 안에서는 답변 생성 모델과 RAGAS 판정 모델을 고정한다.
- 유료 호출 실패 또는 비용 한도 초과는 `not_evaluated`로 기록하며, pgvector 전환 근거로 사용하지 않는다.

## 5. 전환 판정 기준

| 기준 | 통과 조건 | 결과 |
| --- | --- | --- |
| Recall@5 | lexical 대비 -2%p 이내 | 실행 전 |
| MRR | lexical 대비 -0.02 이내 | 실행 전 |
| nDCG@5 | lexical 대비 -0.02 이내 | 실행 전 |
| no-result rate | lexical보다 높지 않음 | 실행 전 |
| p95 latency | lexical의 1.5배 이하 | 실행 전 |
| RAGAS Context Recall | lexical 대비 -0.03 이내 | 실행 전 |
| RAGAS Faithfulness | lexical 대비 -0.03 이내 | 실행 전 |
| 법령 metadata | 모든 top-k 결과가 출처·시점 필터 보존 | 실행 전 |

## 6. 실행 기록

| 항목 | 상태 | 근거 |
| --- | --- | --- |
| 공개 법령 평가셋·정답지 | 미실행 | Issue #280 구현 단계에서 생성 |
| lexical 후보 수집 | 미실행 | PostgreSQL 평가 환경 필요 |
| pgvector 후보 수집 | 미실행 | 동일 embedding space의 법령 seed 필요 |
| 임베딩 모델 A/B | 미실행 | 후보 모델·corpus snapshot 확정 필요 |
| chunk 전략 A/B | 미실행 | 1차 모델 결과 후 실행 |
| RAGAS 파일럿 | 미실행 | 공개 법령 데이터·승인된 유료 호출 사용 예정 |

## 7. 리스크와 한계

- pgvector와 lexical의 결과 비교는 동일 corpus snapshot과 동일 temporal/scope filter가 아니면 유효하지 않다.
- Ollama는 실행 환경이며, 설치·모델 준비가 확인되지 않으면 로컬 후보 결과를 만들지 않는다.
- RAGAS 점수는 판정 모델과 생성 모델의 영향을 받으므로, A/B run 안에서는 두 모델을 고정한다.
- RAGAS는 검색 ranking 지표를 대체하지 않는다.

## 8. 결론

현재는 설계와 리포트 구조만 준비됐다. 실제 A/B와 RAGAS 결과가 기록되기 전에는 pgvector 우선 전환 또는 단일화 결론을 내리지 않는다.
