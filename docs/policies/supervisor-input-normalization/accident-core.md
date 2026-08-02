# 사고 핵심 사실 규칙

| 입력 예시 | 의미 분류 | schema.field | 정규화 값 | 처리 | 금지 조건 | rule_id |
|---|---|---|---|---|---|---|
| 교차로, 사거리 | entity | accident_fact.road_layout | intersection | 자동 | 도로 형태를 부정하거나 모른다고 한 경우 | `accident.road_layout.intersection.exact_01` |
| 제가 직진, 본인 차량 직진 | action | accident_fact.vehicle_actions.self | straight | 자동 | 주체가 본인 차량인지 불명확한 경우 | `accident.vehicle_actions.self.straight.exact_01` |
| 상대 차량 좌회전, 상대 차량은 좌해전 | action | accident_fact.vehicle_actions.other | left_turn | 자동 | 주체가 상대 차량인지 불명확한 경우 | `accident.vehicle_actions.other.left_turn.typo_01` |
| 상대 차량 우회전 | action | accident_fact.vehicle_actions.other | right_turn | 자동 | 주체가 상대 차량인지 불명확한 경우 | `accident.vehicle_actions.other.right_turn.exact_01` |
| 후방 추돌, 뒤에서 추돌 | entity | accident_fact.collision_location | rear_end | 자동 | 충돌 위치를 부정하거나 모른다고 한 경우 | `accident.collision_location.rear_end.exact_01` |
| 제 신호는 녹색 | state | accident_fact.signal_priority | self_green_signal | 자동 | 신호를 부정하거나 모른다고 한 경우 | `accident.signal_priority.self_green_signal.exact_01` |
| 상대 차량 좌회전 신호 | state | accident_fact.signal_priority | other_left_turn_signal | 자동 | 상대 신호가 불명확한 경우 | `accident.signal_priority.other_left_turn_signal.exact_01` |

사고 규칙은 도로 형태, 양 차량 행동, 신호 우선권, 충돌 위치만 다룬다.
