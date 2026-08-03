# Pilot 브라우저 수동 E2E 실패·차단 원인 분석 보고서

## 1. 보고서 범위와 결론

- 실행 일자: 2026-08-03 (KST)
- 대상 URL: `https://skn27-traffic-pilot.duckdns.org/`
- 배포 source revision: `e15d39da9aa1701209113cf75e1735357b587fac`
- 앱 핫픽스 포함 커밋: `4f1d1c30eceff7142b26b37734463d88709815d5`
- 브라우저: 실제 Chrome 사용자 세션 및 격리된 인앱 브라우저
- 범위: 실패한 사용자 여정과 그 실패로 차단된 후속 결과물

통과로 판정된 단계와 이번 실행에서 다루지 않은 항목은 집계와 본문에서 제외했다. 결론은 다음과 같다.

| ID | 사용자 여정 | 판정 | 원인 결론 | 근거 수준 |
|---|---|---|---|---|
| F-01 | J01 일반 교통·법령 상담 | **FAIL** | 현재 정적 라우터는 동일 질문을 법령 상담으로 올바르게 분류한다. 브라우저의 사고 상담 전환은 저장된 후속상담 intent가 현재 입력보다 우선되는 경로와 일치하지만, 당시 저장 상태가 없어 마지막 촉발 조건은 확정할 수 없다. 별도 법령 질문은 프런트 polling 한도를 소진했으며 worker 미완료 원인은 로그·job id 부재로 미확정이다. | 고신뢰 경계 / 내부 원인 미확정 |
| F-02 | J02 과태료 상담 슬롯 누적 | **FAIL** | `고지서 첨부가 가능합니다`가 허용 표현 목록에 없어 `attachment_available` 슬롯이 생성되지 않고 동일 사실을 다시 질문한다. | 확정 |
| F-03 | J03·J04 PDF, J06 JPG 분류 확인 | **FAIL** | 서버는 분류 확인 필요 상태를 만들지만 공개 응답 allowlist가 `structured_results`를 제거한다. 프런트 확인 카드는 제거된 필드와 workflow 상태를 동시에 요구하므로 렌더링될 수 없다. | 확정 |
| F-04 | J06 교통사고 사실확인원 PNG | **FAIL** | 전용 OCR 목적은 일반 분류 대상이 아닌데 workflow 계산기가 전용 OCR 결과를 읽지 않아 영구적으로 `wait_for_classification`을 만든다. 공개 응답의 `structured_results` 제거도 OCR 표시를 막는다. | workflow 원인 확정 / worker 실패 원인 미확정 |
| F-05 | J08 인증·상담 새로고침 복원 | **FAIL** | 서버 인증 세션은 active였으나 클라이언트가 성공적인 `/auth/me/` 복구 경계에 도달하지 못했다. 저장 tuple 부재·읽기 실패가 가장 일관된 설명이지만, 당시 저장값과 네트워크 응답을 수집하지 않아 `/auth/me/` 선행 실패 가능성까지 배제할 수 없다. | 고신뢰 경계 / 마지막 촉발 조건 미확정 |
| B-01 | OCR/Vision 이후 persisted report·이의신청서 | **BLOCKED** | 분류 확인·OCR/Vision·사실 확인 선행 게이트를 통과하지 못해 생성 및 재조회 검증을 시작할 수 없었다. | 선행 실패로 확정 |

### 근거 수준 정의

- **확정**: 브라우저 증상, 현행 코드의 인과 경로, 동일 입력의 제어 재현이 일치한다.
- **고신뢰 경계**: 실패가 발생한 계층과 가능한 코드 경로는 좁혔지만 당시 요청의 session/job/network 추적값이 없어 단일 촉발 조건을 확정할 수 없다.
- **미확정**: 관찰 결과와 가능한 가설만 있고 해당 가설을 직접 입증하는 운영 로그가 없다.
- **차단**: 상위 게이트 실패로 후속 기능 자체를 실행하지 못했다. 후속 기능의 독립 결함으로 계산하지 않는다.

## 2. 배포 및 자료 무결성

### 2.1 실행 코드 기준

1. 원격 `dev` HEAD는 `e15d39da9aa1701209113cf75e1735357b587fac`였다.
2. EC2 `skn27-pilot-app`의 backend·worker·frontend 컨테이너 이미지 태그는 모두 `e15d39da9aa1`이었다.
3. 핫픽스 커밋 `4f1d1c30`은 배포 revision의 ancestor다.
4. 현재 작업 커밋 `4f1d1c30`과 배포 revision 사이에서 이 보고서가 인용한 앱 파일에는 차이가 없었다. 따라서 아래 줄 번호는 배포 소스와 동일하다.
5. 공개 `/api/health/`와 `/api/health/ready/`는 HTTP 200이었고, 배포 파이프라인 source/build/deploy 단계는 성공 상태였다.

이 기준은 “구 코드 때문에 재현됐다”는 설명을 배제한다. 다만 health 응답은 worker 개별 job의 성공이나 브라우저 저장소의 정상 동작까지 보장하지 않는다.

### 2.2 입력 파일 식별값

| 파일 | SHA-256 | 사용 여정 |
|---|---|---|
| `form2_별지154_위반사실통지및과태료사전통지서.pdf` | `E10856495BE492276194D0B187A8C090C5C3F935FF24403B3179207B738B8F49` | J03 |
| `form3_별지152_과태료납부고지서원부_운전자.pdf` | `C8B9721719E14D46733A32E07099515F94EA824E0464D7F039D12DCDA547FC6B` | J04 |
| `15-07-18-.jpg` | `91DC04770F8BFA48544788C0EC0D2AB972B19D6122E3C9E37596CC00A0623D83` | J06 JPG |
| `22-11-18-_.png` | `E2CC01C0D67410AF5C3A93BA6786DF272EAE14D3CDF3672D48110619F05FAB6B` | J06 PNG |

원본 파일, 개인정보 원문, raw OCR, 토큰, 쿠키, 인증 헤더, private storage URI는 보고서나 저장소에 복사하지 않았다.

## 3. F-01 — J01 일반 법령 상담 실패

### 3.1 브라우저 관찰

1. `횡단보도 앞에서 운전자가 일시정지해야 하는 도로교통법 근거와 적용 한계를 알려주세요.`라고 질문했다.
2. 화면은 법령 설명 대신 `당시 신호나 우선권 상황을 알려주세요.`라는 사고 사실 질문을 반환했다.
3. 특정 사고가 아니라 일반 법령 요건임을 명시한 후속 입력에도 보행자 사고 expert handoff가 반환됐다.
4. 새 상담에서 도로교통법 제5조 근거를 별도로 물었을 때 분석 진행 상태가 지속되다가 `분석 상태 확인이 지연되고 있습니다. 잠시 후 다시 확인할 수 있습니다.`로 종료됐다.

기대 결과는 법령 근거·적용 요건·한계를 설명하는 것이었고, 실제 결과는 사고 intake 또는 분석 지연이었다.

### 3.2 정적 키워드 라우터가 직접 원인은 아닌 근거

- 법령 키워드는 사고 키워드보다 먼저 정의돼 있다: `app/config/supervisor_routing_policy.v1.json:20-45`.
- 현재 라우팅 함수는 이 정책으로 content route를 결정한다: `app/services/supervisor_routing_service.py:76-106`.
- 일반 교통 법령은 지원 범위이며, 보행자 제외 규칙은 사고 intent와 사고 맥락이 함께 있을 때 적용된다: `app/config/service_scope_policy.v1.json:54-79`, `app/services/service_scope_policy_service.py:30-69`, `app/services/service_scope_policy_service.py:115-128`.
- 동일한 첫 질문을 배포 소스의 순수 함수에 넣은 제어 재현 결과는 `routing_intent=traffic_law_search`, `scope=traffic_law_reference`, `action=proceed`였다.
- 회귀 테스트도 일반 횡단보도 법령 질문의 법령 라우팅을 전제로 한다: `test/test_chat_orchestration_service.py:32-49`, `test/test_service_scope_policy_service.py:6-14`.

따라서 “`횡단보도` 또는 `보행자`라는 단어 때문에 현행 키워드 정책이 곧바로 오분류했다”는 설명은 현행 소스와 재현 결과에 반한다.

### 3.3 가장 강한 오분류 원인 후보: 저장된 intent 우선 적용

확인된 인과 경로는 다음과 같다.

1. API view가 저장된 후속상담 상태를 로드하고 `followup_routing_intent(stored_state)`를 현재 상담 type보다 우선 후보로 전달한다: `backend/chatbot/views.py:1345-1367`.
2. 후속상담 상태는 이전 `routing_intent`를 보존하고 그대로 반환한다: `app/services/chat_session_followup_service.py:75-96`.
3. orchestration은 override가 비어 있거나 `general_consultation`일 때만 현재 입력의 라우팅 결과를 사용하고, 그 외 값이면 override를 유지한다: `app/services/chat_orchestration_service.py:201-210`.
4. 브라우저에 나온 `당시 신호나 우선권`은 사고 intake 필드 문구다: `app/web/consultationIntake.js:58-63`.

즉 이전 사고 intent가 같은 session에 남아 있었다면 현재 법령 입력이 올바르게 분석돼도 최종 route는 사고 상담으로 고정된다. 이 메커니즘은 관찰 증상과 정확히 맞지만, 당시 요청의 저장 follow-up state를 캡처하지 않았으므로 “그 요청에서 실제로 이전 intent가 존재했다”까지는 확정할 수 없다.

### 3.4 분석 지연이 의미하는 정확한 범위

- 프런트 설정은 worker 결과를 500ms 간격으로 최대 60회 확인한다: `app/web/FrontendAppShell.jsx:72-74`.
- polling 호출 경계는 `app/web/FrontendAppShell.jsx:1355-1370`, 반복·종료 로직은 `app/web/workerPolling.js:23-75`다.
- 관찰된 지연 문구는 polling 소진 시 사용하는 문구와 일치한다: `app/web/workerPolling.js:10`.

따라서 **프런트가 제한 시간 안에 terminal worker 결과를 받지 못했다**는 점은 확정된다. 그러나 worker가 미완료된 이유가 queue 지연, adapter 예외, 외부 의존성 지연, 결과 저장 실패 중 무엇인지는 당시 job id와 worker 로그가 없어 확정할 수 없다.

### 3.5 추가 확정에 필요한 증거

- 실패 요청의 `session_id`, 저장 follow-up state, 최종 `routing_intent_override`
- 지연 응답의 `job_id`, queue→running→terminal 전이 시각, worker 예외 로그

이 두 자료 없이 J01을 하나의 단일 root cause로 단정하면 증거 수준을 넘는다.

## 4. F-02 — J02 `attachment_available` 반복 질문

### 4.1 브라우저 관찰

한 문장에 문서 종류, 발급기관 `서울시`, 의견제출 기한 `2026-08-12`, `고지서 첨부가 가능합니다`를 모두 제공했다. 화면은 앞의 세 사실은 유지했지만 `고지서 사진이나 파일을 첨부할 수 있나요?`라고 다시 물었다.

### 4.2 확정 원인

1. `attachment_available=yes` 정책은 `첨부 가능`만 canonical expression으로 두고 `첨부도 가능`, `문서 첨부도 가능`만 alias로 등록한다: `app/config/supervisor_input_normalization_policy.v1.json:251-262`.
2. normalizer는 등록된 expression·alias의 literal match만 후보로 만든다: `app/services/supervisor_input_normalization_service.py:65-116`, `app/services/supervisor_input_normalization_service.py:134-169`.
3. projection은 생성된 후보만 reducer slot으로 전달한다: `app/services/supervisor_input_projection_service.py:38-43`, `app/services/supervisor_input_projection_service.py:295-312`.
4. 후보가 없으면 reducer는 `attachment_available`을 missing field로 남기고 해당 질문을 생성한다: `app/services/fine_notice_intake_service.py:114-153`; 질문 원문은 `app/services/fine_notice_intake_service.py:19`다.

### 4.3 동일 입력 제어 재현

| 입력 표현 | normalization 결과 | reducer 결과 |
|---|---|---|
| `고지서 첨부가 가능합니다.` | `attachment_available` 후보 없음 | missing field로 남아 브라우저와 동일한 질문 생성 |
| `문서 첨부도 가능합니다.` | `attachment_available=yes` 생성 | 네 슬롯 충족, 추가 질문 없음 |

문장 전체가 후속 답변으로 들어가는 별도 경로도 `yes`, `y`, `예`, `네`, `가능`, `있음`과 같은 전체값만 허용한다: `app/services/fine_notice_intake_service.py:157-170`. 따라서 실제 자연어 문장은 초기 normalization과 후속 단답 양쪽에서 취약하다.

### 4.4 테스트가 놓친 이유

- 기존 테스트는 정확히 등록된 표현인 `문서 첨부도 가능해요`만 검증한다: `test/test_supervisor_input_normalization_service.py:231-253`.
- 브라우저에서 사용한 `고지서 첨부가 가능합니다` 회귀 사례가 없다.

이는 기본값이 사용자의 값을 덮어쓴 문제가 아니라, **자연어 표현이 후보로 생성되지 않은 phrase coverage 결함**이다.

## 5. F-03 — PDF·JPG 분류 확인 카드 누락

### 5.1 브라우저 관찰

- J03 사전통지서 PDF와 J04 납부고지서 PDF는 `Attachment document classification completed.`까지 진행됐다.
- J06 사고 JPG도 분류 완료 상태가 표시됐다.
- 세 경우 모두 공개 workflow는 `classified_waiting_confirmation`, next action은 `confirm_classification`이었다.
- 그러나 `자료 분류 확인 후 다음 분석 진행` 카드와 버튼이 렌더링되지 않아 OCR/Vision으로 진행할 수 없었다.

### 5.2 확정 원인: workflow와 공개 payload의 계약 분리

서버에서 분류 결과가 사라지는 순서는 다음과 같다.

1. 분류 adapter는 성공 결과에 `requires_confirmation=true`, `next_action=confirm_classification`, `attachment_id`를 만든다: `app/services/agent_node_service.py:1403-1458`.
2. attachment classification service는 이 결과를 확인 가능한 record로 보존한다: `backend/chatbot/attachment_classification_service.py:116-143`.
3. workflow builder는 persisted `agent_results`에서 이 결과를 읽어 `classified_waiting_confirmation`을 만든다: `app/services/attachment_workflow_service.py:136-143`, `app/services/analysis_job_query_service.py:414-452`.
4. 동시에 사용자에게 반환할 composed result는 `_COMPOSED_RESULT_FIELDS` allowlist로 projection된다: `app/services/analysis_job_query_service.py:25-36`, `app/services/analysis_job_query_service.py:260-304`.
5. 이 allowlist에 `structured_results`가 없어 최종 공개 payload에서 분류 상세가 제거된다.
6. 프런트는 `analysisResponse.structured_results.attachment_document_classification`에서 상세를 읽는다: `app/web/FrontendAppShell.jsx:418-420`.
7. 확인 카드는 workflow state가 `classified_waiting_confirmation`이면서 동시에 분류 상세의 `requires_confirmation===true`여야 표시된다: `app/web/FrontendAppShell.jsx:3577-3585`.

결과적으로 workflow 조건은 참이지만 상세 조건은 항상 거짓이 된다. 사용자는 서버가 이미 만든 확인 대상을 확인할 방법이 없다.

### 5.3 동일 payload 제어 재현

분류 `structured_result`와 `requires_confirmation=true`를 포함한 저장 agent 결과를 조회 서비스에 넣었을 때:

- 공개 workflow: `classified_waiting_confirmation`
- 공개 next action: `confirm_classification`
- 공개 `structured_results`: 없음

브라우저의 “상태 문구는 있지만 카드가 없는” 결과와 동일하다. 더구나 기존 테스트는 composed 결과에 `structured_results`가 있어도 공개 payload에서 제거돼야 한다고 명시적으로 assert한다: `test/test_analysis_job_query_service.py:407-477`.

따라서 이 문제는 브라우저 렌더링 타이밍이나 파일 포맷 문제가 아니라, **백엔드 공개 projection 계약과 프런트 소비 계약의 모순**이다. PDF 2개와 JPG가 동일 증상을 보인 이유도 같은 공통 경계를 사용하기 때문이다.

## 6. F-04 — 사실확인원 PNG가 `wait_for_classification`에 고정

### 6.1 브라우저 관찰

교통사고 사실확인원 PNG를 독립 새 상담에 업로드한 뒤 15초·30초 시점에도 workflow가 `classification_running`, next action이 `wait_for_classification`이었다. 최종 화면은 `검증을 통과한 분석 결과가 없습니다. 입력 자료와 근거를 확인한 뒤 다시 시도해 주세요.`를 표시했고 OCR 결과는 나타나지 않았다.

### 6.2 확정 원인: 전용 OCR 목적을 일반 분류 workflow로 계산

1. `traffic_accident_confirmation`은 specialized purpose다: `app/services/supervisor_routing_service.py:18`.
2. 이 purpose는 일반 attachment classification을 요구하지 않고 `traffic_accident_confirmation_ocr`로 직접 route된다: `app/services/supervisor_routing_service.py:76-121`, `app/config/supervisor_routing_policy.v1.json:15-17`.
3. 그러나 attachment workflow builder는 `attachment_document_classification`과 `fine_notice_analysis`만 읽고 `traffic_accident_confirmation_ocr` 결과를 읽지 않는다: `app/services/attachment_workflow_service.py:81-105`.
4. 일반 classification이 없으면 무조건 `classification_running`과 `wait_for_classification`을 반환한다: `app/services/attachment_workflow_service.py:162-169`.
5. 프런트가 전용 OCR 결과를 읽는 위치도 `analysisResponse.structured_results.traffic_accident_confirmation_ocr`이므로 F-03의 공개 projection 제거 영향을 함께 받는다: `app/web/FrontendAppShell.jsx:411-417`.

### 6.3 동일 목적 제어 재현

`purpose=traffic_accident_confirmation`인 clean attachment를 배포 소스에 넣으면:

- `classification_required=false`
- route는 `traffic_accident_confirmation_ocr`
- 성공한 전용 OCR structured result를 넣어도 workflow는 `classification_running/wait_for_classification`

따라서 화면의 분류 대기는 실제 라우팅 계획과 모순된 **workflow 표현 결함**이다.

다만 화면의 `검증을 통과한 분석 결과가 없습니다`만으로 전용 OCR worker가 실제 실행됐는지, 실행 후 validation에서 탈락했는지는 판단할 수 없다. 해당 내부 원인은 당시 job id와 agent result가 없어 미확정이다.

## 7. F-05 — J08 새로고침 후 인증·상담 미복원

### 7.1 브라우저 관찰

1. Google 인증 후 `로그아웃`, `Google 계정 상담`이 표시된 상태에서 상담을 완료했다.
2. 같은 탭을 새로고침했다.
3. 5.5초 후와 추가 10초 후 모두 루트 화면은 `Google 로그인` 상태였고 이전 상담·리포트는 복원되지 않았다.
4. 화면 공개 콘솔에는 경고나 오류가 없었으며, 계속 진행하려면 외부 브라우저에서 다시 인증해야 했다.

### 7.2 프런트 복원 계약

- 로그인 성공 시 메모리 상태를 갱신한 뒤 `persistAuthSession`을 호출한다: `app/web/FrontendAppShell.jsx:823-860`.
- reload 시 저장 상태는 최초 렌더에서 한 번 읽는다: `app/web/FrontendAppShell.jsx:286-298`.
- `access_token`과 `auth_session_id`가 모두 있을 때만 인증된 저장 세션으로 간주하고 복구 effect를 실행한다: `app/web/FrontendAppShell.jsx:480-625`.
- 저장·읽기 함수는 `app/web/authSession.js:465-500`, localStorage 접근은 `app/web/authSession.js:507-537`에 있다.
- localStorage 쓰기 예외는 사용자나 telemetry에 전달되지 않고 무시된다: `app/web/authSession.js:518-526`.
- 복구 요청은 `app/web/authSession.js:54-131`, 인증을 지울 수 있는 응답은 401/403으로 제한된다: `app/web/authSession.js:203-205`.

따라서 로그인 직후 메모리 상태만 정상이고 persistent tuple 쓰기가 실패하거나 reload에서 읽히지 않으면, 로그인 완료 화면은 정상이어도 reload 후에는 복구 effect 자체가 시작되지 않는다. 저장 성공을 read-back으로 검증하지 않고 쓰기 오류를 숨기는 현재 구현은 이 실패를 탐지하지 못한다.

### 7.3 운영 DB 근거와 배제 가능한 설명

2026-08-03 J08 재현 시간대의 운영 DB를 SSM 경유 읽기 전용 집계로 확인했다.

| 관찰 | 결과 | 의미 |
|---|---|---|
| Google code login event | 재현 전후 시간대에 생성됨 | 서버 로그인 성공 경계는 통과함 |
| 대응 AuthSession | `active`, `revoked_at=NULL`, 만료 전 | reload 직후 서버가 세션을 logout/revoke했다는 설명과 맞지 않음 |
| AuthEvent의 `auth_me_checked` | 해당 집계 구간 0건 | 성공한 `/auth/me/` persistence 경계가 기록되지 않음 |
| 재인증 event | reload 실패 후 시간대에 다시 생성됨 | 브라우저에서 외부 재인증이 필요했다는 관찰과 일치 |

성공한 `/auth/me/`는 `persist_current_auth_subject`를 거쳐 기본 event type `auth_me_checked`를 생성한다: `backend/chatbot/views.py:594-625`, `backend/chatbot/repositories.py:1312-1333`, `backend/chatbot/repositories.py:1398-1412`.

이 근거로 확정할 수 있는 경계는 **서버 세션 생성 이후, 성공한 `/auth/me/` 복구 persistence 이전**이다. 가장 일관된 원인은 저장 tuple 부재·읽기 실패지만 다음 두 경우를 당시 자료만으로 구분할 수 없다.

1. 저장 tuple이 없거나 불완전해 복구 요청 자체가 시작되지 않음
2. 복구 요청은 시작됐지만 인증/네트워크 오류로 성공 persistence 전에 종료됨

브라우저 localStorage 원문이나 network trace를 수집하지 않았으므로 1번을 확정 원인으로 단정하지 않는다. 또한 성공한 인증 복구가 확인되지 않았으므로 그 다음 단계인 resume manifest를 이번 실패의 원인으로 지목할 근거도 없다.

### 7.4 추가 확정에 필요한 증거

- 로그인 직후 민감값을 제외한 `has_access_token`, `has_auth_session_id` read-back 결과
- reload 직후 `/auth/me/` 요청 존재 여부, HTTP status, 공개 error code
- `/auth/me/` 성공 시에만 resume manifest 요청·응답 확인

## 8. B-01 — Persisted report·이의신청서 차단 원인

기대 연결 순서는 다음과 같다.

`분류 결과 확인 → OCR/Vision → 추출 사실 확인 → 사건/분석 생성 → persisted report → 이의신청서 초안 → 새로고침 재조회`

실행은 PDF/JPG에서 분류 결과 확인 UI 앞, PNG에서 잘못된 분류 대기 상태에서 멈췄다. 그 결과 마이페이지의 등록 사건, 저장 리포트, 최근 분석은 모두 0건이었다.

이 0건은 report 저장 엔진이나 초안 생성기의 독립 실패를 입증하지 않는다. 필요한 입력과 사용자 확인 게이트가 먼저 생성되지 않았기 때문이다. 따라서 이 두 결과물은 **FAIL이 아니라 BLOCKED**이며, F-03·F-04를 해결한 뒤에야 독립 결함 여부를 판단할 수 있다.

## 9. 원인별 수정 지점과 재검증 조건

이 절은 원인 분석에 따른 권고이며, 이번 보고서 작성 범위에서 코드는 수정하지 않았다.

| 우선순위 | 원인 | 수정 지점 | 실패가 해소됐다고 볼 수 있는 최소 증거 |
|---|---|---|---|
| P0 | 공개 payload가 분류/OCR structured result를 제거 | `app/services/analysis_job_query_service.py`, 공개 응답 contract test | PDF와 JPG에서 `classified_waiting_confirmation`과 확인 카드가 함께 표시되고 확인 클릭 뒤 OCR/Vision으로 전진 |
| P0 | 전용 OCR을 일반 분류 대기로 표현 | `app/services/attachment_workflow_service.py`, `traffic_accident_confirmation_ocr` workflow test | PNG가 일반 분류 대기에 머물지 않고 전용 OCR terminal/confirmation 상태를 표시 |
| P0 | 인증 persistence 복구 관측 불가 | `app/web/authSession.js`, `app/web/FrontendAppShell.jsx` | 로그인 직후 저장 tuple read-back, reload `/auth/me/` 성공, 동일 상담 resume를 한 trace로 확인 |
| P1 | 첨부 가능 자연어 표현 누락 | normalization policy와 fine notice reducer tests | 브라우저의 정확한 문장으로 네 슬롯이 채워지고 반복 질문이 없음 |
| P1 | 과거 follow-up intent가 현재 법령 입력보다 우선 가능 | `backend/chatbot/views.py`, `app/services/chat_orchestration_service.py` | 동일 session에서 사고 상담 뒤 일반 법령 질문을 보내도 content route가 법령으로 전환되며 저장/현재 intent가 trace에 남음 |
| P1 | worker polling terminal 미도달 | job 상태·worker logging | 실패 job의 queue·running·terminal과 예외 원인을 job id로 연결하고 법령 응답이 제한 시간 내 완료 |

필수 연결 재시험은 `J02 정확 문장 → PDF 2종 → JPG → PNG → 사실 확인 → 사건/리포트/초안 → 동일 탭 reload` 순서로 수행한다. 각 단계는 새 session 격리 여부와 job id를 함께 기록해야 한다.

## 10. 증거 및 출처 인덱스

### 10.1 브라우저 증거

| 증거 ID | 관찰 내용 | 보존 형태 |
|---|---|---|
| E-J01-DOM | 일반 법령 질문의 사고 intake 전환과 별도 질문 polling 지연 | 현재 Codex 작업의 DOM snapshot |
| E-J02-01 | 네 슬롯 문장과 첨부 가능 여부 반복 질문 | 현재 Codex 작업의 browser capture |
| E-J03-01 | PDF 분류 완료 workflow와 확인 카드 누락 | 현재 Codex 작업의 browser capture |
| E-J04-01 | 다른 PDF에서 동일 확인 카드 누락 | 현재 Codex 작업의 browser capture |
| E-J06-JPG-DOM | JPG 분류 완료 후 확인 UI 누락 | 현재 Codex 작업의 DOM snapshot |
| E-J06-PNG-01 | 사실확인원 PNG의 `wait_for_classification` 고정 | 현재 Codex 작업의 browser capture |
| E-J08-01 | 동일 탭 reload 후 Google 로그인 화면 | 현재 Codex 작업의 browser capture |
| E-MYPAGE-01 | 등록 사건·저장 리포트·최근 분석 0건 | 현재 Codex 작업의 DOM snapshot |

화면 증거에는 토큰, 쿠키, 인증 헤더, 개인정보 원문을 포함하지 않았다. 바이너리 캡처는 저장소에 추가하지 않았다.

### 10.2 코드·테스트·설계 출처

- 배포 소스 기준: `origin/dev` revision `e15d39da9aa1701209113cf75e1735357b587fac`
- 시나리오 설계: `C:/Users/Playdata/.codex/worktrees/0b9f/SKN27-FINAL-3Team/docs/superpowers/specs/2026-08-03-pilot-browser-manual-e2e-scenario-report-design.md:88-131`
- J01 route/scope: `app/config/supervisor_routing_policy.v1.json:20-45`, `app/services/supervisor_routing_service.py:76-121`, `app/config/service_scope_policy.v1.json:54-79`
- J01 stored intent: `backend/chatbot/views.py:1345-1367`, `app/services/chat_session_followup_service.py:75-96`, `app/services/chat_orchestration_service.py:201-210`
- J01 polling: `app/web/FrontendAppShell.jsx:72-74`, `app/web/FrontendAppShell.jsx:1355-1370`, `app/web/workerPolling.js:10`, `app/web/workerPolling.js:23-75`
- J02 normalization/reducer: `app/config/supervisor_input_normalization_policy.v1.json:251-262`, `app/services/supervisor_input_normalization_service.py:65-169`, `app/services/supervisor_input_projection_service.py:295-312`, `app/services/fine_notice_intake_service.py:114-170`
- 분류 공개 projection: `app/services/analysis_job_query_service.py:25-36`, `app/services/analysis_job_query_service.py:260-304`, `app/services/analysis_job_query_service.py:414-452`, `test/test_analysis_job_query_service.py:407-477`
- 분류 확인 UI: `app/services/attachment_workflow_service.py:136-143`, `app/web/FrontendAppShell.jsx:418-420`, `app/web/FrontendAppShell.jsx:3577-3585`
- 사실확인원 전용 OCR: `app/services/supervisor_routing_service.py:18`, `app/services/supervisor_routing_service.py:76-121`, `app/services/attachment_workflow_service.py:81-105`, `app/services/attachment_workflow_service.py:162-169`
- 인증 복구: `app/web/authSession.js:54-131`, `app/web/authSession.js:203-205`, `app/web/authSession.js:465-537`, `app/web/FrontendAppShell.jsx:286-298`, `app/web/FrontendAppShell.jsx:480-625`, `app/web/FrontendAppShell.jsx:823-860`
- 인증 persistence event: `backend/chatbot/views.py:594-625`, `backend/chatbot/repositories.py:1312-1412`

### 10.3 운영 증거

- AWS EC2 instance `i-08457b1c0bef7d17b` (`skn27-pilot-app`)의 실행 컨테이너 image tag 읽기
- SSM 경유 Django ORM 읽기 전용 집계: 최근 3시간 `AuthEvent.event_type`, J08 시간대 `AuthSession.status/revoked_at/expires_at`
- 공개 health endpoint 응답과 배포 pipeline 상태

운영 집계는 계정 식별자, 토큰, 세션 식별자 원문을 출력하지 않은 집계 결과만 사용했다. J08의 특정 로그인과 운영 event 시간대 연결은 비식별 시간 상관관계이므로 단일 사용자 identity 매칭으로 표현하지 않았다.

## 11. 최종 판정

확정된 직접 원인은 세 가지다.

1. J02는 실제 자연어 문장이 normalization 표현 목록에 없어 슬롯이 생성되지 않는다.
2. PDF·JPG는 백엔드가 만든 분류 상세를 공개 projection이 제거하면서 프런트 확인 조건을 충족할 수 없다.
3. 사실확인원 PNG는 전용 OCR 목적을 workflow builder가 일반 분류 대기로 잘못 표현한다.

J01은 정적 라우터 결함이 아니라 저장 intent 우선 경로가 가장 강한 오분류 원인 후보이며, worker 지연 내부 원인은 미확정이다. J08은 서버 세션 생성 이후 성공한 인증 복구 이전으로 실패 경계가 좁혀졌지만, 저장 tuple 부재와 `/auth/me/` 선행 실패를 구분할 당시 network/storage 증거가 없다.

따라서 확정 근거가 있는 세 계약 결함을 먼저 수정하고, J01에는 session/job trace를, J08에는 민감값 없는 storage read-back과 network trace를 추가한 뒤 연결 여정을 다시 실행해야 한다. 그 전에는 persisted report와 이의신청서 초안의 독립 정상·실패 여부를 판정할 수 없다.
