# Supervisor 패키지 메타데이터 정규화 구현 계획

> **에이전트 작업자용:** 이 계획은 작업별로 superpowers:subagent-driven-development 또는 superpowers:executing-plans를 사용해 실행한다. 각 단계의 체크박스를 완료 순서대로 갱신한다.

**목표:** Supervisor LLM/fallback이 저장하는 Agent 패키지에서 첨부파일과 payload를 서버 fallback 계약으로 정규화해, 원문·저장소 메타데이터·임의 필드가 handoff에 남지 않게 한다.

**구조:** 두 LLM 정규화 경로가 공통 helper로 fallback 패키지를 재구성한다. Helper는 fallback에 있는 payload 키만 허용하고, payload·package root의 첨부파일을 fallback 승인 ID 집합에 속한 selector로 투영한다. 실행 시점의 Worker 재결합 로직은 바꾸지 않는다.

**기술 스택:** Python 3, pytest, 기존 app.services.supervisor_llm_service 계약, Django 테스트 환경

## 전역 제약

- 변경 범위는 app/services/supervisor_llm_service.py, 그 단위 테스트, 마스터 체크리스트, 설계·계획 문서로 제한한다.
- LLM 후보는 fallback package에 존재하는 node_code와 payload 필드만 바꿀 수 있다.
- 첨부파일은 attachment_id 문자열 하나만 보관한다. content_base64, storage_uri, scan_status 등 다른 키는 보관하지 않는다.
- 후보가 fallback 승인 ID가 아닌 첨부파일을 보내면 버린다. 사용할 수 있는 후보 ID가 하나도 없으면 fallback selector 목록을 사용한다.
- 패키지 계약이 잘못되면 기존 fail-closed 검증을 유지한다. 정규화가 무효 패키지를 유효하게 만들면 안 된다.
- dev 병합, 이슈·PR 생성, 커밋·푸시는 사용자가 직접 실행한다. 각 커밋 단계에는 사용자 실행 명령만 제시한다.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| app/services/supervisor_llm_service.py | fallback 기준 payload allowlist 및 attachment selector 정규화 helper를 두 LLM package 정규화 경로에 적용한다. |
| test/test_supervisor_llm_service.py | state·plan 경로에서 원문 메타데이터와 후보 전용 필드가 저장되지 않는지 회귀 검증한다. |
| docs/ops/project-readiness-master-checklist.md | #231 구현 진행 중 상태와 이슈 번호를 기록한다. |
| docs/superpowers/specs/2026-07-19-supervisor-package-metadata-normalization-design.md | 승인된 설계 근거를 유지한다. |
| docs/superpowers/plans/2026-07-19-supervisor-package-metadata-normalization.md | 이 구현 순서와 검증 명령을 기록한다. |

### Task 1: state·plan 저장 경계의 실패 회귀 테스트

**Files:**

- Modify: test/test_supervisor_llm_service.py:1, 352-530
- Test: test/test_supervisor_llm_service.py

**Interfaces:**

- Consumes: _safe_agent_input_packages(candidate_packages, fallback_packages) 및 _safe_plan_agent_packages(candidate_packages, fallback_packages)
- Produces: state와 plan package가 selector-only attachment 및 fallback allowlist payload를 보장해야 한다는 실패 회귀 테스트

- [ ] **Step 1: json import와 state 경로 실패 테스트를 추가한다.**

~~~python
import json


def test_state_package_normalization_keeps_only_fallback_selectors_and_payload_fields():
    fallback_packages = [{
        "schema_version": "agent_input_schema.v1",
        "node_code": "fine_notice_analysis",
        "owner": "workzion2",
        "status": "ready",
        "missing_fields": [],
        "attachments": [{"attachment_id": "att_notice", "storage_uri": "server://fallback/raw"}],
        "payload": {
            "notice_text": "fallback notice",
            "attachments": [{"attachment_id": "att_notice", "scan_status": "clean"}],
        },
    }]
    candidate_packages = [{
        "node_code": "fine_notice_analysis",
        "payload": {
            "notice_text": "LLM notice",
            "attachments": [
                {"attachment_id": "att_notice", "content_base64": "llm-secret"},
                {"attachment_id": "att_unknown", "storage_uri": "llm://unknown"},
            ],
            "untrusted_payload_field": "must not persist",
        },
    }]

    packages = service._safe_agent_input_packages(candidate_packages, fallback_packages)

    assert packages[0]["owner"] == "workzion2"
    assert packages[0]["payload"] == {
        "notice_text": "LLM notice",
        "attachments": [{"attachment_id": "att_notice"}],
    }
    assert packages[0]["attachments"] == [{"attachment_id": "att_notice"}]
    stored = json.dumps(packages, ensure_ascii=False)
    assert "secret" not in stored
    assert "storage_uri" not in stored
    assert "untrusted_payload_field" not in stored
~~~

- [ ] **Step 2: plan 경로 실패 테스트를 추가한다.**

~~~python
def test_plan_package_normalization_keeps_only_fallback_selectors_and_payload_fields():
    fallback_packages = [{
        "schema_version": "agent_input_schema.v1",
        "node_code": "law_ground_search",
        "owner": "techshin31",
        "status": "ready",
        "missing_fields": [],
        "attachments": [{"attachment_id": "att_law", "storage_uri": "server://fallback/raw"}],
        "payload": {
            "search_query": "fallback query",
            "attachments": [{"attachment_id": "att_law", "scan_status": "clean"}],
        },
    }]
    candidate_packages = [{
        "node_code": "law_ground_search",
        "payload": {
            "search_query": "LLM query",
            "attachments": [
                {"attachment_id": "att_law", "content_base64": "llm-secret"},
                {"attachment_id": "att_unknown", "storage_uri": "llm://unknown"},
            ],
            "untrusted_payload_field": "must not persist",
        },
    }]

    packages = service._safe_plan_agent_packages(candidate_packages, fallback_packages)

    assert packages[0]["payload"] == {
        "search_query": "LLM query",
        "attachments": [{"attachment_id": "att_law"}],
    }
    assert packages[0]["attachments"] == [{"attachment_id": "att_law"}]
    stored = json.dumps(packages, ensure_ascii=False)
    assert "secret" not in stored
    assert "storage_uri" not in stored
    assert "untrusted_payload_field" not in stored
~~~

- [ ] **Step 3: 두 테스트가 현재의 얕은 병합 때문에 실패하는지 확인한다.**

Run:

~~~powershell
python -m pytest test/test_supervisor_llm_service.py -q
~~~

Expected: 새 두 테스트가 content_base64, storage_uri, 또는 untrusted_payload_field가 남아 실패한다.

- [ ] **Step 4: 테스트 변경만 검토한다.**

~~~powershell
git diff --check
git diff -- test/test_supervisor_llm_service.py
~~~

Expected: 공백 오류가 없고 production 파일은 변경되지 않는다.

- [ ] **Step 5: 사용자가 테스트 RED 상태를 커밋한다.**

~~~powershell
git add test/test_supervisor_llm_service.py
git diff --cached --check
git commit -m "test: cover supervisor package metadata normalization"
~~~

### Task 2: fallback allowlist 기반 package 정규화 구현

**Files:**

- Modify: app/services/supervisor_llm_service.py:575-635
- Test: test/test_supervisor_llm_service.py

**Interfaces:**

- Consumes: candidate_packages: list[Any], fallback_packages: Any
- Produces: _safe_package_payload, _attachment_selectors, _approved_attachment_selectors와 selector-only package 목록

- [ ] **Step 1: package payload와 attachment helper를 추가한다.**

_safe_plan_agent_packages 바로 앞에 아래 함수를 추가한다.

~~~python
def _attachment_selectors(value: Any) -> list[dict[str, str]]:
    selectors: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in _list_of_dicts(value):
        attachment_id = str(item.get("attachment_id") or "").strip()
        if not attachment_id or attachment_id in seen_ids:
            continue
        seen_ids.add(attachment_id)
        selectors.append({"attachment_id": attachment_id})
    return selectors


def _approved_attachment_selectors(candidate: Any, fallback: Any) -> list[dict[str, str]]:
    fallback_selectors = _attachment_selectors(fallback)
    approved_ids = {item["attachment_id"] for item in fallback_selectors}
    selected = [
        item
        for item in _attachment_selectors(candidate)
        if item["attachment_id"] in approved_ids
    ]
    return selected or fallback_selectors


def _safe_package_payload(candidate: Any, fallback: Any) -> dict[str, Any]:
    fallback_payload = deepcopy(fallback) if isinstance(fallback, dict) else {}
    candidate_payload = candidate if isinstance(candidate, dict) else {}
    payload: dict[str, Any] = {}
    for key, fallback_value in fallback_payload.items():
        if key == "attachments":
            payload[key] = _approved_attachment_selectors(
                candidate_payload.get(key), fallback_value
            )
        elif key in candidate_payload:
            payload[key] = deepcopy(candidate_payload[key])
        else:
            payload[key] = deepcopy(fallback_value)
    return payload


def _safe_agent_package(fallback: dict[str, Any], candidate: Any) -> dict[str, Any]:
    package = deepcopy(fallback)
    candidate_package = candidate if isinstance(candidate, dict) else {}
    package["payload"] = _safe_package_payload(
        candidate_package.get("payload"), package.get("payload")
    )
    if "attachments" in package:
        package["attachments"] = _attachment_selectors(package["attachments"])
    return package
~~~

- [ ] **Step 2: 두 기존 함수를 공통 재구성 helper로 바꾼다.**

_safe_plan_agent_packages와 _safe_agent_input_packages의 각각 package = deepcopy(...) 및 얕은 payload 병합 부분을 아래처럼 바꾼다.

~~~python
package = _safe_agent_package(fallback_by_node[node_code], candidate)
~~~

~~~python
package = _safe_agent_package(fallback, candidate)
~~~

두 함수의 기존 missing_fields, status, owner, schema_version 처리는 그대로 둔다.

- [ ] **Step 3: Task 1의 focused 테스트를 실행해 GREEN을 확인한다.**

Run:

~~~powershell
python -m pytest test/test_supervisor_llm_service.py -q
~~~

Expected: 모든 Supervisor LLM 단위 테스트가 통과하고 새 두 테스트는 raw metadata와 후보 전용 필드가 저장되지 않음을 확인한다.

- [ ] **Step 4: #229 실행 경계 회귀를 실행한다.**

Run:

~~~powershell
python -m pytest test/test_supervisor_llm_service.py test/test_supervisor_execution_input_service.py test/test_agent_node_service.py -q
~~~

Expected: LLM 저장 단계와 Worker 실행 단계의 attachment selector 계약이 함께 통과한다.

- [ ] **Step 5: 사용자에게 구현 커밋 명령을 제공한다.**

~~~powershell
git add app/services/supervisor_llm_service.py test/test_supervisor_llm_service.py
git diff --cached --check
git commit -m "fix: normalize supervisor package attachment metadata"
~~~

### Task 3: 진행 상태 기록 및 PR 전 검증

**Files:**

- Modify: docs/ops/project-readiness-master-checklist.md:69
- Modify: docs/superpowers/specs/2026-07-19-supervisor-package-metadata-normalization-design.md
- Create: docs/superpowers/plans/2026-07-19-supervisor-package-metadata-normalization.md
- Test: test/test_supervisor_llm_service.py, test/test_supervisor_execution_input_service.py, test/test_agent_node_service.py

**Interfaces:**

- Consumes: Task 2가 보장한 selector-only 저장 계약
- Produces: #231 진행 상태와 재현 가능한 검증 근거

- [ ] **Step 1: 체크리스트의 후속 보안 항목을 진행 중으로 갱신한다.**

docs/ops/project-readiness-master-checklist.md의 해당 줄을 다음으로 교체한다.

~~~markdown
- [~] Supervisor LLM/fallback 단계에서도 에이전트 패키지의 첨부파일을 attachment_id 선택자로만 보관하고, 임의 메타데이터·원문을 제거하는 사전 정규화 — #231 구현·검증 진행 중
~~~

- [ ] **Step 2: 전체 변경의 공백 오류와 focused 회귀를 확인한다.**

Run:

~~~powershell
git diff --check
python -m pytest test/test_supervisor_llm_service.py test/test_supervisor_execution_input_service.py test/test_agent_node_service.py -q
~~~

Expected: 공백 오류가 없고 세 테스트 파일이 모두 통과한다.

- [ ] **Step 3: 변경 범위를 확인한다.**

~~~powershell
git diff --stat origin/dev...HEAD
git status --short
~~~

Expected: app/services/supervisor_llm_service.py, test/test_supervisor_llm_service.py, 마스터 체크리스트와 #231 설계·계획 문서만 의도된 변경으로 보인다.

- [ ] **Step 4: 사용자가 문서·상태 변경을 커밋한다.**

~~~powershell
git add docs/ops/project-readiness-master-checklist.md
git add docs/superpowers/specs/2026-07-19-supervisor-package-metadata-normalization-design.md
git add docs/superpowers/plans/2026-07-19-supervisor-package-metadata-normalization.md
git diff --cached --check
git commit -m "docs: track supervisor package normalization"
~~~

- [ ] **Step 5: 사용자가 PR 생성 전 최종 확인 명령을 실행한다.**

~~~powershell
git status -sb
git log --oneline origin/dev..HEAD
git diff --check origin/dev...HEAD
~~~

Expected: fix/231-supervisor-package-normalization에는 #231 관련 커밋만 있고, worktree는 깨끗하다.
