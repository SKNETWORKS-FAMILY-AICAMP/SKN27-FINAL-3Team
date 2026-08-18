# Phase 2-D5 ReportReadQueries Use Case

## Scope

- `GET /api/reports/` and `GET /api/reports/<report_id>/` now delegate through `app/application/reports/read_queries.py`.
- `POST /api/reports/`, report download, D3 confirmation, persistence schema, worker flow, frontend, and OpenAPI are unchanged.

## Boundary

`ListReportsQuery` and `GetReportDetailQuery` derive the subject only from `auth_context`, apply guest/login policy, use the trusted owner for list filtering, authorize detail access before projection, and return only `report_query_service` public DTOs.

## Local verification

- `python backend/manage.py test chatbot.test_phase_02_report_read_queries_use_case chatbot.test_report_api_contract --verbosity 1`: 18 passed
- `python -m pytest -p no:cacheprovider test/test_phase_02_d5_sensitivity_runner.py -q`: 3 passed
- `python scripts/refactoring/verify_phase_02_d5_report_read_queries_test_sensitivity.py`: pass; five mutations failed by `AssertionError`; `working_tree_unchanged: true`
- `python backend/manage.py check`: passed

## CI

`production-gate.yml` uploads `phase-02-d5-sensitivity-evidence` and runs both the boundary and unused-import gates. PR and CI identifiers are recorded after the draft PR is created.