# 공통 오류·권한·부분 결과 API 응답 의미 계약 설계

**이슈:** #277
**기준:** PR #276이 병합된 `origin/dev`
**상태:** 구현 완료 — PR #278

## 1. 목표와 범위

이미 shadow OpenAPI로 등록된 canonical API가 인증 실패, 권한 거부, 부분 결과, 비동기 대기, 서비스 불가를 외부 클라이언트가 일관되게 해석하도록 계약과 회귀 테스트를 추가한다.

기존 HTTP 상태, 오류 코드, 오류 body, Django view 동작은 바꾸지 않는다. 공통화 대상은 **응답 형식이 아니라 응답 의미**다.

포함 범위는 다음과 같다.

- OpenAPI의 401 응답에 `authentication_failure`, 403 응답에 `authorization_denied` 의미를 표기한다.
- 채팅 메시지의 attachment scan gate `409` 부분 결과와 `503` 서비스 불가를 명시한다.
- 분석 결과 조회의 `202` 대기 상태를 부분 결과와 구분해 명시한다.
- 대표 인증·소유권·부분 결과 런타임 회귀와 정적 OpenAPI 회귀를 추가한다.
- 검증 완료 후 마스터 체크리스트 H의 공통 계약 항목만 완료 처리한다.

다음은 제외한다.

- `CaseApiErrorResponse`, `ChatApiErrorResponse`, `AnalysisJobErrorResponse` 등의 오류 DTO 통합 또는 제거
- 기존 오류 코드·HTTP 상태·view·repository·DB migration 변경
- 프런트 UI, Worker, 외부 서비스 장애 관측, 대표 사용자 흐름 E2E 변경

## 2. 현재 구현과 확인된 공백

`RouteSpec.errors`는 이미 endpoint별 오류 코드와 DTO를 보유하고, OpenAPI는 이를 `x-error-codes`로 생성한다. 그러나 401과 403의 공통 해석 규칙, 그리고 성공 body 형태를 유지하면서 부분 상태를 알리는 비정상 HTTP 응답의 의미는 명시하지 않는다.

특히 채팅 첨부파일 scan gate는 `409`이지만 `ChatMessageResponse` 형태의 `status="partial"`·제한사항·scan gate 정보를 반환한다. 이는 일반 오류 envelope가 아니며 현재 route contract에 빠져 있다. 반대로 분석 결과의 `202`는 비동기 작업 대기이며 `partial`과 같은 의미가 아니다.

## 3. 계약 설계

### 3.1 공통 오류·권한 의미

OpenAPI generator는 기존 `RouteErrorSpec`을 유지한 채 다음 확장 필드를 추가한다.

- 401: `x-response-semantics: authentication_failure`
- 403: `x-response-semantics: authorization_denied`

이는 `auth_required`, `token_invalid`, `guest_session_invalid`, `login_required`, `object_access_denied` 같은 기존 endpoint별 코드 목록을 대체하지 않는다. 클라이언트는 세부 처리를 `x-error-codes`로, 공통 분류를 `x-response-semantics`로 해석한다.

`auth_optional=True`는 익명 또는 guest 접근 가능성을 뜻할 수 있으므로, 401이 없는 route에 401 계약을 새로 만들지 않는다. 다만 view가 이미 401을 반환하는데 RouteSpec에 누락된 경우에는, 먼저 Django 회귀 테스트로 실제 status·오류 code·body 모델을 고정하고 그 **기존 동작**만 RouteSpec/OpenAPI에 추가한다. 최초 점검 대상은 `GET`·`POST /api/analysis/jobs/`이며, 상세·결과 조회도 guest credential 누락·만료·잘못된 credential 조합을 같은 기준으로 확인한다.

### 3.2 명시적 outcome 응답

`RouteSpec`에 기본값이 빈 튜플인 `outcome_responses`를 추가한다. 한 outcome은 다음을 가진다.

- `status`: 실제 HTTP 상태
- `semantic`: `partial_result`, `pending`, `service_unavailable` 중 하나
- `description`: 외부 클라이언트용 의미 설명
- `response_model`: 해당 상태에서 실제 반환되는 기존 DTO

검증 규칙은 status 중복을 막는다. outcome status는 기본 성공 status와 기존 오류 status에 동시에 등록할 수 없다. 따라서 새 메타데이터가 기존 response schema를 덮어쓰지 않는다.

OpenAPI generator는 outcome을 원래 HTTP status의 response로 생성하고 `x-response-semantics`를 함께 기록한다.

### 3.3 최초 적용 경로

의미가 실제 구현으로 확인된 경로만 우선 등록한다.

| 경로 | HTTP 상태 | 의미 | 기존 body |
| --- | ---: | --- | --- |
| `POST /api/chat/messages/` | 409 | `partial_result` | `ChatMessageResponse` (`status="partial"`, scan gate·limitations 포함) |
| `POST /api/chat/messages/` | 503 | `service_unavailable` | 기존 `ChatMessageResponse` |
| `GET /api/analysis/results/{job_id}/` | 202 | `pending` | 기존 `AnalysisResultResponse` |

채팅의 503과 분석 결과의 202는 더 이상 일반 성공 응답 목록에 두지 않고, 같은 schema를 가진 outcome response로 문서화한다. 이 변경은 OpenAPI 설명과 확장 메타데이터만 바꾸며 runtime status·body는 바꾸지 않는다.

HTTP 상태 코드만으로 outcome을 일반화하지 않는다. `POST /api/analysis/jobs/`의 409는 `AnalysisJobErrorResponse` error envelope이며 내부 `analysis.status`가 `partial`일 수 있어도 `partial_result` outcome으로 등록하지 않는다. 반대로 채팅 scan gate의 409만 `ChatMessageResponse`를 반환하는 명시적 partial outcome이다.

또한 `POST /api/analysis/jobs/`의 202는 Worker 큐 접수(`AnalysisJobAcceptedResponse`)이므로 기존 성공 응답으로 유지한다. `pending` outcome은 결과가 아직 준비되지 않은 `GET /api/analysis/results/{job_id}/`의 202에만 적용한다.

## 4. 호환성·보안 경계

- endpoint별 오류 DTO와 `x-error-codes`는 유지한다.
- 401/403 의미는 HTTP 상태에만 부여하며 코드 목록을 재분류하거나 삭제하지 않는다.
- `202 pending`과 `partial_result`를 분리해 재시도·폴링 UI가 부분 결과를 완료 상태로 오해하지 않게 한다.
- `409 partial_result`는 일반 오류 DTO로 강제 변환하지 않아 scan gate의 제한사항과 사용자 다음 행동을 보존한다.
- 비회원 인증과 App JWT의 기존 security 요구사항·guest credential 검증은 변경하지 않는다.

## 5. 검증 계획

1. Django 회귀 테스트에서 `GET`·`POST /api/analysis/jobs/`와 job 상세·결과 조회의 guest credential 누락·만료·잘못된 credential 조합을 실행해, 실제 401 status·오류 code·body 모델을 고정한다. RouteSpec에는 이 결과로 확인된 기존 401만 추가한다.
2. 정적 계약 테스트에서 outcome status 중복 거부와 401/403 의미 생성 규칙을 확인한다.
3. OpenAPI 생성 테스트에서 채팅 409 partial, 채팅 503 unavailable, 분석 결과 202 pending의 schema·의미를 확인한다. 분석 작업 큐의 409 error envelope와 202 accepted가 outcome으로 바뀌지 않는 것도 함께 확인한다.
4. Django 런타임 테스트에서 무인증 401, 타인 소유권 403, scan gate partial, 분석 결과 pending을 확인한다.
5. 기존 route별 API 계약·OpenAPI 생성·Django chatbot 회귀를 실행한다.
6. 생성 YAML을 갱신하고 H의 `전체 오류·권한 오류·부분 결과 응답 공통 계약 정리` 항목만 완료 표시한다.

## 6. 비목표와 후속 작업

이번 이슈는 전역 오류 envelope 표준화나 외부 서비스 운영 관측을 완료하지 않는다. I의 외부 서비스 장애·데이터 갱신 실패·큐 적체 관측과 대표 사용자 흐름 E2E는 별도 이슈로 유지한다.
