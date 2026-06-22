# 비밀정보 관리 기준

| 항목 | 내용 |
|---|---|
| 기준 이슈 | `#43 chore-final-stabilization-and-release-readiness` |
| 대상 | API key, DB password, token, OAuth secret, 인증서 |

## 1. 저장 원칙

- 비밀정보는 소스 코드, Markdown, HTML, 클라이언트 JavaScript에 저장하지 않는다.
- 로컬 개발은 환경변수 또는 로컬 전용 `.env`를 사용한다.
- `.env` 파일은 Git 추적 대상에 포함하지 않는다.
- 배포 환경에서는 환경별 secret store 또는 배포 플랫폼 secret 기능을 사용한다.

## 2. 로그 원칙

- 요청 header의 `Authorization`, `Cookie`, token 값은 로그에 남기지 않는다.
- 오류 메시지에는 비밀정보, 서버 경로, DB 주소를 포함하지 않는다.
- 사용자에게는 일반 오류 메시지를 제공하고 상세 오류는 내부 로그에만 기록한다.

## 3. 교체 절차

1. 노출 또는 교체 대상 secret을 식별한다.
2. 기존 secret을 폐기한다.
3. 새 secret을 발급한다.
4. 배포 환경에 새 secret을 등록한다.
5. smoke 점검을 수행한다.
6. 교체 시간을 사고 기록 또는 변경 기록에 남긴다.

## 4. 금지 패턴

- `password = "..."` 형태의 실제 비밀번호
- `api_key = "..."` 형태의 실제 API 키
- `token = "..."` 형태의 실제 token
- 클라이언트 HTML/JS에 포함된 OAuth secret

## 5. 검증

- [ ] 저장소 정적 검사에서 secret 패턴이 발견되지 않는다.
- [ ] 배포 환경 secret은 코드와 분리되어 있다.
- [ ] secret 교체 절차가 문서화되어 있다.
