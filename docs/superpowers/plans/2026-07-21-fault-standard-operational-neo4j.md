# Fault Standard Operational Neo4j Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Export V7 as an auditable historical graph, rebuild V9 as a clean `FaultStandardOperational` graph in a temporary Neo4j instance, validate it, and prepare a same-service-name cutover without touching the current database until validation passes.

**Architecture:** A read-only exporter selects a graph namespace and writes `nodes.jsonl`, `relationships.jsonl`, and a SHA-256 manifest. A separate importer transforms only the V9 export into role labels plus `FaultStandardOperational`, adds schema/source metadata and constraints, and never imports V7. A validator checks counts, labels, identity, required Rule relationships, JSON properties, and Runtime query compatibility before cutover.

**Tech Stack:** Python 3.14, Neo4j Python driver, Neo4j 5 Community, pytest, Docker Compose.

## Global Constraints

- Never run destructive Cypher against the current `fault-standard-neo4j` before V7 export and full rollback evidence exist.
- Do not place Neo4j graph backups in `etl/fault_cases/evaluation/fault_standard/`; that directory remains evaluation-only.
- Preserve `Complete30V7` and `Complete30V9` evaluation/history documents; only the operational graph namespace changes.
- Do not modify `skn27-neo4j` or any existing legal Neo4j volume.
- The final service endpoint remains `fault-standard-neo4j:7687` so Runtime configuration does not change.
- Expected source counts are V7 1,718 nodes/1,441 relationships and V9 7,815 nodes/13,196 relationships.

---

### Task 1: Add graph export library and tests

**Files:**
- Create: `etl/fault_cases/rag_runtime/database/graph_export.py`
- Create: `etl/fault_cases/rag_runtime/database/tests/test_graph_export.py`

**Interfaces:**
- `export_graph(session, namespace_label: str, output_dir: Path) -> dict[str, object]`
- `write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> str`
- `sha256_file(path: Path) -> str`

- [ ] **Step 1: Write failing tests** for deterministic JSONL output, SHA-256 manifest fields, and rejection of unsafe namespace labels.
- [ ] **Step 2: Run `python -m pytest -q etl/fault_cases/rag_runtime/database/tests/test_graph_export.py`** and confirm the tests fail because the module does not exist.
- [ ] **Step 3: Implement the exporter** with safe identifier validation, explicit node/relationship properties, stable key ordering, UTF-8 JSONL, and manifest counts/hashes.
- [ ] **Step 4: Run the focused tests** and confirm all pass.
- [ ] **Step 5: Commit** `feat: add auditable Neo4j graph exporter`.

### Task 2: Export V7 history and V9 source graph

**Files:**
- Modify: none in repository; generated archives live under `C:/dev/project/SKN27-RAG-rescue/etl/fault_cases/HISTORY_LOCAL/neo4j_archives/`.

**Interfaces:**
- Command: `python -m etl.fault_cases.rag_runtime.database.graph_export --label Complete30V7 --output-dir <v7-dir>`
- Command: `python -m etl.fault_cases.rag_runtime.database.graph_export --label Complete30V9 --output-dir <v9-dir>`

- [ ] **Step 1:** Read the current container credentials without printing them and run the exporter against `bolt://localhost:7688`.
- [ ] **Step 2:** Write V7 to `C:/dev/project/SKN27-RAG-rescue/etl/fault_cases/HISTORY_LOCAL/neo4j_archives/complete30_v7/`.
- [ ] **Step 3:** Write V9 staging input to `C:/dev/project/SKN27-RAG-rescue/etl/fault_cases/HISTORY_LOCAL/neo4j_archives/complete30_v9_source/`.
- [ ] **Step 4:** Verify manifests show exactly 1,718/1,441 and 7,815/13,196; stop if either differs.

### Task 3: Add operational importer and tests

**Files:**
- Create: `etl/fault_cases/rag_runtime/database/loaders/import_fault_standard_operational_graph.py`
- Create: `etl/fault_cases/rag_runtime/database/tests/test_import_fault_standard_operational_graph.py`

**Interfaces:**
- `transform_node(row: dict[str, object], schema_version: int, snapshot_id: str) -> dict[str, object]`
- `operational_labels(source_labels: list[str]) -> list[str]`
- `import_graph(session, backup_dir: Path, snapshot_id: str, schema_version: int) -> tuple[int, int]`

- [ ] **Step 1:** Write failing tests for V9 label transformation, removal of `Complete30V9`/`V9Import`, metadata insertion, and preservation of role labels/properties.
- [ ] **Step 2:** Run the focused tests and confirm the intended failures.
- [ ] **Step 3:** Implement fresh-graph import with a `FaultStandardOperational` uniqueness constraint on `source_legacy_element_id`, validator-enforced uniqueness for `Rule.rule_id` (Neo4j Community does not accept a multi-label uniqueness constraint), and relationship MERGE by source relationship ID.
- [ ] **Step 4:** Run focused tests and confirm all pass.
- [ ] **Step 5:** Commit `feat: add fault standard operational graph importer`.

### Task 4: Add structural validator and Runtime label contract

**Files:**
- Create: `etl/fault_cases/rag_runtime/database/validation/validate_fault_standard_operational_graph.py`
- Create: `etl/fault_cases/rag_runtime/database/validation/tests/test_validate_fault_standard_operational_graph.py`
- Create: `etl/fault_cases/rag_runtime/fault_standard/graph_schema.py`
- Modify: `etl/fault_cases/rag_runtime/fault_standard/retriever.py`
- Modify: `etl/fault_cases/rag_runtime/fault_standard/v9_graph_adapter.py`
- Modify: `etl/fault_cases/rag_runtime/fault_standard/tests/test_graph_schema.py`

**Interfaces:**
- `EXPECTED_NODE_COUNT = 7815`
- `EXPECTED_RELATIONSHIP_COUNT = 13196`
- `validate_report(session) -> dict[str, object]`
- `OPERATIONAL_LABEL = "FaultStandardOperational"`

- [ ] **Step 1:** Write failing tests for expected constants, required query label generation, and PASS/FAIL report behavior.
- [ ] **Step 2:** Run focused tests and confirm failures.
- [ ] **Step 3:** Implement validator checks for counts, forbidden labels, duplicate/missing IDs, required Rule paths, missing `record_json`, isolated nodes, and constraints.
- [ ] **Step 4:** Update Runtime queries to use `OPERATIONAL_LABEL` and rename only the adapter module’s public semantics; retain evaluation folder names.
- [ ] **Step 5:** Run focused tests, `compileall`, and the existing RAG test suite.
- [ ] **Step 6:** Commit `feat: validate and query operational Neo4j graph`.

### Task 5: Build and validate temporary operational container

**Files:**
- Create: `etl/fault_cases/rag_runtime/database/README.md` section describing the exact migration commands.
- Modify: `docker-compose.yml` only if an explicit temporary volume override is needed; preserve the final service name and current default volume until cutover.

- [ ] **Step 1:** Start a temporary Neo4j 5 Community container with an explicit `fault_standard_neo4j_operational_next` volume and a temporary host port.
- [ ] **Step 2:** Import only `complete30_v9_source` into the temporary database.
- [ ] **Step 3:** Run the structural validator and save its JSON report beside the rescue archive.
- [ ] **Step 4:** Run Runtime smoke queries against the temporary database with the operational label.
- [ ] **Step 5:** Stop and preserve the temporary container if any check fails; do not touch the current container.

### Task 6: Cut over the service name and verify rollback evidence

**Files:**
- Modify: `docker-compose.yml` volume reference only after Task 5 PASS.
- Modify: Runtime environment/config only if the service name or database name changes.

- [ ] **Step 1:** Capture a final current-container and volume inventory; confirm V7 archive manifest and V9 staging manifest hashes.
- [ ] **Step 2:** Stop the current `fault-standard-neo4j` service and retain its old volume under an explicit archive name.
- [ ] **Step 3:** Attach the validated operational volume to the service name `fault-standard-neo4j`.
- [ ] **Step 4:** Run the validator, Runtime smoke test, and targeted RAG tests after cutover.
- [ ] **Step 5:** Leave the old volume recoverable until the user confirms cleanup; do not delete it in the same step as cutover.
- [ ] **Step 6:** Commit only repository changes and record the cutover report; generated DB volumes remain outside Git.

### Task 7: Final verification

- [ ] **Step 1:** Run `python -B -m pytest -q -p no:cacheprovider etl/fault_cases/rag_runtime etl/fault_cases/src --disable-warnings`.
- [ ] **Step 2:** Run `python -B -m compileall -q etl/fault_cases/rag_runtime etl/fault_cases/src`.
- [ ] **Step 3:** Run the operational Neo4j validator and inspect its full JSON report.
- [ ] **Step 4:** Confirm `git status --short` contains only intended repository changes and no generated graph backup.
