# 2026-06-19 회의 피드백 이슈 코멘트 작성 가이드

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-19 |
| 목적 | 오늘 회의에서 받은 피드백을 각 담당자가 어느 GitHub Issue comment에 작성해야 하는지 명확히 정리한다. |
| 공통 회의록 이슈 | `#11 docs-wbs-owner-deliverable-plan` |
| 개인별 업로드 기한 | 2026-06-21(일) 23:59 KST |
| 작성 원칙 | 회의 중 잡담, 소음, 농담, STT 오인식으로 보이는 문장은 제외하고 결정/피드백/후속 조치만 작성한다. |

## 1. 전체 공통 안내

전체 회의 요약과 공통 기한은 `#11 docs-wbs-owner-deliverable-plan`에 등록한다.

각 담당자는 새 이슈를 만들지 않고, 본인 담당 업무와 연결된 기존 이슈의 comment에 회의 피드백 반영 내용을 작성한다.

업로드 후 Discord 또는 Notion 트래커에 아래 내용을 공유한다.

- 작성한 GitHub Issue 번호
- 작성한 comment URL
- 어떤 피드백을 반영했는지 한 줄 요약

## 2. 공통 comment 작성 양식

각 담당자는 담당 이슈 comment에 아래 형식을 사용한다.

```markdown
### 2026-06-19 회의 피드백 반영

- 회의에서 지적/요청받은 부분:
- 필요한 산출물 또는 확인 항목:
- 수정/보완 계획:
- 연결되는 다른 담당자/이슈:
- 관련 브랜치 또는 문서 링크:
- 완료 기준:
- 남은 리스크 또는 검증 필요 항목:
```

## 3. 담당자별 작성 대상 이슈

### 3.1 필주 `workzion2`

담당 범위: 고지서 OCR, 과태료·범칙금·벌칙 분석용 룰/매핑 데이터, 과태료·범칙금 분석 흐름

| 작성 대상 이슈 | 작성해야 하는 내용 |
|---|---|
| `#23 feat-fine-notice-ocr-intake-flow` | 고지서 OCR input/output 필드, 필수 필드, 누락 필드, OCR 실패/부분 인식 시 재업로드·수동 입력·추가 질문 흐름 |
| `#24 feat-fine-penalty-rule-mapping` | 과태료·범칙금·벌칙 분석용 룰/매핑 데이터 범위, 동혁 법률 원문 DB와 중복되지 않는 분석용 데이터 기준 |
| `#25 feat-fine-analysis-detail-view` | 처분 단계, 이의제기 가능성, 부족 서류, 필요 증거를 사용자에게 어떤 구조로 보여줄지 |
| `#26 feat-fine-law-ground-search` | 법률 근거 검색 노드 호출 시점, 법률 근거가 필요한 케이스와 필요 없는 케이스, 동혁 법률 데이터와 연결되는 input/output |
| `#27 feat-objection-draft-report-node` | 이의신청서 생성 노드로 넘길 필주 분석 결과, 부족 서류, 필요 증거, 사용자 추가 입력 조건 |
| `#28 test-fine-mvp-sample-case-validation` | 고지서 샘플 종류, 샘플 확보 방식, 샘플별 일반 분석 vs 법률 근거 포함 분석 비교 계획 |

권장 작성 순서:

1. `#23`에 OCR 필드와 실패 처리 흐름을 먼저 작성한다.
2. `#28`에 샘플 검증 계획을 작성한다.
3. `#26`에 법률 근거 연결 조건을 동혁 담당 범위와 맞춰 작성한다.
4. `#24`, `#25`, `#27`에는 분석 결과가 어디에 쓰이는지 나눠 작성한다.

### 3.2 동혁 `techshin31`

담당 범위: 법률 데이터 수집, 전처리, DB 적재, 법률 원문/조문/근거 metadata

| 작성 대상 이슈 | 작성해야 하는 내용 |
|---|---|
| `#20 feat-traffic-law-data-pipeline` | 법률 데이터 범위, API key 필요 여부, 기존 코드 활용 방식, 수집·전처리·DB 적재 파이프라인 재설계 계획 |
| `#22 feat-agent-result-schema-and-rag-contract` | 법률 근거 검색 결과 metadata schema, `law_name`, `article`, `effective_date`, `source_url` 외 필요한 필드 |
| `#26 feat-fine-law-ground-search` | 고지서 위반 유형을 법률 검색어로 변환하는 기준, 필주 고지서 분석 결과와 연결되는 검색 input/output |
| `#9 epic-legal-precedent-data-ingestion-and-rag` | 법률 데이터와 판례 데이터의 경계, 법령/시행령/시행규칙/고시·행정 기준과 판례 데이터의 구분 방식 |

권장 작성 순서:

1. `#20`에 법률 데이터 scope와 파이프라인 계획을 먼저 작성한다.
2. `#22`에 법률 근거 metadata schema를 작성한다.
3. `#26`에 필주 흐름과 연결되는 검색어 변환 기준을 작성한다.
4. `#9`에는 법률 데이터와 판례/사례 데이터 경계를 보완한다.

### 3.3 재강 `leejaegang27`

담당 범위: 경위서/OCR 결과 처리, 텍스트 ML, 과실비율 판례, 유튜브 자막 사례, 과실비율심의사례 데이터, 판례/사례 검색 흐름

| 작성 대상 이슈 | 작성해야 하는 내용 |
|---|---|
| `#1 feat-fault-youtube-caption-case-collector` | 유튜브 자막 사례 데이터의 우선순위, 수집 범위, 사고 유형 후보 metadata |
| `#21 feat-fault-ratio-precedent-caption-review-case-pipeline` | 판례, 유튜브 자막, 과실비율심의사례 데이터 중 다음 주 우선순위와 전처리 흐름 |
| `#30 feat-fault-ratio-ml-knowledge-base` | RAG/Elasticsearch/vector DB 중복 구조 재검토, 하이브리드 검색 필요성, 임베딩·분류·요약·태그 생성 후보 모델과 선택 이유 |
| `#31 feat-fault-ratio-structured-question-flow` | 사고 설명, 경위서 OCR 등 input schema와 추가 질문이 필요한 조건 |
| `#32 feat-fault-ratio-result-range-view` | 과실비율을 확정 수치로 단정하지 않고 범위, 유사 사례, 쟁점 근거 중심으로 표현하는 기준 |
| `#33 feat-fault-response-evidence-schema` | 사고 유형 후보, 쟁점 태그, 증거 태그, 유사 사례, 요약을 어떤 output schema로 반환할지 |

권장 작성 순서:

1. `#21`에 데이터 우선순위와 전처리 흐름을 먼저 작성한다.
2. `#30`에 검색 구조와 후보 모델 재검토 결과를 작성한다.
3. `#33`에 output schema를 작성한다.
4. `#31`, `#32`에는 input schema와 결과 표현 제한 기준을 분리해 작성한다.

### 3.4 주희 `ohjuheecode`

담당 범위: 차량 사고 이미지·영상 데이터셋, Vision/DL 분석, 영상·이미지 Agent, DL 결과 구조화

| 작성 대상 이슈 | 작성해야 하는 내용 |
|---|---|
| `#36 spike-vision-model-use-case-decision` | 후보 모델 목록, 모델별 테스트 구조, 분석용 모델과 추론용 모델 구분, 모델 검증 일정 |
| `#37 feat-accident-vision-data-manifest-pipeline` | 사진, 차량 파손 이미지, 블랙박스 영상, CCTV 영상 중 우선 데이터, 해외 블랙박스 영상 사용 근거, manifest 형식과 metadata |
| `#38 feat-accident-image-video-agent-result-flow` | 상황 후보, 장면 요약, key frame, confidence, 품질 이슈를 포함한 output schema와 sequence diagram 수정 방향 |
| `#39 test-vision-accident-poc-validation` | 샘플 영상/이미지 기준 POC 검증 계획, key frame 추출 기준, 장면 변화 또는 변곡점 기준 검증 방법 |
| `#22 feat-agent-result-schema-and-rag-contract` | 영상·이미지 Agent 결과가 공통 Agent schema에 맞게 들어가는 방식 |

권장 작성 순서:

1. `#37`에 데이터 사용 기준과 manifest 초안을 먼저 작성한다.
2. `#36`에 후보 모델과 테스트 구조를 작성한다.
3. `#38`에 output schema와 sequence diagram 보완 방향을 작성한다.
4. `#39`에 POC 검증 계획을 작성한다.
5. `#22`에는 공통 schema와 맞춰야 할 결과 필드를 작성한다.

### 3.5 요청자/PM `hi20260204-maker`

담당 범위: WBS/문서, Supervisor 통합 답변 구조, 화면 흐름, 이의신청서 생성 노드, 통합 QA

| 작성 대상 이슈 | 작성해야 하는 내용 |
|---|---|
| `#11 docs-wbs-owner-deliverable-plan` | 오늘 회의록 정리, 담당자별 피드백 업로드 기한, 각 담당자가 작성해야 할 이슈 안내 |
| `#12 docs-mvp-screen-and-process-flows` | 홈, 로그인, 챗봇, 결과/리포트 진입 흐름과 오늘 회의 결정 반영 범위 |
| `#13 docs-requirement-gap-and-risk-log` | 확정, 초안, 검증 필요, 보류 항목과 미확정 리스크 |
| `#22 feat-agent-result-schema-and-rag-contract` | 공통 Agent 결과 schema, Agent 식별 코드값, evidence metadata 기준 |
| `#27 feat-objection-draft-report-node` | 필주 분석 결과와 동혁 법률 근거를 받아 이의신청서 생성 노드로 넘기는 입력 조건 |
| `#29 feat-supervisor-chatbot-routing` | Supervisor routing rule, 법률 질문이 사고 전 상담에서도 들어올 수 있는 흐름, Agent 호출 순서 |
| `#40 test-cross-mvp-integration-scenarios` | 통합 테스트 시나리오, 담당자별 input/output 연결 검증 기준 |

권장 작성 순서:

1. `#11`에 전체 회의록과 담당자별 작성 안내를 먼저 남긴다.
2. `#22`와 `#29`에 공통 schema와 Supervisor routing 기준을 작성한다.
3. `#13`과 `#40`에 미확정 항목과 통합 검증 시나리오를 정리한다.
4. `#12`, `#27`에는 화면 흐름과 이의신청서 생성 연결 조건을 정리한다.

## 4. 최종 확인 체크리스트

각 담당자의 comment가 올라온 뒤 아래 기준으로 확인한다.

| 확인 항목 | 기준 |
|---|---|
| 담당 이슈 선택 | 피드백 내용이 관련 이슈에 작성됐는가 |
| 기한 준수 | 2026-06-21(일) 23:59 KST까지 업로드됐는가 |
| 불필요한 회의 내용 제거 | 잡담, STT 오인식, 농담성 발화가 제외됐는가 |
| input/output 명확성 | 본인 담당 노드의 input과 output이 확인 가능한가 |
| 연결 지점 | 다른 담당자 또는 다른 이슈와 연결되는 지점이 명시됐는가 |
| 검증 필요 분리 | 확정되지 않은 항목을 확정처럼 쓰지 않고 `검증 필요`로 남겼는가 |
| URL 공유 | Discord 또는 Notion 트래커에 issue 번호와 comment URL을 공유했는가 |

## 5. GitHub Issue 링크

| Issue | 링크 |
|---|---|
| `#1` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/1 |
| `#9` | https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/9 |
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
