# 법령 RAG PostgreSQL Lexical·pgvector 평가 설계

## 목표

법령 RAG에서 현재 PostgreSQL lexical 검색과 pgvector 검색을 동일한 공개 법령 평가셋으로 비교하고, 임베딩 모델·조문 chunk 전략·생성 답변 품질을 근거로 pgvector 우선 전환 가능 여부를 판단한다.

## 범위와 담당 경계

- 대상은 `law`, `enforcement_decree`, `enforcement_rule`, `administrative_rule`, `notice` 법령 source family다.
- 수정 대상은 법령 seed·검색·평가 계약과 문서뿐이다.
- `text_ml_case_search`, 과실비율 판례, 심의사례, 과실기준, 해당 Elasticsearch 인덱스와 이재강 담당 ETL은 읽기·수정·재적재 대상에서 제외한다.
- Elasticsearch를 법령 RAG에 새로 도입하거나, 기존 Elasticsearch를 제거하거나, 운영 API의 검색 우선순위를 바꾸지 않는다.

## 현재 구조

`law_chunks`는 법령 원문, 조문 위치, 출처 URL, 시행일과 폐지일을 보관한다. `law_embeddings`는 `chunk_id`에 연결된 pgvector와 provider/model/dimension metadata를 보관한다. 런타임은 pgvector가 준비됐을 때만 벡터 검색을 하고, 결과가 없거나 사용할 수 없으면 같은 `law_chunks`의 PostgreSQL lexical 검색, 그 다음 Django RAG fallback으로 내려간다. Neo4j는 벡터 DB가 아니며 필터를 통과한 법령 결과의 관계 확장에만 사용한다.

## 비교 단위

각 평가 질의는 다음 필드를 가진다.

```json
{
  "query_id": "law_q001",
  "query": "교차로에서 신호를 위반한 차량의 의무는 무엇인가",
  "temporal_basis": {"mode": "as_of", "effective_at": "2026-07-21"},
  "scope": {"allowed_source_types": ["law", "enforcement_rule"]},
  "expected_source_references": ["law:road-traffic-act:article-5"],
  "reference_answer": "운전자는 신호 또는 지시를 따라야 한다.",
  "scenario": "신호 준수",
  "data_classification": "public_law"
}
```

평가 어댑터는 lexical과 pgvector의 결과를 아래 공통 후보 형태로 정규화한다.

```json
{
  "query_id": "law_q001",
  "backend": "postgres_lexical",
  "rank": 1,
  "source_reference": "law:road-traffic-act:article-5",
  "source_type": "law",
  "source_url": "https://www.law.go.kr/...",
  "effective_date": "2025-01-01",
  "expire_date": null,
  "score": 0.84,
  "latency_ms": 18,
  "embedding_space_id": null
}
```

pgvector 후보에는 `embedding_space_id`로 provider, model, dimensions, chunk strategy와 corpus snapshot hash를 기록한다. 서로 다른 embedding space의 벡터는 같은 인덱스나 점수 분포로 혼합하지 않는다.

## 평가 순서

1. 공개 법령만으로 최소 20개 질의를 작성하고, source reference와 기준일을 사람이 검토한다.
2. 현재 법령 chunk와 현재 embedding space에서 PostgreSQL lexical과 pgvector 후보를 수집한다.
3. Recall@1/3/5, MRR, nDCG@5, no-result rate, p50/p95 latency를 계산한다.
4. 기준선을 통과한 상위 두 embedding 후보만 law chunk 전략을 비교한다. chunk는 조문·항·호 경계를 보존하며, 임의 문자 수 절단을 우선하지 않는다.
5. 선택된 조합의 retrieved contexts로 고정 생성 모델의 답변을 만들고 RAGAS Context Precision, Context Recall, Faithfulness, Answer Relevancy를 측정한다.
6. 모델·chunk·backend별 결과, 비용, 실행 환경, 실패와 한계를 기술 검증 리포트에 기록한다.

## 임베딩·chunk 실험 원칙

- 후보는 현재 `intfloat/multilingual-e5-large` 계열, `text-embedding-3-small`, `text-embedding-3-large`, 그리고 실제로 준비된 로컬 후보만 사용한다.
- Ollama는 후보 모델명이 아니라 로컬 모델 실행 환경이다. Ollama CLI 또는 모델이 준비되지 않은 환경에서는 해당 후보를 `not_available`로 기록하며 대체 결과를 만들지 않는다.
- OpenAI 후보와 로컬 후보는 동일 corpus snapshot, 동일 질의, 동일 top-k, 동일 temporal/scope filter로 비교한다.
- 1차에는 현재 조문 경계 chunk를 고정해 모델만 비교한다. 2차에는 1차 상위 두 모델에 대해서만 조문 경계 유지형 chunk 전략과 overlap을 비교한다.
- 모든 실행은 corpus snapshot hash, chunk strategy, provider/model/dimensions, 실행 일시, 코드 revision을 결과에 남긴다.

## RAGAS 실행 경계

- RAGAS에는 `data_classification=public_law` 질의와 공개 법령 context만 전달한다. 사용자 채팅, OCR 원문, 첨부파일, 세션 ID, 개인식별정보는 입력하지 않는다.
- 비교 공정성을 위해 한 A/B run 안에서는 답변 생성 모델과 RAGAS 판정 모델을 고정한다.
- 최초 유료 파일럿은 최대 20개 질의, 질의당 top-5 context, 판정 모델 1개로 제한한다.
- API 키, 모델 식별이 가능한 오류 원문, retrieved context 전문은 콘솔 로그에 남기지 않는다. 결과 리포트에는 aggregate metric, token/cost 합계, 실패 수와 안전한 reason code만 남긴다.
- RAGAS 실행 실패나 비용 한도 초과는 평가 실패가 아니라 `not_evaluated`로 기록한다. 이 경우 pgvector 전환 승인을 내리지 않는다.

## 전환 판정 기준

pgvector 후보는 다음을 모두 만족할 때만 별도 전환 이슈의 후보가 된다.

- Recall@5가 PostgreSQL lexical 기준보다 2%p 이상 낮지 않다.
- MRR과 nDCG@5가 각각 기준선보다 0.02 이상 낮지 않다.
- no-result rate가 기준선보다 높지 않다.
- p95 latency가 기준선의 1.5배를 넘지 않는다.
- RAGAS Context Recall과 Faithfulness가 기준선보다 각각 0.03 이상 낮지 않다.
- 모든 top-k 결과가 source URL, source reference, 시행일/폐지일 필터를 보존한다.

하나라도 충족하지 못하면 PostgreSQL lexical fallback과 현재 운영 경로를 유지하고, 리포트에 탈락 지표와 다음 실험 가설을 기록한다.

## 검증과 산출물

- 평가 입력·후보·metric 계산은 외부 DB와 API 없이 fixture로 단위 테스트한다.
- 실제 PostgreSQL lexical/pgvector 비교와 RAGAS 파일럿은 명시적 실행 명령으로만 수행한다.
- 결과 파일은 Git에 넣지 않는다. 실행 시 생성되는 로컬 artifact에는 입력 snapshot hash와 집계 결과만 남긴다.
- 완료 시 법령 RAG 기술 검증 리포트에 기술 선택 이유, 데이터 흐름, A/B 지표, RAGAS 결과, 비용·지연시간, 전환 결론과 한계를 기록한다.
