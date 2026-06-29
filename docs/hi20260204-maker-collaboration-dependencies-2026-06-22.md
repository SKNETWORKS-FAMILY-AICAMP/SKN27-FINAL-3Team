# hi20260204-maker 협업 의존성 상세 보고서

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-22 |
| 기준일 | 2026-06-22 월요일 KST |
| 이번 주 금요일 | 2026-06-26 |
| 담당 계정 | `hi20260204-maker` |
| 목적 | `hi20260204-maker`가 진행해야 하는 협업 작업에서 선수 담당자, 선수 과정, 받아야 하는 데이터, 지연 시 영향, PM 후속 조치를 상세히 정리한다. |

## 1. 협업 핵심 결론

이번 주 협업의 중심은 `#22`, `#27`, `#29`, `#40`, `#41`이다.

`hi20260204-maker`가 혼자 확정할 수 있는 것은 공통 문서 구조와 PM 초안뿐이다. 실제 close 가능한 수준의 완료를 만들려면 필주, 동혁, 재강, 주희의 schema, metadata, sample, 검증 기준이 먼저 필요하다.

## 2. 담당자별 받아야 하는 산출물

| 담당자 | 선수 과정 | 받아야 하는 데이터 | PM이 반영할 이슈 | 지연 시 영향 |
|---|---|---|---|---|
| 필주 `workzion2` | 고지서 OCR output schema, 감경 판단 schema, 샘플 검증 계획 작성 | `OCRResult`, `notice_stage`, `law_code`, `violation_text`, `ocr_status`, `missing_fields`, `reduction_eligible`, `reduction_rate`, `special_reduction`, `objection_possible`, `missing_documents`, `limitations` | `#22`, `#23`, `#24`, `#25`, `#26`, `#27`, `#29`, `#40` | 과태료·범칙금 흐름, 이의신청서 생성, 통합 시나리오 `INT-001`, `INT-002`, `INT-005` 확정 불가 |
| 동혁 `techshin31` | 법률 데이터 수집, 전처리, chunking, metadata schema 작성 | 법령 source 목록, `law_name`, `article`, `paragraph`, `item`, `effective_date`, `retrieved_at`, `jurisdiction`, `source_reference`, chunk ID, 검색 query 예시, 최신성 표시 기준 | `#20`, `#22`, `#26`, `#27`, `#29`, `#40`, `#41` | 법률 근거 검색, 이의신청서 근거, 법률 guardrail, `INT-006` 확정 불가 |
| 재강 `leejaegang27` | 사고 설명/경위서 OCR, 판례/자막/심의사례 전처리, evidence schema 작성 | 사고 설명 input/output, `processed_sim` 정의, 파일/컬럼 정의, `case_search_text` 필요성 판단, chunk 범위, `reliability_score`, source별 evidence schema, 단정 방지 표현 기준 | `#21`, `#30`, `#31`, `#32`, `#33`, `#22`, `#29`, `#40`, `#41` | 과실비율 흐름, 유사 사례 근거, `INT-003`, 영상 결과 병합 흐름 확정 불가 |
| 주희 `ohjuheecode` | 영상/이미지 데이터 manifest, 모델 후보, Vision output schema 작성 | 데이터셋 후보, 다운로드 상태, 샘플 확보 여부, manifest 필드, 주 모델/비교 모델 후보, `key_frames`, `scene_summary`, `detected_objects`, `confidence_label`, `quality_issues`, `privacy_redaction` | `#36`, `#37`, `#38`, `#39`, `#22`, `#29`, `#40`, `#41` | 영상/이미지 분석 흐름, 개인정보 마스킹, `INT-004` 확정 불가 |

## 3. 이슈별 협업 의존성

### 3.1 `#22 feat-agent-result-schema-and-rag-contract`

| 구분 | 내용 |
|---|---|
| PM 역할 | 공통 결과 envelope과 evidence metadata를 병합한다. |
| 선수 담당 | 필주, 동혁, 재강, 주희 |
| 선수 과정 | 각 담당자가 자기 노드의 `structured_result`, evidence metadata, limitations를 제시해야 한다. |
| 받아야 하는 데이터 | 필주 OCR/감경 schema, 동혁 법률 metadata, 재강 판례/사례 evidence schema, 주희 Vision result schema |
| PM 산출물 | 공통 필드 `node_name`, `node_code`, `status`, `summary`, `structured_result`, `evidence`, `next_actions`, `limitations`와 source type별 metadata 표 |
| 완료 가능 조건 | 모든 노드의 최소 input/output과 `structured_result` 초안이 한 문서에 병합됨 |
| 현재 판정 | 협업 입력 대기. PM 초안만으로 close 불가 |

### 3.2 `#29 feat-supervisor-chatbot-routing`

| 구분 | 내용 |
|---|---|
| PM 역할 | 사용자 입력 유형별 호출 노드와 순서를 정리한다. |
| 선수 담당 | 필주, 동혁, 재강, 주희 |
| 선수 과정 | `#22` 공통 schema와 각 노드 input/output이 먼저 나와야 한다. |
| 받아야 하는 데이터 | 고지서/OCR 필수 필드, 법률 검색 query 형식, 사고 설명 필드, 영상/이미지 결과 필드 |
| PM 산출물 | 고지서/OCR, 법령 질문, 사고 설명, 이미지/영상, 이의신청서 요청별 routing rule |
| 중요한 결정 | 고지서 흐름에서는 법률 근거를 항상 호출하고, `law_code`가 있으면 exact 입력, 없으면 `violation_text` semantic 입력으로 분기한다. |
| 완료 가능 조건 | 입력 유형별 호출 노드, 추가 질문 조건, `partial`/`failed` 병합 규칙이 확정됨 |
| 현재 판정 | `#22`와 담당자 schema 없이는 close 불가 |

### 3.3 `#27 feat-objection-draft-report-node`

| 구분 | 내용 |
|---|---|
| PM 역할 | 이의신청서 생성 노드의 입력 조건, 출력 구조, 부족 시 추가 질문 조건, 면책 문구를 정리한다. |
| 선수 담당 | 필주, 동혁 |
| 선수 이슈 | `#23`, `#24`, `#25`, `#26`, `#22` |
| 받아야 하는 데이터 | 필주 분석 패키지, 감경 판단, 이의신청 가능성, 부족 서류, 필요 증거, 동혁 법률 metadata |
| PM 산출물 | `notice_analysis_result`, `law_ground_result`, `user_facts`, `additional_explanation`, `attachments` input 계약과 `recipient_agency`, `case_summary`, `grounds`, `disclaimer` output 계약 |
| 완료 가능 조건 | 필주 분석 결과와 동혁 법률 근거가 실제로 초안 생성 input으로 연결됨 |
| 현재 판정 | 선수 산출물 대기. close 불가 |

### 3.4 `#40 test-cross-mvp-integration-scenarios`

| 구분 | 내용 |
|---|---|
| PM 역할 | Cross-MVP 통합 시나리오와 검증 상태를 관리한다. |
| 선수 담당 | 전원 |
| 받아야 하는 데이터 | 고지서 샘플, OCR 텍스트 샘플, 사고 설명 샘플, 영상/이미지 샘플, 법률 검색 샘플, 각 노드 sample output |
| PM 산출물 | `INT-001`~`INT-006` 입력, 호출 노드, 기대 출력, 실제 결과, 상태, 남은 리스크 표 |
| 완료 가능 조건 | 최소 1개 이상의 중간 발표 MVP 흐름이 샘플 기준으로 끝까지 연결됨 |
| 현재 판정 | 시나리오 정의는 가능하나 실행 검증 전이라 close 불가 |

### 3.5 `#41 test-legal-ai-guardrail-validation`

| 구분 | 내용 |
|---|---|
| PM 역할 | 금지 표현, 면책 문구, evidence/limitations 표시 기준을 만든다. |
| 선수 담당 | 전원 |
| 받아야 하는 데이터 | 각 노드 summary, limitations, confidence, evidence sample, 사용자 노출 문구 |
| PM 산출물 | 법률 단정 금지, 성공 보장 금지, 과실비율 수치 단정 금지, 개인정보 노출 금지 체크리스트 |
| 완료 가능 조건 | 실제 Agent 또는 Supervisor sample output을 기준으로 guardrail 검증이 수행됨 |
| 현재 판정 | 기준 초안만 가능. close 불가 |

## 4. 시나리오별 필요한 협업 데이터

| Scenario | 사용자 흐름 | 필요한 선수 데이터 | 선수 담당 |
|---|---|---|---|
| `INT-001` | 고지서 업로드 후 분석 결과 | 고지서 샘플, OCR output schema, 감경 판단 schema, 법률 검색 입력 방식 | 필주, 동혁 |
| `INT-002` | OCR 텍스트 붙여넣기 후 부족 필드 보완 | 필수 필드 목록, `missing_fields`, 추가 질문 조건 | 필주 |
| `INT-003` | 사고 설명 입력 후 과실비율 분석 | 사고 설명 schema, 판례/자막/심의사례 chunk, reliability score | 재강 |
| `INT-004` | 블랙박스 영상 업로드 후 사고 분석 | 영상/이미지 샘플, key frame, scene summary, confidence, privacy redaction | 주희, 재강 |
| `INT-005` | 과태료 결과 확인 후 이의신청서 초안 요청 | 고지서 분석 패키지, 법률 근거, 사용자 사실관계, 필요 증거 | 필주, 동혁, PM |
| `INT-006` | 법령 근거만 질문 | 법률 source, chunking, metadata, 검색 결과 sample | 동혁 |

## 5. 2026-06-26까지 협업 일정

| 날짜 | 받아야 하는 것 | PM 후속 조치 |
|---|---|---|
| 2026-06-23 12:00 | 주희 sequence diagram 초안, 재강 저장 구조 초안, 필주 OCR/감경 schema 초안, 동혁 chunking 이슈 원인 정리 | 누락 항목을 `#13`에 리스크로 등록 |
| 2026-06-23 23:59 | 담당자별 schema, manifest, 구현계획서, evidence score 기준 | `#22` 병합 초안 작성 |
| 2026-06-24 23:59 | PM이 병합한 `#22`, `#29`, `#27` 초안에 대한 담당자 확인 | 확정 가능 항목과 `검증 필요` 항목 분리 |
| 2026-06-25 23:59 | 샘플 확보 여부와 sample output | `#40` 시나리오 상태 갱신 |
| 2026-06-26 23:59 | close 후보와 보류 사유 | `#12` 조건부 close 여부 보고, 나머지 보류 사유 보고 |

## 6. 담당자에게 요청할 comment 템플릿

```markdown
### 2026-06-22 회의 반영 산출물

- 현재 완료된 것:
- 아직 미완료인 것:
- PM에게 넘길 schema 또는 데이터:
- sample 또는 manifest 위치:
- 연결 이슈:
- 검증 필요 항목:
- 2026-06-26까지 완료 가능한 범위:
```

## 7. PM이 확정하면 안 되는 항목

- 실제 LangGraph 사용 여부
- API endpoint 최종 명세
- Agent 식별 코드값 최종 enum
- OCR, ML, DL 모델 최종 선택
- 고지서, 사고 설명, 영상/이미지 샘플 검증 결과
- 법률 판단, 이의신청 성공 가능성, 과실비율 수치
- 개인정보 보관/삭제 운영 정책

위 항목은 담당자 산출물과 추가 회의 결과를 받은 뒤 `확정`, `검증 필요`, `보류` 중 하나로 다시 분류한다.

## 8. 협업 리스크

| 리스크 | 영향 | 대응 |
|---|---|---|
| 필주 OCR schema 지연 | 이의신청서 생성과 과태료 통합 시나리오 지연 | `#27`, `#40`을 `검증 필요`로 유지 |
| 동혁 법률 metadata 지연 | 법률 근거 검색과 guardrail 검증 지연 | `#22`, `#41`에 법률 metadata 미수신 표시 |
| 재강 evidence score 미정 | 과실비율 결과가 단정처럼 보일 위험 | 정성 라벨과 한계 문구만 사용 |
| 주희 샘플 영상 미확보 | `INT-004` 실행 불가 | 영상 시나리오는 설계 검증 상태로 유지 |
| Project 상태 미갱신 | 실제 진행 상황과 보드 상태 불일치 | PM 확인 후 Status/start/fin 갱신 |
