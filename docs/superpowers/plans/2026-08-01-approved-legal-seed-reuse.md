# 승인 기반 법령 Seed 임베딩 재사용 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 최신 법령 수집 결과와 기존 검증 seed를 해시로 대조하여 동일 OpenAI 임베딩을 재사용하고, 변경·신규 청크만 명시적 비용 승인 후 처리하는 승인형 seed builder를 만든다.

**Architecture:** 파일 기반 재사용 서비스가 기존 2.4GB embedding JSONL을 streaming 방식으로 분류하고 벡터 없는 plan/audit를 만든다. 별도 orchestration 서비스와 얇은 Django command가 live ingestion, freshness 검증, 비용 게이트, 변경분 embedding, 네 artifact 패키징과 manifest 이중 검증을 순서대로 실행한다. 기본 및 dry-run 경로는 OpenAI, S3, 운영 DB를 호출하지 않는다.

**Tech Stack:** Python 3.14, Django management commands, JSONL/CSV, OpenAI embeddings API, pytest, `production_rag_seed_manifest.v1`.

## Global Constraints

- 기존 embedding 공간은 `openai` / `text-embedding-3-large` / `1024`만 허용한다.
- 재사용 identity는 `chunk_id + embedding_text_hash`다.
- 최신성은 실제 source ingestion의 `legal_ingestion_run_summary.v2`로만 증명한다.
- 테스트와 `--dry-run`은 OpenAI, S3, 운영 DB를 호출하지 않는다.
- pending이 1개 이상이고 `--allow-paid-embedding`이 없으면 provider 호출 전에 실패한다.
- final bundle은 네 artifact를 포함하고 build 후 reload 전체 검증을 통과해야 한다.
- audit JSON/CSV에 embedding vector와 법령 원문을 기록하지 않는다.
- AWS 업로드, 운영 seed load, descriptor 생성, App Release는 이 계획에서 실행하지 않는다.

---

### Task 1: 기존 embedding을 streaming 방식으로 분류한다

**Files:**
- Create: `app/services/legal_embedding_reuse.py`
- Create: `test/test_legal_embedding_reuse.py`

**Interfaces:**
- Consumes: `RagSeedBundle`, fresh `embedding_inputs.jsonl`, output directory.
- Produces: `EmbeddingReusePlan(plan_sha256, ...)`, `reused_embeddings.jsonl`, `pending_embedding_inputs.jsonl`, `embedding_reuse_plan.json`, `embedding_reuse_audit.csv`.

- [ ] **Step 1: 동일·변경·신규·삭제 분류 실패 테스트를 작성한다**

```python
def test_plan_reuses_only_matching_chunk_and_text_hash(tmp_path, verified_bundle):
    fresh = write_jsonl(tmp_path / "fresh.jsonl", [
        embedding_input("same", "hash-same"),
        embedding_input("changed", "hash-new"),
        embedding_input("new", "hash-new-row"),
    ])
    plan = build_embedding_reuse_plan(
        bundle=verified_bundle,
        fresh_inputs_path=fresh,
        output_dir=tmp_path / "plan",
    )
    assert plan.reused_count == 1
    assert plan.changed_count == 1
    assert plan.new_count == 1
    assert plan.removed_count == 1
    assert plan.pending_count == 2
    assert len(plan.plan_sha256) == 64
```

- [ ] **Step 2: RED를 확인한다**

Run: `python -m pytest test/test_legal_embedding_reuse.py -q`

Expected: FAIL with `ModuleNotFoundError: app.services.legal_embedding_reuse`.

- [ ] **Step 3: 최소 streaming 분류 구현을 작성한다**

`EmbeddingReusePlan`은 digest, count와 산출물 path만 보관한다. fresh 입력은 `chunk_id -> embedding_text_hash` metadata map으로 읽고, 기존 `legal_embeddings`는 한 행씩 순회한다. hash가 같은 기존 JSON 행은 final 실행에서만 reuse 임시 파일에 기록하고 dry-run에서는 count만 계산한다. 변경·신규 fresh row만 pending 파일에 기록한다. `plan_sha256`은 dataset version, 기존 manifest SHA, embedding 공간과 정렬된 pending identity로 계산한다. 중복 ID나 빈 hash는 `LegalEmbeddingReuseError`로 실패시키고 임시 파일을 정리한다.

- [ ] **Step 4: GREEN과 edge case를 확인한다**

Run: `python -m pytest test/test_legal_embedding_reuse.py -q`

Expected: PASS for matching, changed, new, removed, duplicate ID, empty hash, and vector-free audit assertions.

- [ ] **Step 5: 사용자가 검토 후 Task 1 변경을 커밋한다**

```powershell
git add app/services/legal_embedding_reuse.py test/test_legal_embedding_reuse.py
git diff --cached --check
git commit -m "feat: plan verified legal embedding reuse"
```

### Task 2: pending embedding 결합과 final bundle 생성을 구현한다

**Files:**
- Create: `app/services/approved_legal_seed_builder.py`
- Create: `test/test_approved_legal_seed_builder.py`

**Interfaces:**
- Consumes: verified existing bundle, fresh ingestion output root, expected dataset version, max age, paid-call boolean, approved plan SHA, injected embedding function.
- Produces: `ApprovedLegalSeedBuildResult(status, dataset_version, verified_at, manifest_path, manifest_sha256, reuse_plan)`.

- [ ] **Step 1: 비용 게이트와 zero-paid 성공 실패 테스트를 작성한다**

```python
def test_builder_refuses_pending_rows_before_provider_call(builder_fixture):
    calls = []
    with pytest.raises(PaidEmbeddingApprovalRequired):
        build_approved_legal_seed(
            **builder_fixture,
            allow_paid_embedding=False,
            approved_plan_sha256=None,
            embedding_generator=lambda **kwargs: calls.append(kwargs),
        )
    assert calls == []


def test_builder_completes_without_provider_when_every_row_is_reused(builder_fixture):
    result = build_approved_legal_seed(
        **builder_fixture,
        allow_paid_embedding=False,
        approved_plan_sha256=None,
        embedding_generator=lambda **kwargs: pytest.fail("provider called"),
    )
    assert result.status == "verified"
```

- [ ] **Step 2: RED를 확인한다**

Run: `python -m pytest test/test_approved_legal_seed_builder.py -q`

Expected: FAIL because `app.services.approved_legal_seed_builder` is absent.

- [ ] **Step 3: freshness·dataset version·결합·manifest 이중 검증을 구현한다**

새 ingestion `reports/run_summary.json`을 `evaluate_run_summary()`로 검증하고 non-dry 입력 dataset version과 exact match를 요구한다. 모든 필수 source의 가장 오래된 `last_verified_at`을 보수적인 단일 검증 시각으로 사용한다. reuse plan의 pending이 있으면 비용 flag와 approved plan SHA가 현재 plan digest와 모두 일치한 후에만 injected generator를 부른다. generated JSONL은 materialized reuse 임시 파일에 먼저 append하고, 완성된 파일만 final legal embeddings 경로로 원자 이동한다. 이어서 fresh `law_chunks.jsonl`, 기존 review-case, 기존 precedent를 새 bundle에 복사한다. `build_rag_seed_manifest()` 후 `load_and_validate_rag_seed_manifest()`를 호출하여 완성 결과만 반환한다.

- [ ] **Step 4: 실패 원자성과 manifest 검증을 확인한다**

Run: `python -m pytest test/test_approved_legal_seed_builder.py test/test_production_rag_seed.py -q`

Expected: PASS; provider 실패, dataset mismatch, stale summary, generated append 실패, duplicate final embedding, manifest reload failure에서 final manifest나 부분 final embedding이 남지 않는다.

- [ ] **Step 5: 사용자가 검토 후 Task 2 변경을 커밋한다**

```powershell
git add app/services/approved_legal_seed_builder.py test/test_approved_legal_seed_builder.py
git diff --cached --check
git commit -m "feat: build incrementally embedded legal seed"
```

### Task 3: 승인형 Django command를 추가한다

**Files:**
- Create: `backend/chatbot/management/commands/build_approved_legal_rag_seed.py`
- Create: `test/test_approved_legal_rag_seed.py`

**Interfaces:**
- Consumes: `--source-config`, `--existing-manifest`, `--output-root`, `--max-age-hours`, optional `--dataset-version`, `--approved-plan-sha256`, `--client`, `--base-date`, `--history-years`, `--dry-run`, `--allow-paid-embedding`, `--format`.
- Produces: redacted `approved_legal_rag_seed_build.v1` JSON/text result and verified bundle when not dry-run.

- [ ] **Step 1: command 인자와 provider 차단 실패 테스트를 작성한다**

```python
def test_command_dry_run_never_calls_openai(tmp_path, monkeypatch, command_inputs):
    monkeypatch.setattr(
        "etl.legal.embedding.run_openai.generate_embeddings",
        lambda **kwargs: pytest.fail("provider called"),
    )
    call_command(
        "build_approved_legal_rag_seed",
        *command_inputs,
        output_root=tmp_path / "output",
        dry_run=True,
        format="json",
    )
```

- [ ] **Step 2: RED를 확인한다**

Run: `python -m pytest test/test_approved_legal_rag_seed.py -q`

Expected: FAIL with unknown management command.

- [ ] **Step 3: 얇은 command와 ingestion orchestration을 구현한다**

command는 인자 검증, source ingestion 실행, builder 호출, redacted 출력만 담당한다. `--dry-run`은 live source ingestion과 reuse plan까지 실행해 dataset version과 plan SHA를 출력하지만 embedding generator를 전달하지 않는다. non-dry는 `--dataset-version`을 요구한다. pending 실행은 `--allow-paid-embedding`과 일치하는 `--approved-plan-sha256`이 함께 있을 때만 `run_openai.generate_embeddings()`를 전달한다. API key, 원문, vector, raw provider exception은 stdout/stderr에 출력하지 않는다.

- [ ] **Step 4: command와 기존 pipeline 회귀를 확인한다**

Run: `python -m pytest test/test_approved_legal_rag_seed.py test/test_legal_ingestion_operational_summary.py -q`

Expected: PASS without network/provider calls.

- [ ] **Step 5: 사용자가 검토 후 Task 3 변경을 커밋한다**

```powershell
git add backend/chatbot/management/commands/build_approved_legal_rag_seed.py test/test_approved_legal_rag_seed.py
git diff --cached --check
git commit -m "feat: orchestrate approved legal seed reuse"
```

### Task 4: 운영 문서와 전체 회귀 계약을 정렬한다

**Files:**
- Modify: `docs/ops/legal-data-freshness-runbook.md`
- Modify: `docs/ops/production-rag-seed.md`
- Modify: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`
- Modify: `test/test_aws_pilot_infrastructure.py`
- Modify: `test/test_deployment_readiness_artifacts.py`

**Interfaces:**
- Consumes: verified builder result and immutable local bundle.
- Produces: 비용 승인 전 dry-run, 승인 후 변경분 embedding, S3 upload, maintenance, acceptance, App Release의 운영 순서.

- [ ] **Step 1: 금지된 우회와 순서 계약 실패 테스트를 작성한다**

`test/test_aws_pilot_infrastructure.py`에서 runbook이 기존 baseline 재구축만으로 현재 시각을 부여하지 않고, dry-run → paid approval → immutable upload → seed maintenance → acceptance → App Release 순서를 명시하도록 검사한다.

- [ ] **Step 2: RED를 확인한다**

Run: `python -m pytest test/test_aws_pilot_infrastructure.py -k "legal_seed or operational_evidence" -q`

Expected: FAIL because current runbook has no incremental reuse or cost-gate sequence.

- [ ] **Step 3: runbook과 master checklist를 갱신한다**

현재 검증 seed 경로, dry-run 명령 형식, 승인 보고 필드, 새 manifest 검증, versioned S3 prefix upload, `Load-Rag-Seed-Pilot.ps1`, 10분 acceptance, App Release 승인 순서를 기록한다. `rebuild_artifacts_from_embeddings`만 실행해 freshness를 갱신하는 우회를 명시적으로 금지한다.

- [ ] **Step 4: 전체 관련 회귀와 정적 검사를 실행한다**

Run:

```powershell
python -m pytest test/test_legal_embedding_reuse.py test/test_approved_legal_seed_builder.py test/test_approved_legal_rag_seed.py test/test_production_rag_seed.py test/test_legal_ingestion_operational_summary.py test/test_aws_pilot_infrastructure.py -q
git diff --check
rg -n "OPENAI_API_KEY|embedding_vector" docs/ops/legal-data-freshness-runbook.md docs/ops/production-rag-seed.md
```

Expected: all tests PASS, `git diff --check` clean, and docs contain no secret values or vectors.

- [ ] **Step 5: 사용자가 검토 후 Task 4 변경을 커밋한다**

```powershell
git add docs/ops/legal-data-freshness-runbook.md docs/ops/production-rag-seed.md docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md test/test_aws_pilot_infrastructure.py test/test_deployment_readiness_artifacts.py
git diff --cached --check
git commit -m "docs: govern incremental legal seed refresh"
```

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-01-approved-legal-seed-reuse.md`.

Execution uses inline `superpowers:executing-plans` with a checkpoint after each RED/GREEN task. The assistant does not stage, commit, push, upload seed data, invoke paid providers, mutate production databases, or approve App Release. Those actions require the user's explicit operation or approval.
