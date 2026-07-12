# AI 교통분쟁 초기상담 v2 구현 설계

## 1. 제품 정체성

이 서비스의 대표 경험은 사고 직후 사용자가 사진·블랙박스·진술을 바탕으로 사실을 정리하고,
근거가 있는 과실 범위와 다음 행동을 얻는 것이다. 단순 법률 챗봇이나 고지서 OCR이 아니라
`상담 → 증거 해석 → 사실 확정 → 근거 분석 → 사건 워크스페이스 → 실행 결과물`을 잇는
AI 교통분쟁 사건 워크스페이스를 지향한다.

고지서 이의신청은 계속 지원하지만 대표 제품 경험은 사고 초기상담이다. 고위험 사건은
긴급 안내, 증거 보존, 전문가 이관 자료까지만 제공하며 과실 범위를 산출하지 않는다.

## 2. 사용자 흐름

```text
게스트 자유상담
→ Risk Gate
→ 적응형 문진
→ 로그인 및 Case 생성
→ 위치 확인과 자료 업로드
→ Vision·도로정보 추출
→ 사실 카드 사용자 수정·확정
→ OpenSearch + pgvector + Neo4j 근거 분석
→ 과실 범위와 변동 요인
→ 사건 워크스페이스
→ 웹 요약서
→ 요청 시 PDF와 완료 알림
```

일반 교통질문은 Case를 만들지 않고 출처가 있는 짧은 답변으로 끝낸다. 사고상담은
도로 형태, 양 차량 행동, 신호·우선권, 충돌 위치가 모두 확인되기 전에는 수치를 숨긴다.

## 3. 핵심 도메인

- `Case`: 상담, 자료, 분석, 리포트를 묶는 사건 aggregate다.
- `ConfirmedFactVersion`: 사용자가 확정한 사실, 출처, 상충정보, 수정 이력을 불변 버전으로 보관한다.
- `MediaArtifact`: 선별 프레임, 마스킹 결과, 객체탐지 결과를 원본 자료와 분리한다.
- `Report`: `initial_consultation`, `expert_handoff`, 기존 제품 리포트를 버전별로 보관한다.
- 원본과 추출 프레임은 기본 30일 보관 후 삭제하고 구조화 사실과 요약서는 Case 삭제 전까지 보관한다.

Case 상태는 다음 값으로 고정한다.

```text
intake
awaiting_fact_confirmation
queued
analyzing
needs_input
ready
high_risk_handoff
closed
deleted
```

## 4. 공개 계약

### consultation_state.v2

자유입력 직후 intent, risk gate, 사실 카드, 핵심 4요소 충족도, 다음 질문을 제공한다.

### confirmed_facts.v1

확정 사실, 각 사실의 출처, 상충 항목, 사용자 수정 이력과 확정자를 제공한다. 모든 분석은
명시적인 fact version을 입력으로 사용한다.

### vision_media_result.v2

event window, key frame, detection box, 장면 후보, 품질 문제, 비식별화 결과를 제공한다.

### external_evidence.v1

provider, source URL 또는 내부 source reference, 데이터 기준일, 조회시각, 제한사항을 제공한다.

### fault_assessment.v2

과실 범위, 변동 요인, 유사사례·법령, 자료 충족도, 분석 한계를 제공한다.

### consultation_report.v2

웹과 PDF가 공유하는 섹션, 주석 프레임, SVG 사고 도식, 근거와 한계를 제공한다.

## 5. Vision 파이프라인

Vision은 부가기능이 아니라 증거를 구조화 사실로 바꾸는 핵심 계층이다.

1. S3 quarantine 객체의 ClamAV clean 판정을 확인한다.
2. FFmpeg/OpenCV로 event window와 후보 프레임을 추출한다.
3. 얼굴·번호판 등 식별자를 마스킹한다.
4. RunPod 객체탐지로 차량·보행자·신호·표지판 후보를 추출한다.
5. OpenAI Responses API를 `store:false`와 strict schema로 호출해 장면을 요약한다.
6. 객체탐지·장면요약·품질정보를 `vision_media_result.v2`로 병합한다.
7. 사용자가 사실 카드를 수정·확정하기 전에는 과실분석을 시작하지 않는다.

원본 영상 전체를 외부 provider에 전달하지 않는다. 비식별화된 선별 프레임만 제한시간이 짧은
signed URL 또는 직접 이미지 입력으로 전달한다.

## 6. 검색과 Neo4j

세 검색 계층은 대체 관계가 아니라 역할 분리 관계다.

- OpenSearch: 법조문·사례의 정확한 용어와 BM25/Nori 검색
- pgvector: 사용자 표현과 의미가 가까운 법령·사례 검색
- Neo4j: 행위, 도로상황, 의무, 위반 가능성, 과실 요인, 법령·사례 관계 확장

Supervisor는 세 결과를 하나의 `external_evidence.v1` 목록으로 정규화한다. Neo4j가 unavailable이면
성공으로 위장하지 않고 `partial`과 누락된 관계 추론 범위를 반환한다. v2 staging 활성화 조건에는
Neo4j 적재, 관계 질의, source reference 검증이 포함된다.

초기 graph schema는 다음 관계를 포함한다.

```text
(RoadContext)-[:IMPLIES_DUTY]->(Duty)
(VehicleAction)-[:MAY_VIOLATE]->(Duty)
(Duty)-[:GROUNDED_IN]->(LawProvision)
(FaultFactor)-[:SUPPORTED_BY]->(Precedent)
(Precedent)-[:APPLIES_WHEN]->(RoadContext)
```

## 7. Agent 실행 순서

```text
Risk Gate
→ Input Validation
→ Vision / Road Context
→ Fact Confirmation
→ OpenSearch / pgvector / Neo4j Evidence
→ Fault Assessment
→ Result Validation
→ Report Composer
```

모든 Agent 결과는 `status`, `structured_result.schema_version`, `evidence`, `limitations`를 가진다.
외부 의존성 장애는 `dependency_unavailable` 또는 `partial`로 반환한다.

## 8. API

- `POST /api/cases/`: 인증 후 상담 session을 Case로 승격
- `GET /api/cases/`: 소유자의 Case 목록
- `GET /api/cases/{case_id}/workspace/`: 사건 집계
- `POST /api/cases/{case_id}/facts/confirm/`: 사실 버전 확정
- `POST /api/cases/{case_id}/analysis/jobs/`: 확정 fact version으로 worker queue 등록
- 기존 chat, file, analysis result, report API는 유지하고 Case 식별자를 additive하게 연결

## 9. 기능 플래그와 활성화 원칙

- `CASE_WORKSPACE_V2_ENABLED`
- `VISION_PIPELINE_ENABLED`
- `EVIDENCE_MCP_ENABLED`
- `NEO4J_EVIDENCE_ENABLED`
- `SQS_WORKER_ENABLED`
- `EMAIL_NOTIFICATION_ENABLED`

플래그는 목표를 축소하기 위한 장치가 아니라 실연동 전 거짓 성공을 막기 위한 release gate다.
Vision과 Neo4j는 v2 제품의 필수 목표이며 staging 실연동과 대표 사건 검증 후 활성화한다.

## 10. 구현 순서

1. Case, confirmed facts, 상담 상태와 canonical API
2. Vision, 비식별화, RunPod/OpenAI provider
3. OpenSearch + pgvector + Neo4j 통합 evidence
4. 사건 워크스페이스, consultation_report.v2, PDF, 알림
5. AWS staging, 대표 사건셋, 보안·성능·복구 검증

## 11. 완료 기준

- 사용자 확정 전 과실 범위를 표시하지 않는다.
- 고위험 사건에서 과실 범위를 산출하지 않는다.
- 표시된 법령·사례는 100% source reference를 가진다.
- Vision 원본은 clean 판정과 비식별화 전 Agent에 전달되지 않는다.
- Neo4j 장애는 관계 근거가 없는 정상 성공으로 기록되지 않는다.
- 다른 사용자의 Case, fact version, 파일, 분석, 리포트 접근을 차단한다.
- 실제 Vision·Neo4j 자격증명 smoke와 대표 사건 E2E 전에는 v2를 운영 완료로 표시하지 않는다.
