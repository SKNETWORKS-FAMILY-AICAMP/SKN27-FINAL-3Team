# Roundabout preprocessing patch notes

## 적용 범위

대상 폴더: `fault_standard/preprocessing/roundabout`

이번 수정은 2025 2차로형 회전교차로 전처리에서 발견된 하드코딩성 추론과 Neo4j 적재 전 보정 포인트를 반영한 패치입니다.

## 주요 수정사항

1. `extractors.py`
   - 회전번호/색상별 강제 보정 함수 제거
   - `extract_direction()`을 keyword 문맥 기반으로 변경
     - `진입`: 선진입/후진입/진입 주변 방향만 인정
     - `진출`: 진출 주변 방향만 인정
     - 직진/회전 방향을 `exit_direction`으로 확정하지 않음
   - `infer_role()`에서 `round_no == 1/2/3` 및 색상 기반 분기 제거
     - rule title과 action의 원문 신호로 역할 추정
   - `infer_expected_path()`에서 3시/9시/12시 방향별 정상 차로 고정 로직 제거
     - 원문에 명시된 lane path만 반환
     - 노면표시 적합성은 `unknown`으로 남김
   - `infer_conflict_lane()` / `infer_conflict_direction()`의 회전번호별 고정값 제거
     - 충돌/사고/진입부/진출부 문맥과 party exit/lane-change 정보만 사용
     - derived source/confidence 필드 추가
   - `LaneStep` 구조 추출 추가
     - `red_lane_steps`, `blue_lane_steps` 생성
     - 각 step은 `seq`, `movement`, `lane`, `direction`, `source`를 가짐
   - 판례 과실비율 파서 보강
     - `10:02`, `15:00` 같은 시간값 제외
     - `%`는 주변에 과실/비율/책임/부담 문맥이 있을 때만 인정

2. `builder.py`
   - `lane_steps.jsonl` 테이블 생성 추가
   - `cleaning_quality`의 고정 True 값을 실제 텍스트 검증값으로 변경
   - action이 끊긴 경우 `dangling_action_suffix` flag 추가
   - conflict lane/direction이 추론값이면 `conflict_*_derived` flag 기록

3. `classifiers.py`
   - 정상 우회전/직진/좌회전 차로를 코드에서 고정하지 않도록 변경
   - 방향별 정상 차로는 문서/도표/수동 태그에서 확인해야 하므로 `None`과 source 필드로 남김

## 남겨둔 값

- `EXPECTED_RULE_COUNT = 15`, `ROUND_NO_MIN/MAX`, `ROUND_GROUP_RANGES`는 문서 구조 검증용 설정값이라 `config.py`에 유지했습니다.
- 이미지 crop/diagram bbox 자동화는 이번 패치 범위가 아닙니다.
- `path_matches_marking`은 하드코딩하지 않고 `unknown`으로 유지합니다.

## 생성되는 추가 산출물

- `99_tables_for_db/lane_steps.jsonl`

Neo4j 적재 시 `lane_paths.jsonl`의 문자열 path만 쓰기보다 `lane_steps.jsonl`을 함께 사용하면 됩니다.
