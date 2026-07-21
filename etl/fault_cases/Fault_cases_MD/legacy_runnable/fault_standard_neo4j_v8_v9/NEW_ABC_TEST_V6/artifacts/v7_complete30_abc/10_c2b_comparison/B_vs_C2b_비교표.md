# B / C-2b 비교표

> C-2b는 V9 Neo4j의 RuleGroup·Party·LanePath·LaneStep/NEXT_STEP·선후진입·Context·Variant·Adjustment/BaseFault 경로를 탐색한다. 공통차로는 충돌 사실로 쓰지 않는다.

| 지표 | B PostgreSQL | C-2b 전체 관계 Neo4j |
|---|---:|---:|
| Hit@1 | 11/30 (36.7%) | 11/30 (36.7%) |
| Hit@3 | 21/30 (70.0%) | 21/30 (70.0%) |
| MRR@3 | 0.5056 | 0.5056 |
| nDCG@3 | 0.5552 | 0.5552 |
| Hit@10 | 24/30 (80.0%) | 24/30 (80.0%) |
| Recall@50 | 28/30 (93.3%) | 28/30 (93.3%) |
| Exact Rule@1 | 11/30 (36.7%) | 11/30 (36.7%) |
| Final Ratio Exact | 9/30 (30.0%) | 9/30 (30.0%) |
| End-to-End Exact | 8/30 (26.7%) | 8/30 (26.7%) |
| Calculation Coverage | 20/30 (66.7%) | 19/30 (63.3%) |

Graph-eligible: 4/30 (fault_complete30_q09, fault_complete30_q25, fault_complete30_q26, fault_complete30_q27).
선택/정답순위가 바뀐 B→C-2b case: 0건.
