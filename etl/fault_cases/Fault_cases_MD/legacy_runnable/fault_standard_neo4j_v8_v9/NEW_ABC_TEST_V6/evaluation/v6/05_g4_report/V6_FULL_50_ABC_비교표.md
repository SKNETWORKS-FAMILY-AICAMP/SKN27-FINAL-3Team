# V6 FULL-50 인정기준 A/B/C 비교표

## 실험 계약

- 입력: 같은 기준 질문 50개 + 고정된 Supervisor Facts 50개
- 검색: 고정 Qwen 4B 2,560차원 exact cosine Top-50
- B/C: 같은 Top-50에 `MATCH → UNKNOWN → UNMODELED → MISMATCH` 조건 버킷만 적용; 가중치·boost 없음
- 계산: 세 방법 모두 같은 base-only Calculator. Variant/수정요소를 확정하지 못하면 숫자를 만들지 않음
- 실행: PostgreSQL 55433 / Neo4j 17688 실험 컨테이너에서 3회 반복. 운영 `skn27-*` DB는 미접속

## 분모

- 전체 입력: **50**
- Exact Rule Gold: **39** (`relevance=2`만 허용)
- 정확 비율 Gold: **33**
- 추가 사실 없이는 Exact Rule/비율을 정할 수 없는 안전성 Case: **11**

## 검색·재정렬 수치 비교

| 지표 | A: pgvector | B: pgvector + PostgreSQL | C: pgvector + Neo4j |
|---|---:|---:|---:|
| Recall@K는 전체 50개를 분모로, nDCG@K는 positive qrels 49개를 분모로 계산한다. | | | |
| Recall@1 (전체 50) | 6/50 (12.0%) | 12/50 (24.0%) | 12/50 (24.0%) |
| Recall@3 (전체 50) | 17/50 (34.0%) | 23/50 (46.0%) | 23/50 (46.0%) |
| Recall@5 (전체 50) | 21/50 (42.0%) | 28/50 (56.0%) | 28/50 (56.0%) |
| Recall@10 (전체 50) | 28/50 (56.0%) | 34/50 (68.0%) | 34/50 (68.0%) |
| Recall@50 (전체 50) | 44/50 (88.0%) | 44/50 (88.0%) | 44/50 (88.0%) |
| MRR@1 (전체 50) | 0.1200 | 0.2400 | 0.2400 |
| MRR@3 (전체 50) | 0.2300 | 0.3367 | 0.3367 |
| MRR@5 (전체 50) | 0.2500 | 0.3597 | 0.3597 |
| MRR@10 (전체 50) | 0.2702 | 0.3765 | 0.3765 |
| MRR@50 (전체 50) | 0.2830 | 0.3841 | 0.3841 |
| nDCG@1 (positive qrels 49) | 0.1224 | 0.2313 | 0.2313 |
| nDCG@3 (positive qrels 49) | 0.2217 | 0.3010 | 0.3010 |
| nDCG@5 (positive qrels 49) | 0.2559 | 0.3416 | 0.3416 |
| nDCG@10 (positive qrels 49) | 0.3050 | 0.3916 | 0.3916 |
| nDCG@50 (positive qrels 49) | 0.3915 | 0.4531 | 0.4531 |
| Top-1 Exact Rule (Exact Gold 39) | 5/39 (12.8%) | 7/39 (17.9%) | 7/39 (17.9%) |
| Resolver가 확정한 Exact Rule (비율 Gold 33) | 4/33 (12.1%) | 3/33 (9.1%) | 3/33 (9.1%) |
| 숫자 출력 coverage (비율 Gold 33) | 4/33 (12.1%) | 7/33 (21.2%) | 7/33 (21.2%) |
| End-to-end 정확 비율 (비율 Gold 33) | 2/33 (6.1%) | 3/33 (9.1%) | 3/33 (9.1%) |
| 구조 조회 latency p50 / p95 | - | 36.12 / 51.52 ms | 76.59 / 94.20 ms |

## 실행 무결성

- 3회 결과 byte-identical: A=True, B=True, C=True
- B/C semantic parity: **True**
- 상태: A={'matched': 4, 'top1_ambiguous_party': 9, 'top1_mismatch': 36, 'top1_unknown': 1}; B={'ambiguous_rule': 11, 'matched': 11, 'no_match': 16, 'requires_fact': 12}; C={'ambiguous_rule': 11, 'matched': 11, 'no_match': 16, 'requires_fact': 12}

## 판정

B/C는 A보다 MRR@50·nDCG@50과 Top-1 Exact Rule이 높았고, 각각 7/33건의 숫자를 계산했다. 다만 End-to-end 정확 비율은 3/33건이므로, 이것만으로 구조 후처리 도입을 확정할 수준은 아니다.
B와 C가 동일한 것은 두 저장소에 동일 Canonical 조건을 넣고 같은 버킷 규칙을 실행했다는 parity 결과다. 이는 Neo4j가 PostgreSQL보다 정확하다는 증거도, 반대로 불필요하다는 증거도 아니다.
다음 비교의 핵심은 Rule별 PDF 조건을 공통 Fact Dictionary에 더 매핑하고, Supervisor가 그 Facts를 확정해 `UNKNOWN`과 `ambiguous_rule`을 줄이는 것이다. 그 뒤 같은 Runner와 같은 지표를 재실행한다.

## Gold 품질 공개

| Label quality | 건수 | 의미 |
|---|---:|---|
| `out_of_corpus_negative` | 1 | 정확 Rule 없음 |
| `ratio_derived_from_base_only` | 13 | 수정요소 미확정 상태의 base-only 시뮬레이션 |
| `ratio_present_legacy_label` | 26 | 기존 레저에 최종비율 존재 |
| `related_rule_only_not_gold` | 10 | 유사 Rule만 있어 Exact Gold 아님 |
