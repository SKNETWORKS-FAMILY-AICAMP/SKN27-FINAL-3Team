# Phase 0 Refactoring Baseline

- 기준 SHA: `198efeba3cabacc3a977cfcaf2f8d7e06fd47104`
- 작성 기준일: 2026-08-08
- 권위 우선순위: runtime 코드, Dockerfile, `docker-compose.yml`, CI workflow, package metadata, 그 다음 설계 문서.

이 디렉터리는 Phase 0의 현재 동작 baseline이다. Phase 1의 Canonical·Mock 구조 변경이나 production refactor를 선언하지 않는다.

| 문서 | 역할 |
|---|---|
| `phase-00/current-runtime-architecture.md` | 현재 request, worker, persistence, CI 경계 |
| `phase-00/runtime-versions.md` | Docker·CI·package 근거 버전 |
| `phase-00/active-contracts.md` | 현재 runtime·test-only·historical contract 분류 |
| `phase-00/state-ownership-baseline.md` | PostgreSQL, metadata, Redis, browser, object storage ownership baseline |
| `phase-00/production-mock-test-double-matrix.md` | production, explicit mock, test double 구분 |
| `phase-00/characterization-test-selection.md` | blocking selector의 기존 test 분류와 gap |
| `phase-00/verification-matrix.md` | A~G acceptance coverage와 CI selector |
| `phase-00/migration-status.md` | Phase 0~9 migration status |

`receipts/phase-00-receipt.md`는 구현·검증·CI 결과가 실제 diff와 일치할 때만 작성한다.
