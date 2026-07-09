# `law_embeddings` 벡터 조회 가이드

> 대상: `law_chunks`/`law_embeddings`(PostgreSQL + pgvector)에 적재된 임베딩을 코드에서 어떻게 조회하는지.
> 작성 배경: 2026-07-08 법령DB 재적재(`load_sql.py`) 이후 실제 라이브 DB에 대고 직접 검증한 내용.

---

## 1. 조회 함수는 이미 있다 — `etl/legal/search.py::search_laws()`

임베딩 벡터 유사도 검색 전담 함수가 이미 구현돼 있다. 직접 SQL을 짤 필요 없이 이 함수를 쓰면 된다.

```python
from etl.legal.search import search_laws

results = search_laws(
    "과태료 부득이한 사유 도난",   # 자연어 질의
    top_k=3,
    provider="openai",              # ⚠️ 2절 참고 — 반드시 명시할 것
)
for r in results:
    print(r["source_name"], r.get("article_no"), r["score"])
    print(r["provision_text"][:100])
```

### 내부 동작

1. 질의 텍스트를 임베딩으로 변환 — `provider`에 따라 `embed_query_with_openai()` 또는
   `embed_query_with_sentence_transformers()` 사용.
2. pgvector 코사인 거리 연산자 `<=>`로 `law_embeddings ⋈ law_chunks` JOIN 조회.
   유사도 점수는 `1 - (embedding_vector <=> 질의벡터)`.
3. `ORDER BY embedding_vector <=> 질의벡터 LIMIT top_k`로 가장 가까운 조문 반환.
4. `temporal_basis`(시행일 기준 필터), `scope.allowed_source_types`(소스 타입 필터) 옵션 지원.

---

## 2. ⚠️ 함수 기본값이 지금 DB와 안 맞음 — `provider` 필수 명시

`search_laws()`의 `provider` 기본값은 `"sentence-transformers"`이지만, 현재 적재된 임베딩은
전부 `embedding_provider='openai'`로 저장돼 있다:

```sql
SELECT embedding_provider, count(*) FROM law_embeddings GROUP BY embedding_provider;
--  embedding_provider | count
-- ---------------------+--------
--  openai              | 100412
```

`search_laws()` 내부 쿼리에 `WHERE e.embedding_provider = %s` 필터가 있어서, `provider`를
명시하지 않으면 **에러 없이 조용히 0건**이 반환된다. 반드시 `provider="openai"`를 넘길 것.

---

## 3. ⚠️ 질서위반행위규제법은 벡터 검색에 안 잡힘

`질서위반행위규제법`(제7·14·16·20조 포함, 61개 청크)은 `law_chunks`엔 있지만 **임베딩 생성 자체가
안 돼 있어서** `law_embeddings`엔 이 소스의 행이 0건이다. 따라서 `search_laws()`(벡터 유사도 검색)로는
이 법을 절대 찾을 수 없다.

이 법의 조문이 필요하면 벡터 검색이 아니라 **정확한 (법령명, 조번호)로 직접 조회**해야 한다:

```python
from etl.legal.search import get_provision_text, law_code_exists

text = get_provision_text("질서위반행위규제법", "제7조")
exists = law_code_exists("질서위반행위규제법 제7조")
```

`ai/agents/appeal_decision_flow/law_refs.py`가 정확히 이 방식(정확 매칭)을 쓰고 있어서 이 갭의
영향을 안 받는다.

---

## 4. 실측 결과 (2026-07-08, 실제 OpenAI API 호출로 검증)

```python
search_laws("과태료 부득이한 사유 도난", top_k=3, provider="openai")
```

```
자동차관리법 시행규칙  (article_no=None)  score=0.4322
자동차관리법 시행규칙  (article_no=None)  score=0.4294
자동차관리법 시행규칙  (article_no=None)  score=0.4264
```

메커니즘 자체(임베딩 생성 → pgvector 유사도 계산 → 반환)는 정상 동작을 확인했다. 다만 이 질의로는
관련성 낮은 결과(자동차관리법 시행규칙의 별표/표 형식 청크, `article_no=None`)가 상위에 나왔다.
원인 후보:
- 별표·표 데이터가 일반 텍스트 임베딩과 유사도 계산이 잘 안 맞는 경우가 많음
- `top_k`가 낮아 상위권이 우연히 표 데이터로 몰림

개선 방향(필요시):
- `top_k`를 늘려 표본을 넓힌 뒤 후처리로 필터링
- `scope={"allowed_source_types": ["law"]}`로 법률 본문만 필터링 (시행규칙 별표 등 제외)

---

## 5. raw SQL로 직접 조회하고 싶을 때

실무에서는 위 `search_laws()`를 쓰는 게 훨씬 편하다(쿼리 벡터 생성을 함수가 대신 해줌). 직접
찔러보고 싶다면 쿼리 벡터를 파이썬에서 미리 만들어 SQL에 꽂아야 한다:

```sql
SELECT c.source_name, c.article_no,
       1 - (e.embedding_vector <=> '[0.01,0.02,...]'::vector) AS score
FROM law_embeddings e
JOIN law_chunks c ON e.chunk_id = c.chunk_id
WHERE e.embedding_provider = 'openai'
ORDER BY e.embedding_vector <=> '[0.01,0.02,...]'::vector
LIMIT 5;
```

`docker exec skn27-postgres psql -U postgres -d law_db` 로 접속해서 실행하면 된다(로컬 dev 기준
컨테이너명·자격증명은 `docker-compose.yml` 참고).

---

## 관련 문서

- `docs/architecture/law_agent_architecture_summary.md` — `search_laws()`를 실제로 쓰는
  LawGroundSearch Agent 전체 아키텍처(시퀀스 다이어그램, Neo4j 그래프 확장 포함)
- `ai/agents/appeal_decision_flow/law_refs.py` — 벡터 검색이 아니라 정확 매칭(`get_provision_text`)만
  쓰는 소비자 예시
