# V6 G1 입력 고정 보고서

## 결과

기준 질문 50개와 기존 Supervisor 시뮬레이션 Facts 50개를 V6 입력 전용 산출물로 고정했다.
이 스크립트는 qrels·정답지·Rule ID·비율·PDF 정답 페이지를 읽지 않는다.
따라서 뒤의 PDF Gold 라벨 단계가 입력을 보고 정답에 맞게 보정하는 누출을 막는다.

| 항목 | 값 |
|---|---:|
| 질문 수 | 50 |
| Supervisor 응답 수 | 50 |
| 완료 Facts 수 | 50 |
| 입력 SHA-256 | `6c5dabf0284ea25801baa4152e2e9da5ee475d16ce92b3ee89961e37e90ddb4b` |
| 미확정 Fact가 있는 조건 키 수 | 8 |

## 다음 G1-LABEL 규칙

1. PDF 원문에서 Rule과 Party A/B 매핑을 독립적으로 확인한다.
2. 기본비율·Variant·수정요소·최종비율을 Calculator로 재계산한다.
3. Facts가 UNKNOWN이면 숫자를 임의로 만들지 않고 `needs_fact` 또는 `not_calculable`로 기록한다.
4. FULL-50 Gold가 불가능한 Case는 Rule 부재/근거 충돌로 분류하고 사용자 승인 없이는 대체하지 않는다.

## 미확정 Fact 분포

| Fact key | UNKNOWN 건수 |
|---|---:|
| `explicit_conditions.reasonless_sudden_stop` | 49 |
| `opponent.signal_state` | 30 |
| `user.signal_state` | 31 |
| `v3_extensions.pedestrian.signal_state` | 3 |
| `v4_extensions.environment.bicycle_facility_type` | 49 |
| `v4_extensions.environment.crossing_road_width` | 45 |
| `v4_extensions.environment.crosswalk_context` | 49 |
| `v4_extensions.environment.u_turn_control` | 50 |
