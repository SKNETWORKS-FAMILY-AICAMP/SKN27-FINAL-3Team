# Phase 2-D5 ReportReadQueries Application Boundary

## Authority

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base: `37acecef69e14fe1540cd15918cffc533cb9dd9c`
- Branch: `refactor/phase-02-d5-report-read-queries-use-case`
- Reviewed Runtime Head: `41f7bd6bd80238c66b5e286d3eea8145cfc917fd`
- PR: `#409`
- State: `OPEN`
- Draft: `true`
- Merge: `NOT_PERFORMED`

This receipt records the reviewed runtime head only. A docs-only metadata commit must not introduce a self-referential final SHA.

## Scope and Boundary

- `GET /api/reports/` and `GET /api/reports/<report_id>/` delegate through `app/application/reports/read_queries.py`.
- `ListReportsQuery` and `GetReportDetailQuery` derive authority only from `auth_context`, preserve owner/session filtering and detail authorization, then use existing public projections.
- `POST /api/reports/`, Report download, D3 confirmation, persistence schema, worker flow, frontend, OpenAPI, renderer, and storage are unchanged.

## Independent Review Evidence

- D5 characterization plus existing Report contract: `18 passed`
- Existing `chatbot.test_report_api_contract`: `11 passed`
- B1~D4 Django regression: `61 passed`
- D5 sensitivity: `5/5 AssertionError`; source restored; clean tree
- D5 sensitivity contract: `3 passed`
- Django check, Ruff/F401, OpenAPI, frontend route, and `git diff --check`: passed

## Current Head CI

- production-gate run: `32146900478` — `success`
- offline-verification job: `95742751402` — `success`
- compose-integration job: `95744785737` — `success`
- regression-signal run/job: `32146900349 / 95742751002` — `success`
- D5 boundary, D5 sensitivity, artifact upload, full Django, import guard, previous B1/B2/B3/D1/D2/D3/D4 gates, OpenAPI, frontend route, and Docker smoke: `success`

## RED Evidence Limitation

- RED temporal ordering from Git commit history: `NOT_INDEPENDENTLY_PROVABLE`
- The RED tests and implementation are together in `41f7bd6bd80238c66b5e286d3eea8145cfc917fd`; history was not rewritten.
- RED mechanism: `INDEPENDENTLY_REPRODUCED_ON_BASE`
  - List: legacy HTTP behavior completes, `execute_list_reports` is called `0` times, then `assert_called_once()` raises `AssertionError`.
  - Detail: legacy HTTP behavior completes, `execute_get_report_detail` is called `0` times, then `assert_called_once()` raises `AssertionError`.

## Deferred and Audit

- Production DB audit: `NOT_EXECUTED`
- `POST /api/reports/`, Report download, renderer/storage changes, and Phase 3 redesign: deferred/out of scope.

## P2 Status

- P0: `0`
- P1: `0`
- P2: `REMEDIATED_PENDING_DELTA_REVIEW`