# Operational Data Run Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 이슈 #299의 첫 번째 독립 단위로, 법령 적재·재구축 실행마다 source별 최신성·버전·건수·실패 원인을 동일한 `run_summary` 계약으로 남기고 운영자가 오래되거나 불완전한 실행을 자동 판정할 수 있게 한다.

**Architecture:** 기존 `etl/legal/ingestion/reporter.py`를 법령 run summary의 단일 생성기로 유지하고, source별 증적과 결정적 데이터 버전을 추가한다. `rebuild_artifacts_from_embeddings.py`도 같은 생성기를 사용한다. 별도 검증 CLI는 운영자가 승인한 최대 허용 경과시간을 인자로 받아 stale·missing·failed를 판정하며, 코드에 임의 운영 임계값을 하드코딩하지 않는다.

**Tech Stack:** Python 3.13+, 표준 라이브러리 `hashlib`·`json`·`datetime`, pytest, 기존 법령 ETL 모듈

## Global Constraints

- 실제 운영 DB, 공급자 API, 유료 재임베딩 없이 성공 증적을 만들지 않는다.
- source 원문, 비밀값, 임베딩 벡터를 run summary에 저장하지 않는다.
- 시간은 UTC ISO 8601로 기록한다.
- `dataset_version`은 source/version/chunk 식별자와 content hash만으로 결정적으로 계산한다.
- stale 기준은 검증 CLI의 `--max-age-hours`에서 명시하며 기본 운영값을 코드에 넣지 않는다.
- 이 계획은 #299의 데이터 최신성 하위 범위만 다룬다. Agent 실행 재현성과 CloudWatch 관측은 별도 계획으로 진행한다.

---

### Task 1: source별 법령 run summary 계약

**Files:**
- Create: `test/test_legal_ingestion_operational_summary.py`
- Modify: `etl/legal/ingestion/reporter.py`

**Interfaces:**
- Consumes: 기존 `build_run_summary(...)`의 `sources`, `versions`, `raw_records`, `chunks`, `searchable_chunks`, `failed_items`
- Produces: `contract_version="legal_ingestion_run_summary.v2"`, `dataset_version`, `source_summaries`

- [ ] **Step 1: 실패 테스트 작성**

```python
from etl.legal.ingestion.reporter import build_run_summary


def _summary():
    return build_run_summary(
        run_id="legal:test",
        mode="artifact",
        sources=[{
            "source_id": "road_traffic_act",
            "source_name": "도로교통법",
            "source_type": "law",
            "provider": "law_go_kr",
            "provider_source_id": "도로교통법",
        }],
        versions=[{
            "source_id": "road_traffic_act",
            "source_version_id": "road_traffic_act:20260701:1",
            "enforce_date": "2026-07-01",
        }],
        raw_records=[{
            "source_id": "road_traffic_act",
            "source_version_id": "road_traffic_act:20260701:1",
            "fetched_at": "2026-07-23T01:00:00+00:00",
        }],
        chunks=[{
            "source_id": "road_traffic_act",
            "chunk_id": "road_traffic_act:20260701:1:article:1",
            "content_hash": "sha256:abc",
            "is_searchable": True,
        }],
        searchable_chunks=[{
            "source_id": "road_traffic_act",
            "chunk_id": "road_traffic_act:20260701:1:article:1",
        }],
        relations=[],
        embedding_inputs=[],
        quality_report={"failed_chunks": 0, "status_counts": {}},
        failed_items=[],
        started_at="2026-07-23T00:59:00+00:00",
    )


def test_run_summary_contains_source_freshness_and_version_evidence():
    summary = _summary()
    assert summary["contract_version"] == "legal_ingestion_run_summary.v2"
    assert summary["dataset_version"].startswith("sha256:")
    source = summary["source_summaries"][0]
    assert source == {
        "source_id": "road_traffic_act",
        "source_name": "도로교통법",
        "source_type": "law",
        "provider": "law_go_kr",
        "provider_source_id": "도로교통법",
        "status": "success",
        "version_count": 1,
        "raw_document_count": 1,
        "chunk_count": 1,
        "searchable_chunk_count": 1,
        "first_effective_at": "2026-07-01",
        "last_effective_at": "2026-07-01",
        "collected_at": "2026-07-23T01:00:00+00:00",
        "last_verified_at": summary["finished_at"],
        "data_version": source["data_version"],
        "errors": [],
    }
    assert source["data_version"].startswith("sha256:")


def test_run_summary_marks_missing_source_failed():
    summary = build_run_summary(
        run_id="legal:failed",
        mode="artifact",
        sources=[{
            "source_id": "road_traffic_act",
            "source_name": "도로교통법",
            "source_type": "law",
            "provider": "law_go_kr",
            "provider_source_id": "도로교통법",
        }],
        versions=[],
        raw_records=[],
        chunks=[],
        searchable_chunks=[],
        relations=[],
        embedding_inputs=[],
        quality_report={"failed_chunks": 0, "status_counts": {}},
        failed_items=[{"source_id": "road_traffic_act", "error": "provider_unavailable"}],
        started_at="2026-07-23T00:59:00+00:00",
    )
    source = summary["source_summaries"][0]
    assert source["status"] == "failed"
    assert source["last_verified_at"] is None
    assert source["errors"] == ["provider_unavailable"]
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest test/test_legal_ingestion_operational_summary.py -q`

Expected: `contract_version`, `dataset_version` 또는 `source_summaries`가 없어 FAIL

- [ ] **Step 3: 최소 구현**

`etl/legal/ingestion/reporter.py`에 다음 책임을 추가한다.

```python
import hashlib

RUN_SUMMARY_CONTRACT_VERSION = "legal_ingestion_run_summary.v2"


def _sha256_version(rows: list[str]) -> str:
    payload = "\n".join(sorted(value for value in rows if value))
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _source_summaries(
    *,
    sources: list[dict],
    versions: list[dict],
    raw_records: list[dict],
    chunks: list[dict],
    searchable_chunks: list[dict],
    failed_items: list[dict],
    finished_at: str,
) -> list[dict]:
    rows = []
    for source in sorted(sources, key=lambda item: item["source_id"]):
        source_id = source["source_id"]
        source_versions = [row for row in versions if row.get("source_id") == source_id]
        source_raw = [row for row in raw_records if row.get("source_id") == source_id]
        source_chunks = [row for row in chunks if row.get("source_id") == source_id]
        source_searchable = [
            row for row in searchable_chunks if row.get("source_id") == source_id
        ]
        errors = [
            str(item["error"])
            for item in failed_items
            if item.get("source_id") == source_id and item.get("error")
        ]
        effective_dates = sorted(
            str(row["enforce_date"])
            for row in source_versions
            if row.get("enforce_date")
        )
        collected_dates = sorted(
            str(row["fetched_at"]) for row in source_raw if row.get("fetched_at")
        )
        status = "success" if source_versions and not errors else "partial"
        if not source_versions:
            status = "failed" if errors else "missing"
        rows.append({
            "source_id": source_id,
            "source_name": source.get("source_name"),
            "source_type": source.get("source_type"),
            "provider": source.get("provider"),
            "provider_source_id": source.get("provider_source_id"),
            "status": status,
            "version_count": len(source_versions),
            "raw_document_count": len(source_raw),
            "chunk_count": len(source_chunks),
            "searchable_chunk_count": len(source_searchable),
            "first_effective_at": effective_dates[0] if effective_dates else None,
            "last_effective_at": effective_dates[-1] if effective_dates else None,
            "collected_at": collected_dates[-1] if collected_dates else None,
            "last_verified_at": finished_at if status == "success" else None,
            "data_version": _sha256_version([
                str(row.get("source_version_id") or "") for row in source_versions
            ] + [
                f"{row.get('chunk_id', '')}:{row.get('content_hash', '')}"
                for row in source_chunks
            ]),
            "errors": errors,
        })
    return rows
```

`build_run_summary()`는 `finished_at`을 한 번만 계산하고 위 함수를 호출한다. 전체 `dataset_version`은 각 source의 `source_id:data_version`을 `_sha256_version()`에 전달해 계산한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest test/test_legal_ingestion_operational_summary.py -q`

Expected: `2 passed`

- [ ] **Step 5: 커밋**

```powershell
git add etl/legal/ingestion/reporter.py test/test_legal_ingestion_operational_summary.py
git commit -m "feat: add legal source run summaries"
```

### Task 2: embedding baseline 재구축도 동일 계약 사용

**Files:**
- Modify: `etl/legal/rebuild_artifacts_from_embeddings.py`
- Modify: `test/test_legal_ingestion_operational_summary.py`

**Interfaces:**
- Consumes: Task 1의 `build_run_summary(...)`
- Produces: 수집 실행과 baseline 재구축 실행에서 동일한 v2 source summary

- [ ] **Step 1: 실패 테스트 작성**

작은 manifest와 embedding JSONL fixture를 `tmp_path`에 만들고 `rebuild_artifacts()`를 실행한 뒤 다음을 검증한다.

```python
def test_embedding_rebuild_uses_v2_run_summary(tmp_path):
    summary = rebuild_artifacts(
        manifest_path=manifest_path,
        embeddings_path=embeddings_path,
        output_dir=tmp_path / "out",
    )
    assert summary["contract_version"] == "legal_ingestion_run_summary.v2"
    assert summary["source_summaries"][0]["source_id"] == "road_traffic_act"
    assert summary["source_summaries"][0]["status"] == "success"
    persisted = json.loads(
        (tmp_path / "out/reports/run_summary.json").read_text(encoding="utf-8")
    )
    assert persisted["dataset_version"] == summary["dataset_version"]
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest test/test_legal_ingestion_operational_summary.py -q`

Expected: baseline summary에 v2 필드가 없어 FAIL

- [ ] **Step 3: 최소 구현**

`rebuild_artifacts_from_embeddings.py`의 수동 `run_summary` 사전을 제거하고 `build_run_summary()`를 호출한다. `mode`는 `rebuild_from_embedding_baseline`, `raw_records`는 이미 작성한 목록, `quality_report`는 현재 계산한 count를 사용한다. 기존 `embedding_baseline_path`와 `limitations`는 반환된 사전에 추가하되 v2 공통 필드를 덮어쓰지 않는다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest test/test_legal_ingestion_operational_summary.py -q`

Expected: `3 passed`

- [ ] **Step 5: 커밋**

```powershell
git add etl/legal/rebuild_artifacts_from_embeddings.py test/test_legal_ingestion_operational_summary.py
git commit -m "refactor: unify legal rebuild run evidence"
```

### Task 3: stale·missing·failed 자동 판정 CLI

**Files:**
- Create: `etl/legal/validate_run_summary.py`
- Create: `test/test_legal_run_summary_validation.py`

**Interfaces:**
- Consumes: v2 `run_summary.json`, 운영자가 승인한 `max_age_hours`, 필수 source id 목록
- Produces: `legal_run_summary_validation.v1` 결과와 프로세스 종료 코드 0 또는 1

- [ ] **Step 1: 실패 테스트 작성**

```python
from datetime import datetime, timezone
from etl.legal.validate_run_summary import evaluate_run_summary


def test_validation_blocks_stale_and_missing_sources():
    result = evaluate_run_summary(
        {
            "contract_version": "legal_ingestion_run_summary.v2",
            "run_id": "legal:test",
            "finished_at": "2026-07-22T00:00:00+00:00",
            "source_summaries": [{
                "source_id": "road_traffic_act",
                "status": "success",
                "last_verified_at": "2026-07-22T00:00:00+00:00",
            }],
        },
        now=datetime(2026, 7, 23, 2, tzinfo=timezone.utc),
        max_age_hours=24,
        required_sources=["road_traffic_act", "road_traffic_act_enforcement_decree"],
    )
    assert result["status"] == "failed"
    assert result["stale_sources"] == ["road_traffic_act"]
    assert result["missing_sources"] == ["road_traffic_act_enforcement_decree"]
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest test/test_legal_run_summary_validation.py -q`

Expected: 모듈이 없어 수집 단계에서 FAIL

- [ ] **Step 3: 최소 구현**

`evaluate_run_summary()`는 계약 버전, 각 필수 source 존재 여부, `status == "success"`, `last_verified_at` 경과시간을 검사한다. 결과는 `status`, `checked_at`, `max_age_hours`, `missing_sources`, `failed_sources`, `stale_sources`, `run_id`, `dataset_version`만 포함한다. CLI는 `--summary`, `--max-age-hours`, 반복 가능한 `--required-source`, 선택적인 `--output`을 받고 실패면 1을 반환한다.

- [ ] **Step 4: 단위·CLI 테스트 통과 확인**

Run: `python -m pytest test/test_legal_run_summary_validation.py -q`

Expected: stale, failed, current, 잘못된 계약 버전 시나리오가 모두 PASS

- [ ] **Step 5: 커밋**

```powershell
git add etl/legal/validate_run_summary.py test/test_legal_run_summary_validation.py
git commit -m "feat: validate legal data freshness evidence"
```

### Task 4: 운영 절차와 회귀 게이트 연결

**Files:**
- Create: `docs/ops/legal-data-freshness-runbook.md`
- Modify: `docs/ops/project-readiness-master-checklist.md`
- Modify: `docs/ops/release-checklist.md`

**Interfaces:**
- Consumes: Task 1~3의 v2 summary와 validation CLI
- Produces: 운영자가 실제 secret·DB를 넣은 뒤 실행할 명령, 증적 보관 위치, 실패 시 배포 중단 절차

- [ ] **Step 1: runbook 계약 테스트 작성**

`test/test_deployment_readiness_artifacts.py`에 다음 문자열 계약을 추가한다.

```python
def test_legal_freshness_runbook_has_bounded_validation_and_failure_actions():
    content = Path("docs/ops/legal-data-freshness-runbook.md").read_text(encoding="utf-8")
    assert "validate_run_summary.py" in content
    assert "--max-age-hours" in content
    assert "missing_sources" in content
    assert "failed_sources" in content
    assert "stale_sources" in content
    assert "배포를 중단" in content
    assert "reports/run_summary.json" in content
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest test/test_deployment_readiness_artifacts.py -q`

Expected: runbook 파일이 없어 FAIL

- [ ] **Step 3: runbook 작성**

문서에 다음 순서를 정확히 기록한다.

1. 운영 법령 수집 또는 승인 seed 재구축 실행
2. `reports/run_summary.json`을 변경 불가능한 release 증적 디렉터리에 복사
3. 운영 승인값으로 `python -m etl.legal.validate_run_summary --summary ... --max-age-hours ... --required-source ...` 실행
4. `missing_sources`, `failed_sources`, `stale_sources` 중 하나라도 있으면 배포를 중단
5. 공급자 복구 또는 승인 seed 재실행 후 새 run id로 재검증
6. `run_id`, `dataset_version`, validation JSON, 운영 DB readiness 결과를 배포 manifest와 함께 보관

- [ ] **Step 4: 전체 관련 검증**

Run:

```powershell
python -m pytest test/test_legal_ingestion_operational_summary.py test/test_legal_run_summary_validation.py test/test_deployment_readiness_artifacts.py -q
python -m ruff check etl/legal/ingestion/reporter.py etl/legal/rebuild_artifacts_from_embeddings.py etl/legal/validate_run_summary.py test/test_legal_ingestion_operational_summary.py test/test_legal_run_summary_validation.py --no-cache
git diff --check
```

Expected: 모든 테스트와 Ruff, whitespace 검사 통과

- [ ] **Step 5: 체크리스트 갱신과 커밋**

실제 운영 데이터 검증 전에는 `[x]`로 올리지 않는다. 코드·문서 자동화만 완료되면 C-2와 I 항목을 `[~]`로 유지하면서 PR 번호와 테스트 증적을 추가한다.

```powershell
git add docs/ops/legal-data-freshness-runbook.md docs/ops/project-readiness-master-checklist.md docs/ops/release-checklist.md test/test_deployment_readiness_artifacts.py
git commit -m "docs: add legal freshness operations gate"
```

## Self-Review

- Spec coverage: #299의 source별 `run_summary`, 수집 시점, 마지막 검증일, 원본 provider, 적용 기준일, 데이터 버전, stale·갱신 실패 판정과 운영 절차를 포함한다.
- Deferred by explicit split: 운영 DB row·index·embedding readiness 실증, Agent 모델·프롬프트·검색 버전 추적, 큐·외부 장애·CloudWatch 알림은 후속 독립 계획 대상이다.
- Placeholder scan: 실행 파일, 함수, 필드, 명령과 기대 결과를 모두 명시했다.
- Type consistency: v2 summary를 Task 1에서 만들고 Task 2~4가 같은 필드 이름으로 소비한다.
