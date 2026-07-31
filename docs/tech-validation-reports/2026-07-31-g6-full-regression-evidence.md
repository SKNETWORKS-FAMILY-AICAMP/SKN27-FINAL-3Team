# G6 전체 회귀·Release Candidate 검증 증거

> 상태: G6 GREEN / runtime RC SHA 고정 완료
> 시작 시각: 2026-07-31T18:57:35.7119708+09:00
> 기술 게이트 종료 시각: 2026-07-31T19:15:38.9407354+09:00
> 브랜치: `feat-pilot-safety-hotfix`
> 시작 SHA: `65d2fdc8b50ea55f44b5a88178095f8824a5d8f1`
> Runtime RC SHA: `631e927833a7bfead2ae5efcd318bdac99212b8a`
> upstream SHA: `65d2fdc8b50ea55f44b5a88178095f8824a5d8f1`
> 원격 `dev`: `61e0c56ba8a783423cb8a830e5d7088001e5593b`
> 실행 계획: `docs/superpowers/plans/2026-07-31-g6-full-regression-release-candidate.md`

## 1. 범위와 금지 조건

- G1~G5 핫픽스 브랜치의 로컬 전체 회귀, Django 통합, 프런트 테스트,
  production build, Compose render, 전체 diff review를 검증한다.
- `--run-live`, `--run-aws`, 유료 Agent/OpenAI/RunPod 호출을 실행하지 않는다.
- 운영 배포, secret 회전, 로그 삭제, production data 변경, 13개 운영 E2E를
  실행하지 않는다.
- 환경 변수 값, credential, PII, raw OCR, signed URL을 증거에 기록하지 않는다.

## 2. 기준점

| 항목 | 결과 |
|---|---|
| 격리 환경 | linked Git worktree, submodule 아님 |
| 작업 브랜치 | `feat-pilot-safety-hotfix` |
| feature/upstream | `65d2fdc8` / `65d2fdc8`, 일치 |
| 원격 dev | `61e0c56b`, 승인된 구현 기준과 일치 |
| 기준 worktree | G6 문서 생성 전 clean |
| Python | `3.14.3` |
| Node | `24.14.0` |
| npm | `11.9.0` |
| Docker | `29.4.3` (`055a478`) |
| Docker Compose | `v5.1.4` |

## 3. 실행 결과

| Gate | 명령 요약 | 결과 | 경고·비고 |
|---|---|---|---|
| Safety/routing | pytest 7 modules | `106 passed`, 0 failed | 기존 LangChain warning 1건 |
| Auth/ownership | pytest 7 modules | `43 passed`, 0 failed | 경고 없음 |
| Consultation/Supervisor | pytest 8 modules | `75 passed`, 0 failed | 경고 없음 |
| Polling/evidence | pytest 3 modules | `82 passed`, 0 failed | 경고 없음 |
| Operations/deployment | pytest 8 modules | `147 passed`, 0 failed | 경고 없음 |
| Agent/RAG/graph | pytest 11 modules | `191 passed`, 0 failed | 기존 LangChain warning 1건 |
| Frontend Node | `node --test *.test.js` | `66 passed`, 0 failed | 경고 없음 |
| Django chatbot | `python backend/manage.py test chatbot --verbosity 1` | 최초 RED 후 재실행 `383 tests`, `OK` | DISC-003 정렬; 기존 LangChain warning 및 의도된 fallback 로그 |
| Full pytest | `python -m pytest -q` | 최종 `1450 passed`, `37 skipped`, `4 subtests passed`, 0 failed | 기존 LangChain warning 1건; 100.60초 |
| Vite production build | `npm run build` | 성공, Vite `7.3.6`, `44 modules transformed` | `dist` ignore 상태 최종 확인 대기 |
| Local Compose | `docker compose -f docker-compose.yml config --quiet` | 성공 | 서비스 시작·pull·build 없음 |
| Pilot Compose | synthetic ignored env fixture + `config --quiet` | 최초 RED 후 GREEN | DISC-004 해결; fixture cleanup 완료 |
| Full branch review | `origin/dev` 대비 status/stat/name-status/diff-check | actionable finding 해결 후 clean | 과거 commit whitespace 3건 정리; secret·migration·dist·임시 env 혼입 없음 |

## 4. 경고 분류

- 허용된 기존 경고: `LangChainPendingDeprecationWarning` 1건.
- 신규 경고: 없음.

## 4.1 G6 발견 사항

- `DISC-003`: Django 전체 discovery에서만 수집되는 구형 fixture 2건이 최신
  production 계약과 불일치했다.
  - public law projection은 출처 없는 scalar law를 제거하지만 queue 테스트는
    scalar가 노출된다고 단정했다.
  - law adapter는 `llm_extractor` keyword를 전달하지만 non-DL smoke mock만
    `**kwargs`를 받지 않아 `TypeError`를 만들었다.
  - production 코드는 유지하고 테스트 fixture 2건만 최신 계약으로 정렬했다.
  - RED: 단독 2건 모두 실패. GREEN: 함께 `2 tests`, `OK`, 전체
    discovery `383 tests`, `OK`.
- `DISC-004`: pilot Compose가 `OPERATIONAL_LOG_GROUP` 필수 interpolation을
  요구하지만 `runtime.env.example`에 해당 키가 없어 실제 `config --quiet`가
  실패했다.
  - Compose의 모든 `${VAR:?}` 키가 template에 존재하는지 검사하는 회귀
    테스트를 추가했다.
  - template에 값 없는 secret이 아니라
    `OPERATIONAL_LOG_GROUP=INJECTED_BY_DEPLOY_SCRIPT` 계약 한 줄만 추가했다.
  - RED: missing key `OPERATIONAL_LOG_GROUP`. GREEN: 신규 `1 passed`, AWS
    pilot module `85 passed`, local/pilot Compose render 성공.

## 5. 최종 판정

- G6: GREEN
- Runtime Release Candidate SHA:
  `631e927833a7bfead2ae5efcd318bdac99212b8a`
- 원격 `dev`: 종료 확인에서도 `61e0c56b`, 승인 기준과 일치
- RC commit은 G6에서 발견한 runtime template·회귀 테스트 정렬과 전체
  branch whitespace 정리를 포함한다. 뒤따르는 문서 전용 commit은 runtime
  artifact RC를 변경하지 않는다.
- feature upstream push: 문서 전용 commit과 함께 사용자 실행 대기
- G7 운영 재배포 준비·승인: 대기
- G8 운영 재배포·smoke: 대기
- G9 배포 후 13개 E2E: 대기
