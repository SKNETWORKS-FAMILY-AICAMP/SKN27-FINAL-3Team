# V6 인정기준 A/B/C 실행 분석 보고서

## 결론

50개 입력으로 A/B/C를 실제 실행했다. B/C는 각 11건을 `matched`, 12건을 `requires_fact`, 11건을 `ambiguous_rule`로 판정했고, 7건의 base-only 숫자를 계산했다. 순위 지표는 A보다 상승했지만 정확 비율은 3/33이므로, 이 실행만으로 Neo4j 도입을 결정해서는 안 된다.

## 근거

1. A/B/C는 모두 같은 50개 후보군을 사용했고 3회 반복 결과가 동일했다.
2. B/C decision parity는 True이다. PostgreSQL과 Neo4j가 같은 조건 평가를 수행했다.
3. B/C 상태는 각각 {'ambiguous_rule': 11, 'matched': 11, 'no_match': 16, 'requires_fact': 12}이며, 계산기 숫자 출력은 각각 11건이다.
4. 현재 Gold는 Exact Rule 39건, 수치 비교 가능 33건, 추가 Facts 필요/코퍼스 부재 11건으로 분리되어 있다.

## 해석 시 금지

- `0/33`을 B/C가 틀렸다는 정확도 수치로 해석하지 않는다. 이는 Resolver가 Rule·Party mapping을 확정하지 않았기 때문에 계산을 거부한 coverage 수치다.
- relevance=1 유사 Rule을 Exact Gold 또는 비율 정답으로 승격하지 않는다.
- base-only simulation assumption을 PDF 수정요소까지 검수한 최종비율로 표현하지 않는다.

## 재실행 전 필수 보강

1. 934개 직접 조건 중 Rule 선택에 필요한 조건을 공통 Fact Dictionary의 값으로 매핑한다.
2. `unknown` 문자열을 확정값으로 취급하지 않고 Supervisor 답변에서 명시값을 받는다.
3. Variant·Adjustment 적용 여부를 별도 Facts로 받아 공통 Calculator에 전달한다.
4. 33개 비율 Gold 중 base-only 13개를 PDF 표와 수정요소 근거로 시각 검수한다.
5. 위 사항을 완료한 뒤 이 동일한 평가기를 재실행하여, 그때의 End-to-end 비율 수치를 의사결정에 사용한다.
