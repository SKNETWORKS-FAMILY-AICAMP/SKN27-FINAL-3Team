# 사고 핵심 사실 규칙

| 입력 예시 | 의미 분류 | schema.field | 정규화 값 | 처리 | 금지 조건 | rule_id |
|---|---|---|---|---|---|---|
| 교차로, 사거리 | entity | accident_fact.road_layout | intersection | 자동 | 도로 형태를 부정하거나 모른다고 한 경우 | `accident.road_layout.intersection.exact_01` |

사고 규칙은 도로 형태, 양 차량 행동, 신호 우선권, 충돌 위치만 다룬다.
