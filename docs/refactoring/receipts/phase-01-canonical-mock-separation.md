# Phase 1 Canonical/Mock Runtime Separation Receipt

## 기준

- Base SHA: `9f05e8b67509c0a1f06bc39d631d6a7c94044a90`
- Branch: `refactor/phase-01-canonical-mock-separation`
- 접근: test boundary first separation

## 변경 요약

- canonical import에서 Explicit Mock service와 mock agent dispatch를 제거했다.
- neutral attachment staging/history event contract를 추가하고 local staging을 Local Infrastructure Adapter에 연결했다.
- 기본 URLConf는 `/api/mock/`를 등록하지 않으며, 별도 `config.mock_urls`는 enable flag와 `DEBUG=True`에서만 동작한다.
- canonical persistence/public surface에서 mock marker를 제거했고 `AnalysisJob.mock_scenario` physical column은 유지했다.

## 검증 및 위험

- import boundary, URL isolation, canonical negative reachability, persistence marker, frontend surface gate를 추가했다.
- Phase 0 core, deterministic, queued follow-up, sensitivity, OpenAPI, frontend test/build 게이트를 유지한다.
- Production DB audit는 실행하지 않았고 physical column 제거는 defer한다.
- 로컬 Docker/Compose gate는 Docker Desktop daemon 미실행으로 `NOT_EXECUTED`이며, PR CI의 blocking Docker/Compose job으로 재확인한다.
- rollback은 Phase 1 commit을 역순 revert한다. migration과 public production mock route가 없으므로 schema rollback은 필요하지 않다.

## 후속 범위

Phase 2 View/Application Use Case 분리와 Phase 3 queue/repository/storage/bounded-context 재설계는 이 PR에서 수행하지 않는다.
