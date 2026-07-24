# 2차 고도화 — CloudFront 파일럿 프런트엔드 전달 설계

## 범위와 시점

이 설계는 현재 EC2 기반 첫 운영 배포를 완료한 뒤 진행하는 2차 고도화다. 이번 첫
배포의 RDS, Django API, Worker, Redis, Clean/Quarantine S3, OpenAI, RunPod 경로를
변경하지 않는다.

2차 목표는 React/Vite 정적 프런트엔드를 EC2 Nginx에서 분리해 비공개 S3와
CloudFront로 전달하면서 `/api/*`만 기존 EC2 HTTPS origin으로 전달하는 것이다.
ALB, NAT Gateway, ECS/Fargate는 추가하지 않는다.

## 목표 구조

```text
사용자
  -> CloudFront
       -> 기본 동작: private S3의 React/Vite dist
       -> /api/*: HTTPS로 현재 EC2 origin
                    -> Caddy -> HAProxy -> Django/Worker/Redis
                                      -> RDS, Clean/Quarantine S3,
                                         OpenAI, RunPod
```

공개 진입점은 CloudFront 하나로 통일한다. 정적 프런트엔드와 API는 같은 공개
origin을 사용하고 브라우저는 상대 경로 `/api/...`로 호출한다.

## Terraform 경계

`infra/terraform-pilot`에 파일럿 범위의 구성만 추가한다. 전체 운영용
`infra/terraform`의 ALB·NAT·ECS·WAF 구성을 그대로 복사하지 않는다.

책임별 후보 파일은 다음과 같다.

- `frontend_delivery.tf`: private S3, encryption, versioning, public access block,
  OAC, bucket policy, CloudFront distribution, cache/origin request policies
- `dns.tf`: 선택적인 Route 53 alias, us-east-1 ACM provider alias와 validation
- `monitoring.tf`: CloudFront 4xx/5xx 알람과 기존 SNS 재사용
- `variables.tf`: 도메인, 인증서, 로그, IPv6, 가격 등급과 기능 토글
- `outputs.tf`: distribution ID·도메인, bucket 이름, 필요한 외부 DNS 레코드

실제 AWS 생성·변경은 `terraform plan`을 검토한 뒤 별도 승인으로 실행한다.

## S3와 정적 자산

- 전용 S3 bucket은 Block Public Access를 모두 켜고 SSE-S3 이상으로 암호화한다.
- versioning을 켜고 CloudFront OAC만 `GetObject`할 수 있도록 bucket policy를
  제한한다.
- 해시가 포함된 `/assets/*`는
  `Cache-Control: public,max-age=31536000,immutable`로 배포한다.
- `index.html`은 마지막에 업로드하고 `Cache-Control: no-cache`를 사용한다.
- 배포마다 `/*` 전체 invalidation을 기본으로 실행하지 않고 `/index.html`과 실제
  최소 rewrite 경로만 무효화한다.
- source map은 기본 비공개이며, 공개가 필요하면 별도 보안 검토를 거친다.

## CloudFront 동작

### 기본 정적 origin

- default root object는 `index.html`이다.
- viewer HTTP는 HTTPS로 redirect한다.
- 최소 TLS 1.2 정책을 사용한다.
- HTTP/2 이상을 사용하고 IPv6는 DNS·운영 영향 검토 후 선택한다.

### API origin

- `/api/*`는 기존 EC2의 HTTPS origin으로 전달한다.
- CloudFront managed caching-disabled 정책을 우선 사용하고 TTL은 0으로 둔다.
- GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE를 허용한다.
- 실제 계약에서 사용하는 Authorization, Content-Type, cookie, query string,
  guest/session header만 origin에 전달한다.
- API의 401/403/404와 `Set-Cookie`를 그대로 보존하며 정적 SPA 응답으로 바꾸지
  않는다.
- CORS, CSRF, secure cookie, SameSite, `X-Forwarded-Proto`, trusted proxy CIDR을
  CloudFront 경계에 맞춰 다시 검증한다.

## SPA deep-link

CloudFront 전체 403/404를 `index.html`로 바꾸지 않는다. 그러면 API 오류와 실제
정적 파일 누락도 React 화면으로 변질된다.

viewer request CloudFront Function을 사용해 다음 조건을 모두 만족하는 프런트엔드
경로만 `/index.html`로 rewrite한다.

- `/api/`로 시작하지 않는다.
- 마지막 path segment에 파일 확장자가 없다.
- React Router가 소유하는 공개 route다.

`.js`, `.css`, `.png`, `.svg`, `.woff2` 등 실제 정적 파일 누락은 정상 404로
유지한다.

## 도메인과 인증서

권장 구조는 다음과 같다.

- `app.<owned-domain>`: CloudFront 공개 도메인
- `origin.<owned-domain>`: EC2 Elastic IP와 Caddy 인증서용 origin 도메인

CloudFront viewer 인증서는 us-east-1 ACM에서 관리한다. Route 53을 사용하면
provider alias와 DNS validation을 Terraform으로 관리한다. 외부 DNS를 사용하면
정확한 CNAME/TXT 레코드를 output으로 제공하고 사람이 입력한다.

DuckDNS는 첫 배포에 유지할 수 있지만, CloudFront custom domain과 안정적인
origin TLS 분리를 위해서는 소유 도메인이 필요하다. 도메인 구매와 DNS 전환은
사람 게이트로 둔다.

## EC2 origin 보호

비용과 운용 복잡도를 고려해 다음 이중 경계를 목표로 한다.

1. EC2 security group의 443 ingress를 AWS 관리형 CloudFront origin-facing
   prefix list로 제한한다.
2. CloudFront가 private origin header를 보내고 Caddy/HAProxy가 상수 시간 비교로
   검증한다.

origin header 값은 Git과 CloudFront 로그에 남기지 않는다. Terraform state,
state bucket 접근, SSM SecureString, EC2 runtime env 권한을 함께 제한한다.
장애 시에는 제한된 관리 경로만 임시로 열 수 있고 광범위한 `0.0.0.0/0` 예외를
상시 유지하지 않는다.

## OAuth와 세션

CloudFront 도메인으로 전환할 때 다음 값을 하나의 canonical origin으로 맞춘다.

- Google Authorized JavaScript Origin
- Google Redirect URI
- Django allowed hosts
- CSRF trusted origins
- CORS allowed origins
- secure cookie domain·SameSite 정책

로그인 전 guest session, 로그인 후 소유권 전환, 새로고침, 직접 deep-link 진입,
로그아웃, 다른 사용자 자료 접근 차단을 실제 브라우저로 검증한다.

## 배포와 롤백

프런트엔드 배포는 source 확인, production build, 이전 dist artifact 보관,
해시 asset 선업로드, `index.html` 마지막 업로드, 최소 invalidation, distribution
배포 완료 대기, smoke 순서로 진행한다.

실패하면 이전 versioned artifact를 복원하고 `index.html`을 다시 무효화한다.
CloudFront/DNS 롤백은 TTL과 기존 EC2 직접 진입점 복구 절차를 별도로 검증한다.
RDS와 첨부파일·리포트 S3는 이 작업에서 삭제하거나 교체하지 않는다.

## 비용과 관측

- CloudFront는 무조건 무료가 아니며 계정의 Free Plan/무료 사용량과 요청·전송량
  한도를 plan 직전 다시 확인한다.
- 추가 비용 요인은 요청 수, 인터넷 데이터 전송, S3 GET·저장, Route 53/도메인,
  CloudFront 로그, 선택적 WAF다.
- 실시간 access log는 기본 활성화하지 않고 표준 지표와 제한된 로그부터 사용한다.
- 기존 SNS와 Budget을 재사용하고 중복 topic·budget을 만들지 않는다.
- CloudFront request·4xx·5xx·origin latency, S3 AccessDenied, 배포 실패를
  모니터링한다.
- WAF는 비용과 위협 모델을 별도 비교한 뒤 후속 선택 항목으로 둔다.

## 완료 게이트

- Terraform fmt, validate, 계약 테스트, plan 검토
- Vite production build와 Docker Compose config 검증
- private S3·OAC·bucket policy 확인
- HTTPS, 정적 asset cache hit, `index.html` 단기 캐시 확인
- SPA deep-link 새로고침과 누락 asset 404 확인
- API 무캐시, OPTIONS, POST, 401/403/404 보존
- 상담, OAuth, 첨부 업로드, RunPod 분석, 리포트 조회·다운로드 브라우저 QA
- EC2 직접 접근 우회 차단 확인
- CloudWatch·Budget 영향 확인
- 프런트엔드 artifact 롤백과 DNS 롤백 연습

## 사람 작업

- 소유 도메인과 public/origin 하위 도메인 확정
- 외부 DNS 레코드 입력 또는 Route 53 구매 승인
- ACM DNS·이메일 소유권 확인
- Google OAuth Console의 origin/redirect 변경
- CloudFront Free Plan/무료 사용량 확인
- 실제 `terraform apply`와 DNS 전환 최종 승인
