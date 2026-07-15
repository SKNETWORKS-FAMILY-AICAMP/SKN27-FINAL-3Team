# Google OAuth Authorization Code 실연동 및 E2E 절차

이 문서는 mock 코드나 고정 프로필 없이 Google Identity Services popup code
flow를 로컬과 AWS staging에서 검증하는 운영 절차다. 로그인 용도로 받은 Google
access/refresh token은 사용자 식별 직후 폐기하고, 애플리케이션 JWT와 안전한 계정
연결 정보만 저장한다.

## 1. 환경별 origin을 먼저 확정한다

각 환경에서 브라우저 주소와 `GOOGLE_POPUP_REDIRECT_URI`는 정확히 같은 origin이어야
한다. origin에는 경로, 쿼리, fragment가 들어가면 안 된다.

| 환경 | 예시 origin | 허용 여부 |
|---|---|---|
| 로컬 | `http://127.0.0.1:5173` | 허용 |
| 로컬 대안 | `http://localhost:5173` | 허용하지만 위 주소와 혼용 금지 |
| staging | `https://staging.example.com` | 허용 |
| 공개 HTTP | `http://staging.example.com` | 차단 |
| callback 경로 | `https://staging.example.com/oauth/callback` | 차단 |

프론트와 API가 다른 origin이면 API의 `CORS_ALLOWED_ORIGINS`와
`CSRF_TRUSTED_ORIGINS`에 프론트 origin을 추가한다. 같은 origin으로 reverse proxy하는
구성이 가장 단순하고 저렴하다.

## 2. Google Cloud Console을 설정한다

1. OAuth consent screen을 설정하고 staging 검증 전까지 필요한 계정만 test user로
   등록한다.
2. OAuth client type은 `Web application`으로 만든다.
3. Authorized JavaScript origins에 사용할 로컬 및 staging origin을 정확히 등록한다.
4. popup code flow가 사용하는 redirect 값도 같은 origin으로 유지한다.
5. 발급된 Web client ID는 프론트와 백엔드가 동일하게 사용한다.
6. Client secret은 백엔드 secret store에만 저장한다. Vite 환경변수, Git, 브라우저
   응답, 로그에 넣지 않는다.

`localhost`와 `127.0.0.1`은 Google과 브라우저가 서로 다른 origin으로 취급한다.
하나를 선택한 뒤 Console, 브라우저 주소, 환경변수에서 동일하게 사용한다.

## 3. 로컬 환경변수를 설정한다

저장소 루트의 추적되지 않는 `.env`에 다음 값을 둔다.

```dotenv
VITE_GOOGLE_CLIENT_ID=<web-client-id>.apps.googleusercontent.com
GOOGLE_CLIENT_ID=<동일한-web-client-id>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<로컬에서만 주입되는-client-secret>
GOOGLE_POPUP_REDIRECT_URI=http://127.0.0.1:5173
GOOGLE_TOKEN_ENDPOINT=https://oauth2.googleapis.com/token
GOOGLE_USERINFO_ENDPOINT=https://openidconnect.googleapis.com/v1/userinfo
APP_JWT_SECRET=<32자 이상의 로컬 secret>
OAUTH_TOKEN_SECRET=<32자 이상의 로컬 secret>
```

두 endpoint는 공식 Google HTTPS 주소로 고정한다. 임의 proxy나 테스트 서버 주소는
client secret 또는 provider access token 유출을 막기 위해 런타임, readiness, smoke
모두에서 거부된다.

`.env`, Google client secret, 실제 authorization code는 커밋하지 않는다.

## 4. 로컬 사전 검증을 실행한다

```powershell
$env:DJANGO_ENV_FILE=".env"
python backend\manage.py check
python backend\manage.py check_production_readiness --skip-database --format json
python backend\manage.py smoke_google_oauth_code --format json
```

개발 설정 전체 때문에 readiness 최종 상태가 fail일 수는 있지만, 출력의
`google_oauth` check는 `pass`여야 한다. smoke 출력의 `config.ready`도 `true`여야
한다.

그 다음 프론트와 백엔드를 실행한다.

```powershell
npm --prefix app\web run dev
$env:DJANGO_ENV_FILE=".env"
python backend\manage.py runserver 127.0.0.1:8010
```

Vite의 기본 proxy target과 `.env.example`의 `VITE_API_PROXY_TARGET`이 모두 8010을
가리키므로 Django도 같은 port에서 실행한다.

브라우저에서 실제 test user로 로그인하고 다음을 확인한다.

- `POST /api/auth/google/code/`가 `200`을 반환한다.
- 응답 `contract_version`은 `google_auth_code.v1`이다.
- 응답 `auth_mode`는 `authorization_code`이다.
- `mock_google_code`, `authorization_code_mock`이 응답에 없다.
- `social_accounts`와 `auth_sessions` row가 생긴다.
- 로그인 전용 flow에서는 `oauth_connections`에 provider token을 저장하지 않는다.
- 응답과 서버 로그에 Google code, access token, client secret이 없다.
- 다른 guest에 묶인 session이나 이미 다른 사용자가 소유한 session은 Google 교환 전에
  `403`으로 거부된다.
- app JWT는 브라우저 영구 저장소에 보관하지 않는다. 페이지를 새로고침하면 stale
  `auth_session_id`를 로그인 상태로 복원하지 않고 새 guest 흐름으로 돌아가며, 필요한
  경우 Google 로그인을 다시 수행한다. 새로고침 후 자동 로그인은 향후 HttpOnly cookie
  세션으로 별도 구현한다.

이 프로젝트는 Google이 popup UX에 안내하는 custom `X-Requested-With` 검증을 사용하고,
그보다 엄격하게 브라우저 `Origin`도 서버 설정과 정확히 비교한다. OAuth `state`는
redirect UX를 도입할 때 별도로 생성·검증한다. popup과 redirect 방식을 한 endpoint에서
혼합하지 않는다.

## 5. 일회용 코드 재사용 거부를 검증한다

아직 교환하지 않은 새 code를 확보한 경우 다음 smoke가 첫 교환 성공과 동일 code의
두 번째 교환 거부를 연속 확인한다.

```powershell
python backend\manage.py smoke_google_oauth_code `
  --prompt-code `
  --require-exchange `
  --verify-replay-rejection `
  --format json
```

`--prompt-code`는 일회용 code를 숨김 입력으로 받으므로 프로세스 인자와 셸 기록에
남기지 않는다. 비대화형 자동화에서는 짧게 유지되는
`GOOGLE_OAUTH_SMOKE_CODE` 환경변수를 사용할 수 있으며, 명령 종료 직후 삭제한다.

통과 조건은 다음과 같다.

- 최상위 `status`가 `pass`이다.
- `exchange.auth_mode`가 `authorization_code`이다.
- `replay_check.status`가 `rejected`이다.
- 출력에 입력 code와 provider token이 없다.

이미 프론트나 다른 명령이 교환한 code를 첫 입력으로 사용하면 첫 교환부터 실패한다.
매 검증마다 새 code를 사용한다.

## 6. AWS staging에 적용한다

1. staging HTTPS origin을 먼저 확정한다.
2. Google Cloud Console에 그 origin을 등록한다.
3. public client ID만 프론트 빌드의 `VITE_GOOGLE_CLIENT_ID`로 주입한다.
4. Client ID, client secret, app JWT secret은 ECS task secret 또는 동등한 secret
   store에서 백엔드에 주입한다.
5. `GOOGLE_POPUP_REDIRECT_URI`는 사용자가 실제 여는 staging 프론트 origin과 정확히
   맞춘다.
6. 배포 후 readiness를 실행하고 `google_oauth=pass`를 확인한다.
7. staging test user로 실제 브라우저 로그인을 수행한다.
8. CloudWatch 로그에서 code, Google token, client secret이 출력되지 않았는지 확인한다.
9. 같은 code 재사용 요청이 `401`인지 확인한다.

## 7. 완료 증적

이슈와 PR에는 secret이나 code 원문을 붙이지 않고 다음만 기록한다.

- 검증 시각과 환경(local/staging)
- 프론트 origin과 API origin(비밀값 아님)
- readiness의 `google_oauth` 상태
- 성공 응답의 `contract_version`, `auth_mode`, HTTP status
- replay 요청 HTTP status와 안전한 error reason
- 생성된 `social_account_id`, `auth_session_id`는 필요하면 일부만 마스킹
- secret/token/code 미노출 로그 검색 결과

실제 계정으로 local과 staging 검증이 모두 끝나기 전에는 #192를 완료 처리하지 않는다.
