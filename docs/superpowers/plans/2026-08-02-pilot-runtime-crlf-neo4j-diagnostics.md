# Pilot Runtime CRLF and Neo4j Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the exact precedent-seed runtime preflight platform-independent, restore the private recovery stage, and capture the first credential-safe Neo4j graph-load exception with its phase and batch.

**Architecture:** Normalize AWS CLI runtime text to LF before applying the existing exact single-line seed regex. Keep the production graph loader unchanged until an isolated private-stage diagnostic wrapper identifies the failing Neo4j boundary and error code. Preserve the failed diagnostic stage and logs; do not create release evidence, descriptor, complete marker, or a public `current` link.

**Tech Stack:** PowerShell 7.2+, Python 3/pytest, AWS CLI/SSM, Docker Compose, Django management commands, Neo4j Python driver.

## Global Constraints

- Work from branch `feat-pilot-runtime-crlf-neo4j-diagnostics` based on `origin/dev` commit `76c713ec`.
- Exact release tag: `76c713ec92d6`.
- Exact RAG manifest SHA-256: `9bb155067bdbff2792ff1ceb17002b99431454b31c52029f7cee8af75f2294ac`.
- Exact precedent seed version: `sha256:af0a4a40f983dcdaeaaeb57e54962a514338b8644c33a6a807f1e6214878b2db`.
- The parser must still require exactly one lowercase `sha256:` value with 64 lowercase hexadecimal characters.
- Never print the runtime SecureString, credentials, source document text, full Cypher row payloads, or provider secrets.
- Do not call an embedding/provider API during parser verification or Neo4j diagnosis.
- Do not create or change `/opt/skn27-pilot/current`.
- Do not run final cutover, paid live smoke, 600-second acceptance, or the 13 E2E scenarios in this plan.
- A diagnostic failure must preserve the private release directory, stage containers, and Neo4j data/log volumes for inspection.

---

### Task 1: Reproduce and fix the Windows CRLF false rejection

**Files:**
- Modify: `test/test_aws_pilot_infrastructure.py`
- Modify: `deploy/aws-pilot/Deploy-Pilot.ps1:105-124`

**Interfaces:**
- Consumes: decrypted SSM `Parameter.Value` returned as a PowerShell string.
- Produces: `Normalize-RuntimeEnvText([string]$Content) -> string` and the unchanged return contract `Get-VerifiedPrecedentSeedVersion(...) -> string` with the exact `sha256:` prefix plus 64 lowercase hexadecimal characters.

- [ ] **Step 1: Write the failing source-contract regression test**

Add a focused test next to the existing precedent seed deployment assertions:

```python
def test_deploy_normalizes_runtime_line_endings_before_precedent_seed_regex():
    deploy = _read_deploy("Deploy-Pilot.ps1")
    helper = deploy.index("function Normalize-RuntimeEnvText")
    read_parameter = deploy.index("function Get-VerifiedPrecedentSeedVersion")
    normalize = deploy.index("Normalize-RuntimeEnvText $parameterValue", read_parameter)
    pattern = deploy.index(
        'PRECEDENT_NEWPLUSPLUS_SEED_VERSION=(sha256:[0-9a-f]{64})',
        read_parameter,
    )

    assert helper < read_parameter < normalize < pattern
    assert '.Replace("`r`n", "`n").Replace("`r", "`n")' in deploy[helper:read_parameter]
    assert "$matches.Count -ne 1" in deploy[pattern:]
```

This test intentionally requires normalization before the strict regex and retains the single-match gate.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py::test_deploy_normalizes_runtime_line_endings_before_precedent_seed_regex -q
```

Expected: FAIL because `Normalize-RuntimeEnvText` and its call do not exist.

- [ ] **Step 3: Add a behavior-level PowerShell fixture check before production code**

Run this local fixture with the desired parsing contract, not AWS:

```powershell
$expected = "sha256:af0a4a40f983dcdaeaaeb57e54962a514338b8644c33a6a807f1e6214878b2db"
$fixtures = @{
  lf = "A=1`nPRECEDENT_NEWPLUSPLUS_SEED_VERSION=$expected`nB=2`n"
  crlf = "A=1`r`nPRECEDENT_NEWPLUSPLUS_SEED_VERSION=$expected`r`nB=2`r`n"
  duplicate = "PRECEDENT_NEWPLUSPLUS_SEED_VERSION=$expected`r`nPRECEDENT_NEWPLUSPLUS_SEED_VERSION=$expected`r`n"
  malformed = "PRECEDENT_NEWPLUSPLUS_SEED_VERSION=INJECTED_BY_DATABASE_MAINTENANCE`r`n"
}
$pattern = "(?m)^PRECEDENT_NEWPLUSPLUS_SEED_VERSION=(sha256:[0-9a-f]{64})$"
foreach ($name in $fixtures.Keys) {
  $normalized = $fixtures[$name].Replace("`r`n", "`n").Replace("`r", "`n")
  $count = [regex]::Matches($normalized, $pattern).Count
  if ($name -in @('lf', 'crlf')) { if ($count -ne 1) { throw "$name must pass" } }
  else { if ($count -eq 1) { throw "$name must fail" } }
}
```

Expected: exit `0`; LF and interior CRLF pass, duplicate and malformed fixtures fail the exact-one contract.

- [ ] **Step 4: Implement the minimal normalization**

Add immediately before `Get-VerifiedPrecedentSeedVersion`:

```powershell
function Normalize-RuntimeEnvText([string]$Content) {
    return $Content.Replace("`r`n", "`n").Replace("`r", "`n")
}
```

Then normalize the retrieved value only after `Assert-LastExitCode` and before regex matching:

```powershell
$parameterValue = Normalize-RuntimeEnvText $parameterValue
$pattern = "(?m)^PRECEDENT_NEWPLUSPLUS_SEED_VERSION=(sha256:[0-9a-f]{64})$"
```

Do not relax the regex, change the error text, or log parameter contents.

- [ ] **Step 5: Run focused tests and PowerShell parsing**

Run:

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py::test_deploy_normalizes_runtime_line_endings_before_precedent_seed_regex -q
pwsh -NoProfile -Command '$tokens=$null; $errors=$null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path "deploy/aws-pilot/Deploy-Pilot.ps1"),[ref]$tokens,[ref]$errors) > $null; if($errors.Count){$errors | Format-List | Out-String | Write-Error; exit 1}'
```

Expected: pytest PASS and PowerShell parser exit `0`.

- [ ] **Step 6: Run the deployment-contract regression group**

Run:

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py test/test_deployment_readiness_artifacts.py test/test_codebuild_pilot_contract.py -q
```

Expected: all tests PASS.

- [ ] **Step 7: Commit the parser fix**

```powershell
git add deploy/aws-pilot/Deploy-Pilot.ps1 test/test_aws_pilot_infrastructure.py
git diff --cached --check
git commit -m "fix: normalize pilot runtime line endings"
```

---

### Task 2: Recreate and verify the private initial-recovery stage

**Files:**
- Use: `deploy/aws-pilot/Deploy-Pilot.ps1`
- Use: `C:\tmp\skn27-pilot-runtime-oauth.env`
- Use: `C:\tmp\SKN27-origin-dev-deploy\infra\terraform-pilot`

**Interfaces:**
- Consumes: the verified local runtime candidate, exact release images, and exact manifest SHA.
- Produces: `/opt/skn27-pilot/releases/76c713ec92d6` with the exact `.initial-rag-bootstrap.staged` marker and four healthy private services.

- [ ] **Step 1: Re-run local preflight without mutating the stage on parser failure**

Run the focused tests from Task 1 and confirm the worktree contains only intentional changes. Then run:

```powershell
git status --short
```

Expected: clean after the parser commit.

- [ ] **Step 2: Stage the exact release without public cutover**

Run:

```powershell
pwsh -File .\deploy\aws-pilot\Deploy-Pilot.ps1 `
  -RuntimeEnvFile "C:\tmp\skn27-pilot-runtime-oauth.env" `
  -TerraformDirectory "C:\tmp\SKN27-origin-dev-deploy\infra\terraform-pilot" `
  -ReleaseTag "76c713ec92d6" `
  -ExpectedRagSeedManifestSha256 "9bb155067bdbff2792ff1ceb17002b99431454b31c52029f7cee8af75f2294ac" `
  -SkipBuild `
  -StageForInitialRagBootstrap `
  -SsmTimeoutSeconds 1800
```

Expected: `Pilot release 76c713ec92d6 staged private services for initial RAG bootstrap; no public current release was promoted.`

- [ ] **Step 3: Verify exact private-stage invariants with a redacted SSM check**

The check must assert and output only booleans/counts for:

```text
current_link=false
stage_marker_exact=true
running_redis=true
running_clamav=true
running_law_neo4j=true
running_backend=true
complete_marker_present=false
evidence_present=false
descriptor_present=false
```

Expected: every invariant matches exactly. Stop if any value differs.

---

### Task 3: Run a credential-safe phase and batch diagnostic of the Neo4j load

**Files:**
- Generate temporarily: `%TEMP%\skn27-legal-graph-diagnostic-{GUID}.py`
- Generate temporarily: `%TEMP%\skn27-legal-graph-runner-{GUID}.sh`
- Use unchanged: `backend/chatbot/management/commands/load_legal_graph_seed.py`
- Use unchanged: `etl/legal/export_neo4j.py`

**Interfaces:**
- Consumes: the exact S3 bundle and private stage from Task 2.
- Produces: a whitelist-only diagnostic record containing phase, batch index, batch row count, exception class, Neo4j error/status code, and redacted message.

- [ ] **Step 1: Generate the diagnostic Python wrapper locally**

The wrapper must import the real bundle/seed and Neo4j functions, classify queries without printing rows, and replace `run_batches` only inside the diagnostic process:

```python
def phase_for_query(query: str) -> str:
    normalized = " ".join(query.split())
    if "MERGE (source:LegalSource" in normalized:
        return "sources"
    if "MERGE (version:LawVersion" in normalized:
        return "versions"
    if "MERGE (chunk:LawChunk" in normalized:
        return "chunks"
    if "MERGE (fromNode)-[rel:" in normalized:
        return "relations"
    return "unknown_batch"


def diagnostic_run_batches(session, query, rows, batch_size):
    phase = phase_for_query(query)
    for index in range(0, len(rows), batch_size):
        batch = rows[index:index + batch_size]
        try:
            session.run(query, rows=batch).consume()
        except Exception as exc:
            emit_failure(phase, index // batch_size, len(batch), exc)
            raise
    emit_pass(phase, (len(rows) + batch_size - 1) // batch_size, len(rows))
```

`emit_failure` must whitelist `type(exc).__name__`, `exc.code`, and `exc.gql_status`. Its message sanitizer must replace the actual Neo4j URI, user, password, and any URI/userinfo pattern before truncating to 500 characters. It must never serialize `rows`, the runtime environment, or source text.

- [ ] **Step 2: Wrap non-batch phases explicitly**

Use the real driver and emit start/pass/failure for these exact boundaries:

```text
connectivity
constraints
clear
sources
versions
chunks
relations
hints
metadata
```

Call the real `load_and_validate_rag_seed_manifest`, `build_law_graph_seed`, `create_constraints`, `_clear_legal_graph`, `import_law_graph_seed`, `import_hint_terms`, and `_write_dataset_metadata`. Do not call `execute_legal_graph_seed_load`, because its catch-all handler deletes the original exception.

- [ ] **Step 3: Validate the wrapper offline before upload**

Run:

```powershell
python -m py_compile $DiagnosticPythonPath
```

Then scan it:

```powershell
rg -n "print\(.*password|os\.environ|rows=|chunk_text|provision_text|normalized_text" $DiagnosticPythonPath
```

Expected: compilation succeeds; the scan shows no output statement for secrets or payloads. `rows=` may appear only in the real `session.run` call, never in diagnostic serialization.

- [ ] **Step 4: Download and verify the exact bundle on the private host**

The runner must:

1. acquire `/var/lock/skn27-pilot-maintenance.lock`;
2. assert no public `current` link;
3. assert the exact initial-stage marker;
4. download only from the exact versioned S3 prefix;
5. verify the manifest SHA with `sha256sum -c`;
6. mount the bundle read-only into the existing `rag-loader` image;
7. copy the diagnostic wrapper read-only into that one-off container.

Do not create `.production-rag-seed.complete`, evidence, or a descriptor.

- [ ] **Step 5: Execute the diagnostic once and preserve the stage**

Run the wrapper with the exact dataset version:

```text
sha256:8e5964db77c3b69e16ec046b02f606f734a20e741f930a0b874aa320182c2ea3
```

Use batch size `500`, matching the production loader. Do not install an error trap that tears down the stage. Set the SSM execution timeout to `5400` seconds.

Expected: either all phases pass or one exact failure record identifies the first failing phase and batch with a Neo4j error/status code.

- [ ] **Step 6: Collect bounded server evidence if and only if the diagnostic fails**

Collect and redact:

```powershell
docker compose ... ps -a
docker compose ... logs --tail 200 law-neo4j
```

Also read `/logs/neo4j.log` and `/logs/debug.log` from the preserved volume with a maximum of 200 trailing lines. Replace the actual Neo4j password, runtime user, URIs with userinfo, and authorization headers before output. Do not delete the container, release directory, or volumes.

- [ ] **Step 7: Record the confirmed root-cause evidence**

Update the master checklist with only:

- exact failing phase and batch;
- exception class and Neo4j error/status code;
- whether the server stayed healthy;
- the minimum evidence-backed correction category;
- explicit note that public cutover did not occur.

Do not implement the Neo4j correction in this task. The failure category determines the next approved TDD change.

---

### Task 4: Verify and hand off without broadening deployment scope

**Files:**
- Modify after diagnosis: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`
- Preserve: `docs/superpowers/specs/2026-08-02-pilot-runtime-crlf-neo4j-diagnostics-design.md`
- Preserve: `docs/superpowers/plans/2026-08-02-pilot-runtime-crlf-neo4j-diagnostics.md`

**Interfaces:**
- Consumes: Task 1 test evidence and Task 3 diagnostic result.
- Produces: an evidence-backed root-cause handoff and one bounded next decision.

- [ ] **Step 1: Run final local verification for committed code**

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py test/test_deployment_readiness_artifacts.py test/test_codebuild_pilot_contract.py -q
git diff --check
git status --short
```

Expected: all tests pass, no whitespace errors, and only the intentional checklist update remains uncommitted.

- [ ] **Step 2: Commit the diagnostic record separately**

```powershell
git add docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md
git diff --cached --check
git commit -m "docs: record legal graph load root cause"
```

- [ ] **Step 3: Stop at the next production decision**

Report:

1. confirmed parser defect and test evidence;
2. confirmed Neo4j phase/batch/error evidence;
3. current private-stage state;
4. whether any provider call occurred;
5. the single recommended correction;
6. the exact approval required before changing the Neo4j loader/resources or resuming seed load/cutover.

Do not push, merge, run full RAG load, or start public deployment unless the user explicitly approves that separate action.
