# Redis progress cache 연결 기록 - 2026-06-30

## 결론

Redis는 사건/상담의 기준 저장소가 아니라 짧은 TTL 진행 상태 캐시로만 사용한다.
기준 데이터는 계속 PostgreSQL 계열 테이블인 `chat_sessions`, `analysis_jobs`,
`analysis_job_events`에 남긴다. Redis 장애 또는 cache miss가 발생하면 API는
PostgreSQL에서 상태를 복구하고 같은 key로 다시 cache write를 시도한다.

## 적용 범위

- `analysis_job_progress:{job_id}`
  - job status
  - active node
  - progress message
  - analysis plan id
  - status counts
  - source tables
- `chat_session_state:{session_id}`
  - session status
  - current intent
  - latest job id
  - latest job status

## 정책

- policy version: `progress_cache.v1`
- 기본 TTL: 300초
- Docker Compose: `redis:7-alpine`
- Django cache backend
  - `REDIS_URL`이 있으면 `django.core.cache.backends.redis.RedisCache`
  - 없으면 local/test용 `LocMemCache`
- fallback: `postgresql`
- 원문 사용자 입력, OCR 원문, prompt, agent reasoning 전문은 cache snapshot에 넣지 않는다.

## API 노출

- `POST /api/analysis/jobs/`
  - `job.persistence.progress_cache`
  - `job.persistence.session_cache`
- `GET /api/analysis/jobs/{job_id}/`
  - `job.progress_cache`
- `GET /api/mypage/summary/?session_id=...`
  - `progress_cache`
  - `session_cache`

## 다음 단계

1. 실제 비동기 queue가 붙으면 node 실행 단계마다 같은 key로 snapshot을 갱신한다.
2. 운영 Redis에서는 eviction/TTL metric을 확인한다.
3. object storage adapter 작업과 충돌하지 않도록 report binary metadata는 cache에 넣지 않는다.
