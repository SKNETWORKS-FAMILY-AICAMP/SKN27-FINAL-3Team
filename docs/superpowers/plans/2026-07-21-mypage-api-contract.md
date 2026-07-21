# 마이페이지 요약 API 계약 구현 계획

## 목표

`GET /api/mypage/summary/`를 현재 Django 런타임 동작을 변경하지 않는 공식 shadow OpenAPI 계약으로 등록하고, owner·session·guest credential 소유권 경계를 회귀 테스트로 고정한다.

## 작업 1 — 실패하는 정적 계약 테스트 작성

수정/생성 대상:

- `test/test_mypage_api_contract.py`
- `test/test_api_route_specs.py`
- `test/test_openapi_v1_generation.py`

검증할 내용:

- mypage route가 공식 registry에 있고 Deferred에는 없을 것
- `session_id`, `owner_id`, `user_id`, `limit` query와 두 guest header가 문서화될 것
- `owner_id` 우선, `user_id` 호환 별칭, limit 기본값 폴백이 설명에 포함될 것
- 응답 안정 필드와 확장 허용 정책이 OpenAPI에 반영될 것
- `auth_optional=True`이지만 guest credential 검증은 여전히 필요함을 설명할 것

먼저 아래 테스트가 실패하는지 확인한다.

```powershell
.venv\Scripts\python.exe -m pytest -p no:timeout -p no:cacheprovider test/test_mypage_api_contract.py test/test_api_route_specs.py test/test_openapi_v1_generation.py -q
```

## 작업 2 — DTO와 route registry 등록

수정/생성 대상:

- `app/contracts/mypage.py`
- `app/contracts/api_route_specs.py`

구현 원칙:

- request body는 없고 query/header parameter만 선언한다.
- `MyPageSummaryResponse` 상위 DTO는 `extra="allow"`로 둔다.
- 안정 화면용 요약 및 case/policy 필드만 타입화한다.
- route는 `GET /api/mypage/summary/`, `canonical-mypage-summary`, `mypage_summary`와 정확히 연결한다.
- `auth_required=False`, `auth_optional=True`로 등록하되, 무인증 허용이라는 의미로 쓰지 않는다.
- 이 route만 `DEFERRED_ROUTE_SPECS`에서 제거한다.
- view, repository, URL, 프런트 코드는 수정하지 않는다.

## 작업 3 — 실제 Django 경로의 소유권 회귀 테스트

수정/생성 대상:

- `backend/chatbot/test_mypage_api_contract.py`
- 필요 시 기존 guest credential boundary 테스트 파일

검증할 내용:

- 인증 주체 자신의 owner·session 요청이 200인지 확인한다.
- 타 owner와 타 session 요청이 403인지 확인한다.
- `X-Guest-Id` 단독 요청은 기존처럼 401 `auth_required`/`missing_token`으로 거부되는지 확인한다. 즉 raw guest ID는 단독 권한 증명이 아니다.
- 유효 credential guest 요청은 기존 정책을 유지하는지 확인한다.
- 무효 `limit`이 새 오류가 아니라 현행 기본값 동작을 유지하는지 확인한다.

실제 외부 provider는 호출하지 않고 기존 mock/auth helper만 사용한다.

## 작업 4 — OpenAPI 생성·체크리스트·전체 검증

수정 대상:

- `docs/api/openapi-v1.yaml` (generator 출력)
- `docs/ops/project-readiness-master-checklist.md`

체크리스트는 정적·Django·생성 문서 검증이 모두 통과한 후에만 같은 PR에서 갱신한다.

검증 순서:

```powershell
.venv\Scripts\python.exe backend\manage.py test chatbot.test_mypage_api_contract -v 1
.venv\Scripts\python.exe scripts\generate_openapi_v1.py --output docs\api\openapi-v1.yaml
.venv\Scripts\python.exe -m pytest -q --timeout=30 -p no:cacheprovider
```

마지막으로 변경 범위를 확인한다.

```powershell
git diff --check origin/dev...HEAD
git diff --name-only origin/dev...HEAD
```

## 안전장치

- DTO를 runtime validation이나 response filtering에 연결하지 않는다.
- `limit`을 OpenAPI 정수 강제로 바꾸거나 400 규칙을 추가하지 않는다.
- owner/user alias 우선순위 및 guest header policy는 문서·테스트로만 고정한다.
- 운영 메타데이터 상세를 강한 공개 DTO로 고정하지 않는다.
