# 2026-06-22 월요일 인물별 액션 및 업데이트 정리

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-22 |
| 기준일 | 2026-06-22 월요일 KST |
| 기준 이슈 | `#11 docs-wbs-owner-deliverable-plan` |
| 기준 문서 | `docs/wbs-owner-deliverable-plan.md`, `docs/meeting-feedback-issue-comment-guide-2026-06-19.md`, `docs/meeting-pm-guide-2026-06-19.md`, `docs/hi20260204-maker-issue-action-detail-2026-06-19.md`, `docs/issues/40-cross-mvp-integration-scenarios.md`, `docs/superpowers/specs/2026-06-19-agent-result-schema-design.md` |
| 최신 GitHub 확인 | 2026-06-22 조회 기준, 2026-06-21 이후 관련 이슈 업데이트는 `#22`, `#26`에서 확인됨 |
| 오늘의 목적 | 2026-06-21 23:59 KST까지 올라왔어야 할 담당자별 코멘트와 산출물을 점검하고, 2026-06-22부터 시작되는 데이터·DB·RAG 계약 고정 작업의 착수 기준을 맞춘다. |

## 1. 오늘 전체 기준

2026-06-18 ~ 2026-06-21 단계는 역할/WBS/Issue 재정렬 기간이었다. 2026-06-22부터 2026-06-28까지는 다음 항목을 고정해야 한다.

| 이번 주 목표 | 필요한 산출물 |
|---|---|
| 데이터·DB·RAG 계약 고정 | 법률/과태료/과실비율/영상 데이터 schema |
| Agent 결과 계약 고정 | 공통 결과 envelope, 노드별 `structured_result`, `evidence` metadata |
| Supervisor 착수 기준 정리 | 입력 분류, 노드 호출 순서, 추가 질문 조건, 병합 규칙 |
| 샘플 기반 검증 준비 | 고지서 샘플, 사고 설명 샘플, 영상/이미지 샘플, 통합 시나리오 |
| 리스크 분리 | 확정/초안/검증 필요/보류 상태 구분 |

오늘 회의 또는 점검에서는 새 기능을 임의로 확정하지 않는다. 문서에 없는 기능, 모델, API는 `검증 필요`로 둔다.

## 2. 오늘 우선 확인해야 하는 이슈

| 우선순위 | 이슈 | 오늘 확인할 내용 | 상태 판단 |
|---:|---|---|---|
| 1 | `#22 feat-agent-result-schema-and-rag-contract` | 모든 담당자의 노드별 input/output과 `structured_result`가 들어왔는지 확인 | 2026-06-21 `techshin31` 댓글 있음. 내용은 "구성 예정" 수준이라 구체 schema 보완 필요 |
| 2 | `#26 feat-fine-law-ground-search` | 법률 근거 항상 호출 원칙과 입력 방식 분기 기준 확인 | 2026-06-22 회의 수정 기준. 호출 필요/불필요가 아니라 `law_code` exact 입력과 `violation_text` semantic 입력으로 구분 필요 |
| 3 | `#23`, `#28` | 고지서 OCR 필드와 샘플 검증 계획 확인 | 2026-06-19 이후 추가 업데이트 없음. 오늘 구체 산출물 확인 필요 |
| 4 | `#29` | Supervisor routing rule과 추가 질문 조건 확인 | 2026-06-19 이후 추가 업데이트 없음. PM이 오늘 보완 필요 |
| 5 | `#40` | Cross-MVP 통합 시나리오 상태 업데이트 | 현재 전부 `검증 필요`. 샘플 확보 여부를 오늘 반영해야 함 |
| 6 | `#13` | 미확정 항목을 리스크 로그로 분리 | 최신 코멘트 이후 리스크 상태 업데이트 필요 |

## 3. 요청자/PM `hi20260204-maker`

### 오늘 해야 할 일

| 작업 | 연결 이슈 | 오늘 업데이트할 내용 |
|---|---|---|
| 담당자 코멘트 누락 확인 | `#11` | 각 담당자가 2026-06-21 23:59 KST까지 본인 담당 이슈에 코멘트를 올렸는지 확인한다. |
| 공통 Agent 결과 schema 정리 | `#22` | `node_name`, `node_code`, `status`, `summary`, `structured_result`, `evidence`, `next_actions`, `limitations`를 공통 envelope 후보로 정리한다. |
| Supervisor routing rule 작성 | `#29` | 고지서/OCR, 법률 질문, 사고 설명, 이미지/영상, 이의신청서 요청별 호출 노드를 표로 정리한다. |
| 리스크 로그 업데이트 | `#13` | 미정 항목을 `확정`, `초안`, `검증 필요`, `보류`로 분류한다. |
| 통합 시나리오 갱신 | `#40` | `INT-001` ~ `INT-006`의 입력 샘플 확보 여부, 실행 노드, 상태를 갱신한다. |
| 화면 흐름 반영 범위 정리 | `#12` | 홈 -> 로그인 -> 챗봇 -> 결과/리포트 진입 흐름을 최소 MVP 기준으로 정리한다. |
| 이의신청서 생성 조건 정리 | `#27` | 필주 분석 패키지와 법령 근거 metadata를 받아 초안을 만들 조건, 부족 시 추가 질문 조건, 면책 문구를 정리한다. |

### 오늘 받아야 할 산출물

| 담당자 | 받아야 하는 내용 | 반영할 이슈 |
|---|---|---|
| 필주 | 고지서 OCR 필드, 분석 결과 구조, 부족 서류, 필요 증거, 법률 근거 입력 방식 분기 | `#22`, `#27`, `#29`, `#40` |
| 동혁 | 법령 원문/조문 metadata, RDB 적재 구조, 최신성 표시 기준 | `#20`, `#22` |
| 재강 | 과실비율 텍스트 ML/판례·사례 검색 결과 schema, 단정 방지 기준 | `#22`, `#29`, `#40` |
| 주희 | 영상·이미지 분석 결과 schema, key frame, 장면 요약, confidence | `#22`, `#29`, `#40` |

### 오늘 완료 기준

- `#22`에서 공통 필드와 노드별 `structured_result` 초안이 확인되어야 한다.
- `#29`에서 입력 유형별 호출 노드와 추가 질문 조건이 표로 정리되어야 한다.
- `#13`에서 미확정 항목이 확정처럼 기록되지 않아야 한다.
- `#40`에서 최소 3개 이상의 MVP 통합 시나리오에 입력, 호출 노드, 기대 출력, 상태, 리스크가 있어야 한다.

## 4. 필주 `workzion2`

### 담당 범위

고지서 OCR, 과태료·범칙금·벌칙 분석용 룰/매핑 데이터, 과태료·범칙금 분석 흐름.

### 오늘까지 업데이트해야 하는 이슈

| 이슈 | 오늘 업데이트할 내용 | PM 확인 포인트 |
|---|---|---|
| `#23 feat-fine-notice-ocr-intake-flow` | 고지서 OCR input/output 필드, 필수 필드, 누락 필드, OCR 실패/부분 인식 시 재업로드·수동 입력·추가 질문 흐름 | `structured_result.notice_fields`, `ocr_status`, `missing_fields`가 `#22`와 연결되는지 |
| `#24 feat-fine-penalty-rule-mapping` | 과태료·범칙금·벌칙 분석용 룰/매핑 데이터 범위 | 감경 판단 output schema와 `FINE_RULES` 적용 기준이 분리되어 있는지 |
| `#25 feat-fine-analysis-detail-view` | 처분 단계, 이의제기 가능성, 부족 서류, 필요 증거 표시 구조 | 결과 화면과 `#12` 화면 흐름에 연결 가능한지 |
| `#26 feat-fine-law-ground-search` | 법률 근거 항상 호출 원칙, `law_code` exact 입력과 `violation_text` semantic 입력 분기, 감경 판단 직접 처리 기준 | 호출 필요/불필요 표가 아니라 입력 방식 판단표로 정리됐는지 |
| `#27 feat-objection-draft-report-node` | 이의신청서 생성 노드로 넘길 분석 결과, 부족 서류, 필요 증거, 사용자 추가 입력 조건 | `#27`의 input 조건과 맞는지 |
| `#28 test-fine-mvp-sample-case-validation` | 고지서 샘플 종류, 확보 방식, 샘플별 일반 분석 vs 법률 근거 포함 분석 비교 계획 | `#40`의 `INT-001`, `INT-002`, `INT-005` 실행 가능 여부 |

### 오늘 받아야 할 구체 산출물

- 고지서 샘플 5~6개 목록 또는 확보 계획
- 고지서 OCR input/output schema 초안
- OCR 실패/부분 인식 시 fallback 흐름
- 법률 근거 입력 방식 판단표 초안
- 필주 `law_search_node`는 항상 호출하고, `law_code` 기반 exact 입력과 `violation_text` 기반 natural language semantic 입력으로 구분
- 서류 단계 정규화 기준: `사전통지서 = 1차`, `사전통지서 독촉 = 2차 통지서`
- 감경 판단은 필주 범위에서 직접 처리

### 최신 확인 사항

`#26`에는 2026-06-19 `workzion2`의 법률근거검색 체크리스트 첨부가 있고, 2026-06-21 `techshin31`의 데이터 범위 관련 댓글이 추가됐다. 오늘은 두 내용을 합쳐서 실제 연결 input/output으로 구체화해야 한다.

## 5. 동혁 `techshin31`

### 담당 범위

법률 데이터 수집, 전처리, DB 적재, 법률 원문/조문/근거 metadata.

### 오늘까지 업데이트해야 하는 이슈

| 이슈 | 오늘 업데이트할 내용 | PM 확인 포인트 |
|---|---|---|
| `#20 feat-traffic-law-data-pipeline` | 법률 데이터 범위, API key 필요 여부, 기존 코드 활용 방식, 수집·전처리·DB 적재 파이프라인 계획 | 도로교통법, 시행령, 시행규칙, 고시/행정 기준 중 MVP 범위가 명확한지 |
| `#22 feat-agent-result-schema-and-rag-contract` | 법률 근거 검색 결과 metadata schema | `law_name`, `article`, `paragraph`, `item`, `effective_date`, `retrieved_at`, `jurisdiction`, `source_reference`가 포함되는지 |

### 오늘 받아야 할 구체 산출물

- 법률 데이터 source 목록
- 법률 원문/조문 metadata schema
- 법령 원문/조문 metadata schema
- 법령 DB/RAG 검색 결과가 근거 metadata로 전달되는 구조 초안
- 법률 데이터 최신성 표시 기준

### 최신 확인 사항

2026-06-21에 `#22`에 "데이터파이프라인을 구성하며 최종 input/output schema 구성 예정", `#26`에 "데이터 범위설정은 데이터 파이프라인을 짤때 기준을 정할 것"이라는 댓글이 올라왔다. 오늘은 이 내용을 실행 가능한 schema와 source 목록으로 보완해야 한다.

## 6. 재강 `leejaegang27`

### 담당 범위

경위서/OCR 결과 처리, 텍스트 ML, 과실비율 판례, 유튜브 자막 사례, 과실비율심의사례 데이터, 판례/사례 검색 흐름.

### 오늘까지 업데이트해야 하는 이슈

| 이슈 | 오늘 업데이트할 내용 | PM 확인 포인트 |
|---|---|---|
| `#1 feat-fault-youtube-caption-case-collector` | 유튜브 자막 사례 데이터의 우선순위, 수집 범위, 사고 유형 후보 metadata | 공식 근거가 아니라 참고 사례로만 쓰는 제한이 명시됐는지 |
| `#21 feat-fault-ratio-precedent-caption-review-case-pipeline` | 판례, 유튜브 자막, 과실비율심의사례 중 이번 주 우선순위와 전처리 흐름 | 데이터 신뢰도별 가중치 또는 구분 기준이 있는지 |
| `#30 feat-fault-ratio-ml-knowledge-base` | 검색 구조, 후보 모델, 입력/출력, 대안, 한계 | ML 학습 확정이 아니라 RAG/검색/태그 기반 흐름으로 정리됐는지 |
| `#31 feat-fault-ratio-structured-question-flow` | 사고 설명, 경위서 OCR input schema와 추가 질문 조건 | `#22` 공통 envelope과 연결되는지 |
| `#32 feat-fault-ratio-result-range-view` | 과실비율 수치 단정 방지 표현 기준 | 정성 라벨, 쟁점, 유사 사례 중심인지 |
| `#33 feat-fault-response-evidence-schema` | 사고 유형 후보, 쟁점 태그, 증거 태그, 유사 사례, 요약 output schema | Supervisor가 병합할 수 있는 evidence 구조인지 |

### 오늘 받아야 할 구체 산출물

- 텍스트 ML/RAG 후보 모델 목록
- 사고 설명 input/output schema
- 판례/유튜브 자막/과실비율심의사례 데이터 후보 목록
- 과실비율 단정 방지 표현 기준
- 사고 설명 샘플 1개 기준 예상 출력 예시

### 오늘 확인해야 할 리스크

- 과실비율을 수치로 확정하는 모델로 오해되지 않아야 한다.
- 유튜브 자막 사례는 공식 판례나 법령 근거가 아니므로 evidence source type을 `caption_case`로 분리해야 한다.
- 영상·이미지 분석 결과를 텍스트 근거로 받을지 `#36`, `#38`과 연결 지점을 확인해야 한다.

## 7. 주희 `ohjuheecode`

### 담당 범위

차량 사고 이미지·영상 데이터셋, Vision/DL 분석, 영상·이미지 Agent, DL 결과 구조화.

### 오늘까지 업데이트해야 하는 이슈

| 이슈 | 오늘 업데이트할 내용 | PM 확인 포인트 |
|---|---|---|
| `#36 spike-vision-model-use-case-decision` | 후보 모델 목록, 모델별 테스트 구조, 분석용 모델과 추론용 모델 구분, 검증 일정 | 모델 확정이 아니라 후보와 검증 기준인지 |
| `#37 feat-accident-vision-data-manifest-pipeline` | 사진, 차량 파손 이미지, 블랙박스 영상, CCTV 영상 중 우선 데이터와 manifest 형식 | 파일 출처, 사고 유형, metadata, 개인정보 처리 기준이 있는지 |
| `#38 feat-accident-image-video-agent-result-flow` | key frame, 장면 요약, confidence, 품질 이슈를 포함한 output schema | `#22`의 `vision_result` evidence metadata와 연결되는지 |
| `#39 test-vision-accident-poc-validation` | 샘플 영상/이미지 기준 POC 검증 계획 | `#40`의 `INT-004` 실행 가능 여부 |
| `#22 feat-agent-result-schema-and-rag-contract` | 영상·이미지 Agent 결과가 공통 schema에 맞게 들어가는 방식 | `structured_result.key_frames`, `scene_summary`, `confidence_label`, `quality_issues`가 명확한지 |

### 오늘 받아야 할 구체 산출물

- 영상·이미지 분석 후보 모델 목록
- 이미지/영상 input/output schema
- 데이터 manifest 초안
- key frame, 장면 요약, confidence 정의 초안
- 개인정보 처리 리스크 목록

### 오늘 확인해야 할 리스크

- 사고 책임을 확정하는 모델로 정의하면 안 된다.
- 영상 품질 낮음, 프레임 누락, 객체 탐지 실패는 `limitations`에 표시되어야 한다.
- 샘플 영상/이미지가 없으면 `#40`의 `INT-004`는 계속 `검증 필요` 상태로 남긴다.

## 8. 오늘 회의에서 공통으로 결정해야 할 항목

| 항목 | 오늘 결정 또는 분류할 내용 |
|---|---|
| 공통 Agent 결과 schema | 7개 필드 사용 여부: `node_name`, `node_code`, `status`, `summary`, `structured_result`, `evidence`, `next_actions`, `limitations` |
| 노드 정식 명칭 | 고지서 OCR·과태료/범칙금 분석 노드, 법률 근거 검색 노드, 텍스트 ML/판례·사례 검색 노드, 영상·이미지 분석 노드, 이의신청서 생성/리포트 노드 |
| Agent 식별 코드값 | `fine_notice_analysis`, `law_ground_search`, `text_ml_case_search`, `vision_media_analysis`, `objection_report_generation` 후보 확정 여부 |
| 법률 근거/감경 판단 호출 시점 | 고지서 OCR 후 필주 `law_search_node`는 항상 호출하고, `law_code`가 있으면 exact 입력, 없으면 `violation_text` natural language semantic 입력으로 처리한다. 감경 판단은 필주 범위에서 처리한다. |
| 추가 질문 기준 | 어떤 필드가 없으면 분석하지 않고 질문할지 |
| guardrail | 법률 단정, 과실비율 수치 단정, 제출 성공 보장 표현 금지 |
| API 명세 우선순위 | 챗봇 메시지, 파일 업로드, 분석 Job, Agent 결과 조회, 리포트, 이의신청서 초안 중 무엇부터 문서화할지 |

## 9. 오늘 끝나기 전 체크리스트

| 확인 항목 | 완료 기준 | 상태 |
|---|---|---|
| 각 담당자 코멘트 확인 | 본인 담당 이슈에 comment URL이 있고 Discord 또는 Notion 트래커에 공유됨 | 확인 필요 |
| `#22` schema 보완 | 모든 노드의 최소 input/output과 `structured_result` 초안이 있음 | 확인 필요 |
| `#29` routing rule 보완 | 입력 유형별 호출 노드와 추가 질문 조건이 있음 | 확인 필요 |
| `#13` 리스크 로그 갱신 | 미확정 항목이 `검증 필요`로 분리됨 | 확인 필요 |
| `#40` 통합 시나리오 갱신 | 최소 3개 이상의 시나리오에 입력, 호출 노드, 기대 출력, 상태가 있음 | 확인 필요 |
| 샘플 확보 상태 확인 | 고지서, 사고 설명, 영상/이미지 샘플의 확보 여부가 기록됨 | 확인 필요 |

## 10. 참고 링크

| 이슈 | 링크 |
|---|---|
| `#11` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/11 |
| `#12` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/12 |
| `#13` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/13 |
| `#20` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/20 |
| `#21` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/21 |
| `#22` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/22 |
| `#23` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/23 |
| `#24` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/24 |
| `#25` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/25 |
| `#26` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/26 |
| `#27` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/27 |
| `#28` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/28 |
| `#29` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/29 |
| `#30` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/30 |
| `#31` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/31 |
| `#32` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/32 |
| `#33` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/33 |
| `#36` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/36 |
| `#37` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/37 |
| `#38` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/38 |
| `#39` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/39 |
| `#40` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/40 |

## 11. 검증 기록

| 항목 | 결과 |
|---|---|
| 로컬 기준 문서 확인 | 완료 |
| GitHub 관련 이슈 최신 업데이트 확인 | 완료 |
| 2026-06-21 이후 추가 업데이트 | `#22`, `#26` 확인 |
| 주의 | GitHub Project 보드 상태는 별도 권한이 필요하므로 이 문서에는 반영하지 않았다. |
