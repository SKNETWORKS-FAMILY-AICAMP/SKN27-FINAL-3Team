# Canonical 대표 사용자 흐름 E2E 회귀 검증 설계

**이슈:** #279  
**기준:** PR #278 병합 뒤 `origin/dev` (`cb80779`)  
**상태:** 설계 검토 대기

## 1. 목표와 범위

현재 서비스의 대표 사용자 흐름을 외부 OCR·RAG·LLM 제공자 없이 재현 가능한 Django E2E 테스트로 고정한다. 이 테스트는 실제 공개 API, 저장소, Worker 처리, 공개 DTO, 공식 문서 다운로드 경계를 연결해 검증한다.

성공 흐름은 다음 순서를 따른다.

1. 유효한 App JWT 사용자로 세션을 생성한다.
2. 과태료 고지서 용도 자료를 업로드하고 스캔 Worker가 `clean` 상태로 완료한 것을 확인한다.
3. 채팅 요청이 Supervisor 계획과 비동기 Worker 작업을 큐잉하는지 확인한다.
4. 테스트 전용의 결정적 Agent 결과로 Worker를 처리한다.
5. 분석 결과와 리포트 상세의 공개 DTO에서 확인된 사실, 사용자 주장, 근거, 한계, 다음 행동을 확인한다.
6. 문서 확인 API를 거친 뒤 공식 이의신청서 DOCX를 다운로드한다.

동일한 테스트 묶음에서 다음 비정상 경로도 확인한다.

- Worker 처리 전 분석 결과 조회의 `202 pending`
- 선택된 검색 도메인 일부 실패 시 `partial` 결과와 한계·다음 행동
- 다른 App JWT 사용자의 결과·리포트·다운로드 접근 거부

이번 이슈는 OCR 모델 품질·정답지 기반 정확도·실제 RAG 검색 품질·외부 서비스 장애 관측·프런트 UI 재설계를 검증하지 않는다.

## 2. 현재 구조와 분리 원칙

현재 canonical 다운로드 경로는 `/api/reports/{report_id}/download/?document_type=objection_form`이며, 문서 확인과 소유권 검증을 통과한 경우에만 DOCX MIME 타입을 반환한다. 새 E2E는 이 경로와 `PK`로 시작하는 DOCX 본문만 성공 조건으로 사용한다.

`backend/chatbot/tests.py`의 `RemovedChatbotMockApiContract`에는 PDF를 검증하는 과거 목 시나리오가 남아 있다. 이 테스트는 이력 참조용이며 #279의 canonical 완료 근거로 사용하지 않는다. 이번 작업은 이를 삭제·변환·복구하지 않고, 새 테스트가 PDF를 요청하거나 PDF 응답을 기대하지 않도록 명확히 분리한다.

기존 `test_resource_ownership_e2e.py`는 리소스 소유권과 DOCX 다운로드를, `test_supervisor_reporting_pipeline.py`는 Worker 보고서 생성과 DOCX 렌더링을 각각 검증한다. #279는 이들을 대체하지 않고, 사용자 요청부터 공개 결과와 문서 다운로드까지를 한 경로로 연결하는 회귀 테스트를 추가한다.

## 3. 대안과 선택

### 대안 A — 독립 canonical E2E 테스트 파일 (선택)

`backend/chatbot/test_canonical_user_flow_e2e.py`에 전용 테스트 클래스를 둔다. App JWT 발급, 결정적 Agent fixture, 테스트 Worker 실행을 파일 내부의 작은 보조 함수로 제한한다.

- 장점: 사용자 흐름의 목적이 분명하고, 소유권·Worker 단위 테스트와 책임이 섞이지 않는다.
- 장점: 외부 제공자와 시간·네트워크 의존성이 없어 CI에서 재현 가능하다.
- 단점: 기존 fixture 일부가 중복될 수 있다. 중복은 테스트 목적이 다른 범위에서만 허용하고, 제품 코드 공통화는 하지 않는다.

### 대안 B — 기존 소유권 E2E 확장

기존 `test_resource_ownership_e2e.py`에 정상·pending·partial 시나리오를 모두 추가한다.

- 장점: 인증과 DOCX fixture를 재사용할 수 있다.
- 단점: 소유권 경계 테스트의 책임이 사용자 여정·상태 전이까지 과도하게 넓어져 실패 원인 파악이 어려워진다.

### 대안 C — 브라우저 기반 프런트 E2E

실제 UI를 브라우저로 조작해 같은 흐름을 검증한다.

- 장점: 화면 연결까지 확인할 수 있다.
- 단점: 현재 이슈의 API/Worker 회귀 범위를 넘어가며, UI 변경과 테스트 안정성이 결합된다.

따라서 대안 A를 선택한다.

## 4. 테스트 설계

### 4.1 정상 DOCX 사용자 흐름

테스트는 실제 `/api/` 요청으로 세션·파일·채팅·분석 결과·리포트·문서 확인·다운로드를 호출한다. 파일 스캔과 Agent 실행만 테스트 내부에서 결정적으로 처리한다. 이는 사용자 입력과 권한, 큐잉, 저장·조회 API, Worker 결과 영속화, DOCX 렌더링은 실제 경로로 검증하면서 외부 제공자의 비결정성을 제거한다.

Worker 완료 뒤에는 다음을 검증한다.

- 분석 결과는 공개 DTO이며 내부 `execution_payload`, Worker 원문, Agent raw output, 저장 URI를 노출하지 않는다.
- 공개 DTO는 확인된 사실, 사용자 주장, 근거, 한계, 다음 행동을 제공한다.
- 리포트는 Worker가 생성한 `ready` 상태이며, 문서 확인 전에는 다운로드가 차단된다.
- 문서 확인 후 `objection_form` 다운로드는 DOCX MIME 타입, attachment 헤더, `PK` 본문을 반환한다.
- PDF MIME 타입·`.pdf` 파일명·PDF 본문은 성공 조건에 포함하지 않는다.

### 4.2 pending 경로

동일한 인증·세션·채팅 큐잉 직후, Worker를 실행하기 전에 `GET /api/analysis/results/{job_id}/`를 호출한다. 현재 계약대로 `202`와 pending 상태의 공개 응답을 확인한다. 이 검증은 `202`를 partial 또는 오류로 오해하지 않도록 고정한다.

### 4.3 partial 경로

별도의 결정적 Worker fixture에서 필수 분석은 정상 처리하고 선택된 검색 도메인 하나만 `failed` 결과로 반환한다. 결과는 `partial`로 유지되어야 하며, 공개 DTO에는 실패한 내부 예외가 아닌 사용자용 한계와 다음 행동이 포함되어야 한다. 보고서 생성·다운로드 가능 여부는 현재 Reporting gate가 정한 실제 결과를 그대로 검증하며, partial을 성공 보고서로 승격하는 신규 동작은 만들지 않는다.

### 4.4 소유권 거부 경로

정상 흐름에서 생성된 `job_id`와 `report_id`에 대해 다른 App JWT 사용자가 결과·리포트·다운로드를 요청한다. 각 요청은 `403 object_access_denied`를 반환해야 하며, DOCX Content-Disposition·DOCX MIME 타입·`PK` 본문이 없어야 한다. 문서 렌더링 함수도 호출되지 않아야 한다.

## 5. 호환성·리스크 관리

- 제품 코드, API schema, DB migration, 프런트 UI를 변경하지 않는다. 테스트와 체크리스트만 변경한다.
- Agent fixture는 실제 제공자 호출을 대체하지만, Worker 큐잉·처리·보고서 영속화 경계를 우회하지 않는다.
- App JWT를 대표 인증 수단으로 선택한다. Guest credential의 수명·전환 경로는 이미 별도 E2E로 검증되므로 이슈 #279의 대표 경로에 중복 포함하지 않는다.
- 이력 PDF 목 테스트는 건드리지 않는다. 새 E2E가 DOCX 전용 정책의 현재 근거가 된다.
- 실제 OCR·RAG·LLM 품질을 이 테스트의 통과 조건으로 사용하지 않는다. 품질 평가와 운영 관측은 체크리스트 I의 별도 미완료 항목으로 남긴다.

## 6. 검증과 체크리스트

구현 후 다음을 실행한다.

1. 새 canonical E2E 테스트 단독 실행
2. 관련 소유권·게스트 로그인·Supervisor 보고서·API 응답 계약 테스트 실행
3. 전체 Python 테스트 실행

모든 검증이 통과하면 `docs/ops/project-readiness-master-checklist.md`의 I 항목 중 아래 한 줄만 완료 처리한다.

```md
- [x] 대표 사용자 흐름 E2E: 자료 입력, 사실/주장 분리, OCR, Supervisor 계획, 법령·판례 검색, 한계 표시, 리포트 생성·다운로드 — #279
```

OCR·검색·생성형·영상 분석의 품질 지표, 외부 서비스 장애 관측 등 I의 나머지 항목은 상태를 변경하지 않는다.
