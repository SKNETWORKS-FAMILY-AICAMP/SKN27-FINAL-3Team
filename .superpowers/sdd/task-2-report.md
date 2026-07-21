# Task 2 report: Supervisor Agent contract

## Changed files

- `etl/fault_cases/rag_runtime/agent_runtime/supervisor_input.py`
  - Normalizes `accident_facts`, retaining `structured_facts` as a legacy input alias.
  - Validates the optional `required_domains` request list.
- `etl/fault_cases/rag_runtime/agent_runtime/agent.py`
  - Dispatches only selected domain handlers; defaults to all three supported domains.
  - Returns a contract-shaped failed response for invalid requests.
- `etl/fault_cases/rag_runtime/agent_runtime/supervisor_output.py`
  - Aggregates statuses as success/all-success, failed/all-failed, partial/otherwise.
- `etl/fault_cases/rag_runtime/agent_runtime/tests/test_agent_contract.py`
  - Adds targeted normalization, dispatch, aggregate-status, and invalid-input tests.

## TDD evidence

- RED: `python -B -m pytest etl\\fault_cases\\rag_runtime\\agent_runtime\\tests\\test_agent_contract.py -q`
  - Observed five expected failures: missing `accident_facts`, all-handler dispatch, inclusion of an unrequested domain, all-failed reported as partial, and invalid input returning a non-contract error.
- GREEN: the same command was rerun after implementation.
  - Result: `5 passed`.
- Verification: `git diff --check` exited cleanly.

## Commit

- Implementation commit: `a2e2587e8a3e86239208de68998c12c99259fda8` (`fix(rag): align supervisor agent contract`).

## Concerns

- None. The runtime continues to support only its existing three service domains (`fault_standard`, `precedent`, and `review_case`); unsupported requested domains are treated as invalid input and receive the contract-compatible failed response.
