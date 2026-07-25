# Vision Qwen 1,200건 최종 결과와 Supervisor handoff

## 결론

- 4개 카테고리, 카테고리당 300건의 32프레임 Qwen 분석이 모두 완료됐다.
- model schema-valid는 651/1,200건(54.25%)이다.
- 실패 결과도 `partial`과 `requires_review`로 보존되므로 처리 완료 건수와 model-valid 건수를 구분한다.
- Qwen은 현재 GPU에서 운영 가능한 VLM이다. LLaVA는 48GB급 CUDA OOM으로 usable pilot 결과가 없어 의미 품질 비교는 보류한다.
- Supervisor handoff v1 계약, 상태값, 안정된 Qwen 오류 코드, 계약 테스트와 실제 VideoMAE+YOLO handoff 생성 E2E를 확인했다.

## 카테고리별 최종 결과

| 카테고리 | 처리 | model-valid | invalid | valid 비율 |
|---|---:|---:|---:|---:|
| car_vs_car | 300 | 197 | 103 | 65.67% |
| car_vs_pedestrian | 300 | 155 | 145 | 51.67% |
| car_vs_motorcycle | 300 | 149 | 151 | 49.67% |
| car_vs_bicycle | 300 | 150 | 150 | 50.00% |
| 합계 | 1,200 | 651 | 549 | 54.25% |

## JSON 실패 원인

상위 분류는 `schema_invalid` 300건, `json_incomplete` 249건이다.

| 세부 오류 | 건수 |
|---|---:|
| schema_invalid:missing:accident_situation | 202 |
| json_incomplete:Unterminated string starting at | 86 |
| json_incomplete:Expecting ',' delimiter | 82 |
| schema_invalid:missing:scene_conditions.evidence | 74 |
| json_incomplete:Expecting value | 52 |
| json_incomplete:Expecting property name enclosed in double quotes | 29 |
| schema_invalid:enum:bbox_helpfulness | 14 |
| schema_invalid:enum:predicted_accident_target | 10 |

## 처리시간과 GPU

| 카테고리 | 총 실행시간 | 영상당 |
|---|---:|---:|
| car_vs_pedestrian | 5시간 49분 25초 | 69.88초 |
| car_vs_motorcycle | 6시간 4분 48초 | 72.96초 |
| car_vs_bicycle | 4시간 48분 34초 | 57.71초 |

- 위 900건 가중 평균은 영상당 66.85초다.
- car_vs_car는 이전 재실행 로그에 시작·종료 시각이 없어 동일 기준 계산에서 제외했다.
- 실행 중 관찰된 GPU 메모리는 약 12.5~19.5GiB였고 관찰 최대치는 19,532MiB였다.
- 완료 후 GPU는 14MiB, 사용률 0%로 해제됐다.

## 영어 출력 안정성

- 1,200개 raw output 중 한글 포함 출력은 1건, 기타 비영문·비한글 문자는 0건이었다.
- schema-valid 651건 중 영어-only 출력은 650건(99.85%)이다.
- 현재 validator는 영문과 한글을 허용한다. 운영 계약을 영어-only로 고정한다면 남은 한글 1건을 language-invalid로 분류하도록 후속 변경한다.

## 재개와 재시도 계약

- 한 영상은 최초 시도와 오류별 adaptive retry를 합쳐 최대 2회 생성한다.
- JSON 불완전 재시도는 `max_new_tokens=1024`, 나머지는 512를 사용한다.
- 결과가 저장된 영상은 valid/invalid와 관계없이 일반 재실행에서 건너뛴다.
- `--pilot-qwen-invalid N`을 명시한 경우에만 기존 invalid 중 N건을 다시 분석한다.
- 실행 완료는 32프레임 결과가 저장된 고유 asset 300건으로 판단한다.
- model-valid는 실행 완료와 분리된 품질 지표다.

## Supervisor handoff 계약

- schema version: `vision-supervisor-handoff-v1`
- 허용 상태: `complete`, `partial`, `failed`
- 기존 Vision 상태 `success`는 handoff에서 `complete`로 변환한다.

상태 예시:

```json
{"schema_version":"vision-supervisor-handoff-v1","status":"complete","model_analysis":{"qwen":{"valid":true,"requires_review":false,"error_code":null}}}
```

```json
{"schema_version":"vision-supervisor-handoff-v1","status":"partial","model_analysis":{"qwen":{"valid":false,"requires_review":true,"error_code":"vision_qwen_json_incomplete"}}}
```

```json
{"schema_version":"vision-supervisor-handoff-v1","status":"failed","model_analysis":{"qwen":{"valid":false,"requires_review":true,"error_code":"vision_qwen_unavailable"}}}
```

안정된 Qwen 오류 코드:

- `vision_qwen_input_contract`
- `vision_qwen_json_incomplete`
- `vision_qwen_schema_invalid`
- `vision_qwen_language_invalid`
- `vision_qwen_unavailable`
- `vision_qwen_skipped`

## 검증

- 로컬 계약·JSON·입력·runner 테스트: 29 passed, 상태 subtest 4 passed
- RunPod 서비스 파일 문법 검사 통과
- 로컬과 RunPod 서비스 코드 SHA-256 일치
- 실제 RunPod VideoMAE+YOLO Supervisor handoff E2E 통과
  - 입력: `aihub_train_00003498_bb_3_150717_bike_38_014.mp4`
  - key frames: 32
  - handoff status: `partial`
  - Qwen: `vision_qwen_skipped`
  - 출력: `/workspace/SKN27-FINAL-3Team/storage/vision/outputs/supervisor_handoff/vision_supervisor_handoff_aihub_train_00003498_bb_3_150717_bike_38_014.json`

직접 파일 실행은 프로젝트 import 경로를 잃으므로 다음 패키지 실행 방식을 사용한다.

```bash
python -m ai.vision.run_to_supervisor INPUT.mp4 --checkpoint CHECKPOINT_DIR
```

## 다음 분석 고도화

1. 202건의 `missing:accident_situation`을 우선 개선한다.
2. incomplete 249건은 출력 길이와 중단 위치를 분석해 프롬프트 길이·생성 토큰을 조정한다.
3. model-valid 651건에서 카테고리별 내용 정확도 표본 검수를 수행한다.
4. YOLO bbox·객체 메타데이터 제공 전후의 동일 영상 비교를 수행한다.
5. VideoMAE의 카테고리별 precision/recall/F1, macro F1, confusion matrix, confidence 분포와 review threshold를 확정한다.
6. 실제 Django/Worker/Supervisor 원격 호출·polling·idempotency E2E는 통합 단계에서 수행한다.
