# 오늘 한 일 — 질서위반행위규제법 제8~10조 MG 참조 추가 (2026-07-08)

> 대상 코드: `ai/agents/appeal_decision_flow/law_refs.py`
> 관련 커버리지 조사: 그래프 DB(Neo4j) 텍스트 매칭 감사로 발견

---

## 1. 어떻게 발견했나

`law_ground_search` 에이전트가 그래프 DB에서 "관련 조문"을 찾을 때 쓰려던 `HAS_PENALTY`/
`HAS_APPENDIX`/`HAS_EXCEPTION` 관계가 실제로는 **하나도 적재돼 있지 않다는 걸 먼저 확인**했다.
이 관계를 생성하는 스크립트(`etl/legal/extract_extra_relations.py`)는 존재하지만 결과 파일
(`law_extra_relations.jsonl`)이 없고, `export_neo4j.py`도 이 파일을 참조하지 않는다 — 작성만
되고 파이프라인에 연결된 적이 없는 죽은 스크립트였다.

그래서 그래프 순회 대신 **텍스트 매칭**으로 우회했다:

```cypher
MATCH (c:LawChunk)
WHERE c.source_name IN ['도로교통법','도로교통법 시행규칙','질서위반행위규제법']
  AND c.provision_text CONTAINS '과태료'
  AND c.article_no IS NOT NULL
RETURN DISTINCT c.source_name, c.article_no
ORDER BY c.source_name, c.article_no
```

이 결과를 코드가 실제로 참조하는 조문 목록(`grep -rhoE "제[0-9]+조..." ai/agents/appeal_decision_flow/*.py`)과
대조했다.

## 2. 발견한 것

- **도로교통법**(160조 외 5개 후보)·**도로교통법 시행규칙**(142조 외 8개 후보): 전부 원문을
  읽어 확인 — 납부방법·징수·서식·견인 등 절차 조문이라 "이의제기 가능성 판단"과 무관. 추가
  불필요.
- **질서위반행위규제법**: 이 법은 원래 과태료 전반을 다루는 법이라 매칭이 ~50건 나왔는데
  (예상된 범위), 그 중 이미 참조 중인 **제7조(고의 또는 과실)와 같은 장(제2장 질서위반행위의
  성립 등)**에 속한 **제8조(위법성의 착오)·제9조(책임연령)·제10조(심신장애)**가 MG 참조
  목록에서 빠져있었다.

| 조문 | 내용 | 변경 전 |
|---|---|---|
| 제7조 | 고의·과실 없으면 과태료 부과 안 함 | ✅ 이미 참조 |
| **제8조** | 위법한 줄 몰랐고 정당한 이유가 있었으면 과태료 부과 안 함 | ❌ 누락 |
| **제9조** | 14세 미만은 과태료 부과 안 함 | ❌ 누락 |
| **제10조** | 심신장애로 옳고 그름 판단 불가능했으면 과태료 부과 안 함(②항: 미약하면 감경) | ❌ 누락 |

특히 8조가 눈에 띄었다 — `guide.py`의 예시 사유 자체가 `"표지판이 나뭇가지에 가려져 안
보였습니다"`(=몰랐다는 취지)인데, 이건 7조(고의·과실 없음)보다 **8조(위법성의 착오, "오인에
정당한 이유")가 더 정확히 들어맞는 근거**다. 지금까지 MG는 이 사유를 판단할 때 8조 원문 자체를
LLM에게 한 번도 보여준 적이 없었다.

## 3. 무엇을 고쳤나

### `ai/agents/appeal_decision_flow/law_refs.py`

- 하드코딩 폴백 상수 3개 추가 (법령DB 실원문 기반, 실측 검증):
  `_FALLBACK_ARTICLE_8_TEXT`, `_FALLBACK_ARTICLE_9_TEXT`, `_FALLBACK_ARTICLE_10_TEXT`
- `get_merit_context()`의 `parts` 목록에 8·9·10조를 7조 바로 뒤에 추가 — 142조/160조처럼
  위반유형·notice_stage 무관하게 항상 공통 주입.
- 관련 주석·docstring 갱신 (발견 경위와 이 문서 링크 포함).

**변경 후 최종 매핑**:
```
사전통지   → 160조4항1호 + 142조 + 제7~10조
1차 고지서 → 160조4항1호 + 142조 + 제7~10조 + 제14조
```

### `test/unit/test_appeal_decision_flow_nodes.py`

`TestLawRefs`의 두 컨텍스트 조립 테스트(`test_사전통지_컨텍스트_위반유형무관_공통조문`,
`test_1차고지서_컨텍스트_위반유형무관_공통조문`)에 8·9·10조 포함 여부 assertion 추가.

## 4. 검증

- `test/unit` + `test/integration` 108개 전부 통과 (라이브 DB 연결 상태에서 실행).
- 실제 `get_merit_context("1차 고지서")` 호출 결과를 직접 덤프해서 7·8·9·10·14조 원문이
  법령명 라벨과 함께 순서대로 전부 들어가는 것을 육안으로 확인.

## 5. 남은 과제 (오늘 안 건드림)

- `docs/architecture/appeal-judgment/02_데이터모델_설계서.md` §5 매핑표, `01_아키텍처_설계서.md`
  §9-2 등 설계 문서에는 아직 8·9·10조가 반영 안 됨 — 필요시 별도로 갱신.
- `etl/legal/extract_extra_relations.py` → `law_extra_relations.jsonl` → `export_neo4j.py` 연결이
  끊겨 있는 문제는 오늘 건드리지 않음. 이게 연결되면 향후 "관련 조문 자동 탐색"을 그래프 순회로
  할 수 있게 된다.
