# Neo4j C-2 관계 강화 실험 보고서

## 결론

- B 대비 C-2의 선택/순위가 바뀐 문항은 0건이다.
- 그래프 eligible subset은 4건이므로, 이 subset의 결과를 전역 일반화 근거로 사용하지 않는다.
- C-2는 PDF가 직접 구조화한 LanePath·LaneStep·Signal 관계만 사용했다. 충돌 관계·우선순위 관계를 추정해 추가하지 않았다.

## 전역 결과

- B Hit@3 / E2E: 21/30 (70.0%) / 8/30 (26.7%)
- C-1 Hit@3 / E2E: 21/30 (70.0%) / 8/30 (26.7%)
- C-2 Hit@3 / E2E: 21/30 (70.0%) / 8/30 (26.7%)

## Graph-eligible subset

- 대상: fault_complete30_q09, fault_complete30_q25, fault_complete30_q26, fault_complete30_q27
- B Hit@3: 4/4 (100.0%)
- C-2 Hit@3: 4/4 (100.0%)

## 해석 규칙

- C-2가 B보다 같거나 낮으면 Neo4j 자체의 실패가 아니라, 현재 질문 Fact와 PDF 구조화 관계가 차별화에 충분했는지로 해석한다.
- 다음 확장은 PDF 근거가 명확한 collision phase·진입 선후행·출차 순서 관계를 추가 구조화한 뒤, graph-eligible 표본을 늘려 재측정하는 것이다.
