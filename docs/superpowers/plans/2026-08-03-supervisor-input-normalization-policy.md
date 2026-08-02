# Supervisor 입력 정규화 정책 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사고 과실상담과 과태료·범칙금·이의신청 채팅을 버전이 있는 제한 도메인 규칙으로 정규화하고, 확정 사실을 침범하지 않으면서 각 Supervisor·Agent input schema에 안전하게 전달한다.

**Architecture:** 기존 `input_understanding_gate.v1`가 만든 안전 입력을 결정적 정규화 서비스에 넣고, 정규화 결과를 사고 사실 후보·과태료 intake·Agent `slot_state`로 투영한다. 사람용 Wiki MD와 실행용 JSON을 분리하며 JSON만 실행 기준으로 사용한다. LLM은 정책 allowlist를 통과한 미확정 후보만 제안할 수 있고, 확인 또는 재질문이 필요한 값은 Agent 실행을 차단한다.

**Tech Stack:** Python 3.13, 표준 라이브러리 `json`·`re`·`unicodedata`·`difflib`, pytest, Django Test, 버전 관리 JSON·Markdown, Node test runner, Vite

## Global Constraints

- 일반 한국어 전체를 위한 형태소 분석 라이브러리나 새로운 런타임 의존성을 추가하지 않는다.
- 범위는 사고 핵심 사실, 과태료·범칙금, 의견제출·이의신청으로 제한한다.
- 정규화 계층은 위법 여부, 과실비율, 승소 가능성, 법령명·조문·판례를 생성하지 않는다.
- 사용자 확정값은 확인된 OCR·공식 문서, 규칙 후보, LLM 후보보다 우선한다.
- 공식 문서와 사용자 확정 진술이 다르면 한쪽을 폐기하지 않고 충돌로 보존한다.
- OCR, Vision, RAG, 법률 판단 알고리즘의 내부 동작은 변경하지 않는다.
- 프론트엔드는 기존 `pending_questions`와 상태 표시를 재사용하며 새 화면을 만들지 않는다.
- 제공된 실제 파일은 브라우저 검증 입력으로만 사용하고 저장소에 추가하지 않는다.
- 기존 `확정 사용자 답변 > 미확정 LLM 후보` 핫픽스 동작을 회귀 테스트와 배포 브라우저에서 다시 검증한다.

---

### Task 1: 버전 정책 계약과 사람용 Wiki

**Files:**

- Create: `app/config/supervisor_input_normalization_policy.v1.json`
- Create: `app/services/supervisor_input_normalization_service.py`
- Create: `test/test_supervisor_input_normalization_service.py`
- Create: `docs/policies/supervisor-input-normalization/README.md`
- Create: `docs/policies/supervisor-input-normalization/common-language.md`
- Create: `docs/policies/supervisor-input-normalization/accident-core.md`
- Create: `docs/policies/supervisor-input-normalization/fine-notice.md`
- Create: `docs/policies/supervisor-input-normalization/objection.md`

**Interfaces:**

- Produces: `normalization_policy() -> dict[str, Any]`
- Produces: `normalization_policy_metadata() -> dict[str, str]`
- Produces: `clear_normalization_policy_cache() -> None`
- Consumes: `SUPERVISOR_INPUT_NORMALIZATION_POLICY_PATH` 환경변수 또는 기본 JSON 경로

- [ ] **Step 1: 정책 계약 실패 테스트를 작성한다**

`test/test_supervisor_input_normalization_service.py`에 다음 테스트를 추가한다.

```python
import json
import re
from pathlib import Path

import pytest

from app.services import supervisor_input_normalization_service as service


def test_default_normalization_policy_is_versioned_and_loadable() -> None:
    service.clear_normalization_policy_cache()

    policy = service.normalization_policy()

    assert policy["contract_version"] == "supervisor_input_normalization_policy.v1"
    assert set(policy["domains"]) == {"accident", "fine_notice", "objection"}
    assert service.normalization_policy_metadata()["source"].endswith(
        "app/config/supervisor_input_normalization_policy.v1.json"
    )


@pytest.mark.parametrize(
    "mutation,error_code",
    [
        (lambda value: value.update(contract_version="wrong.v1"), "unsupported_normalization_policy_version"),
        (lambda value: value["rules"].append(dict(value["rules"][0])), "duplicate_normalization_rule_id"),
        (lambda value: value["rules"][0].update(field="unknown"), "normalization_policy_contains_unknown_field"),
        (lambda value: value["rules"][0].update(decision="accept_anything"), "normalization_policy_contains_invalid_decision"),
    ],
)
def test_normalization_policy_rejects_invalid_contract(
    tmp_path, monkeypatch, mutation, error_code
) -> None:
    policy = json.loads(service.DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    mutation(policy)
    path = tmp_path / "invalid-policy.json"
    path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("SUPERVISOR_INPUT_NORMALIZATION_POLICY_PATH", str(path))
    service.clear_normalization_policy_cache()

    with pytest.raises(ValueError, match=error_code):
        service.normalization_policy()


def test_policy_rules_and_wiki_rule_ids_are_bidirectionally_synchronized() -> None:
    policy_ids = {rule["rule_id"] for rule in service.normalization_policy()["rules"]}
    wiki_root = Path("docs/policies/supervisor-input-normalization")
    documented = "\n".join(path.read_text(encoding="utf-8") for path in wiki_root.glob("*.md"))
    documented_ids = set(re.findall(r"`([a-z0-9_.]+(?:exact|alias|typo)_[0-9]+)`", documented))

    assert documented_ids == policy_ids
```

- [ ] **Step 2: 테스트가 올바른 이유로 실패하는지 확인한다**

Run:

```powershell
python -m pytest test/test_supervisor_input_normalization_service.py -q
```

Expected: 모듈 또는 `normalization_policy`가 아직 없어 FAIL.

- [ ] **Step 3: 정책 JSON과 검증 로더를 최소 구현한다**

JSON 최상위 구조를 다음으로 고정한다.

```json
{
  "contract_version": "supervisor_input_normalization_policy.v1",
  "decisions": ["auto_applied", "confirmation_required", "clarification_required"],
  "domains": {
    "accident": {
      "schemas": {
        "accident_fact": [
          "road_layout",
          "vehicle_actions.self",
          "vehicle_actions.other",
          "signal_priority",
          "collision_location"
        ]
      }
    },
    "fine_notice": {
      "schemas": {
        "fine_notice_intake": [
          "fine_type",
          "notice_stage",
          "issuing_authority",
          "notice_date",
          "due_date",
          "amount",
          "alleged_violation"
        ]
      }
    },
    "objection": {
      "schemas": {
        "objection_intake": [
          "requested_action",
          "disputed_facts",
          "objection_reason",
          "evidence_references",
          "deadline_clarification_required",
          "legal_issue_terms"
        ]
      }
    }
  },
  "token_classes": {
    "negation": ["않", "아니", "못", "없"],
    "uncertainty": ["것 같다", "같아요", "아마", "모르겠다", "기억나지 않는다"],
    "particles": ["은", "는", "이", "가", "을", "를", "에서", "에게", "으로", "로"]
  },
  "fuzzy_confirmation_threshold": 0.9,
  "rules": [
    {
      "rule_id": "accident.road_layout.intersection.exact_01",
      "domain": "accident",
      "schema": "accident_fact",
      "field": "road_layout",
      "value": "intersection",
      "token_class": "entity",
      "canonical_expression": "교차로",
      "expressions": ["교차로"],
      "aliases": ["사거리"],
      "approved_typos": [],
      "decision": "auto_applied",
      "routing_intent": "accident_initial_consultation"
    }
  ]
}
```

`app/services/supervisor_input_normalization_service.py`의 로더는 다음 형태를 사용한다.

```python
POLICY_CONTRACT_VERSION = "supervisor_input_normalization_policy.v1"
DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "supervisor_input_normalization_policy.v1.json"
)


@lru_cache(maxsize=1)
def normalization_policy() -> dict[str, Any]:
    configured = os.environ.get("SUPERVISOR_INPUT_NORMALIZATION_POLICY_PATH", "").strip()
    path = Path(configured).expanduser() if configured else DEFAULT_POLICY_PATH
    policy = json.loads(path.read_text(encoding="utf-8"))
    _validate_policy(policy)
    return {**policy, "_source": str(path)}


def clear_normalization_policy_cache() -> None:
    normalization_policy.cache_clear()


def normalization_policy_metadata() -> dict[str, str]:
    policy = normalization_policy()
    return {
        "contract_version": str(policy["contract_version"]),
        "source": str(policy["_source"]),
    }
```

검증기는 계약 버전, 세 도메인, schema·field allowlist, 유일한 `rule_id`, 허용된
`decision`, 비어 있지 않은 `value`와 표현 목록을 확인한다.

- [ ] **Step 4: Wiki 문서에 실행 규칙과 동일한 필드 표를 기록한다**

`README.md`에는 `JSON이 실행의 유일한 기준`, `Wiki와 테스트 동시 갱신`,
`동적 운영 편집 없음`을 명시한다. 나머지 네 문서에는 다음 열을 가진 표를 작성한다.

```markdown
| 입력 예시 | 의미 분류 | schema.field | 정규화 값 | 처리 | 금지 조건 |
|---|---|---|---|---|---|
| 좌해전 | action | accident_fact.vehicle_actions.other | left_turn | 자동 | 부정 표현 |
| 1챠 고지서 | state | fine_notice_intake.notice_stage | first_notice | 자동 | 단계가 불명확한 단순 `고지서` |
| 이의 재기 | action | objection_intake.requested_action | objection | 자동 | 철회·부정 표현 |
```

- [ ] **Step 5: 정책 계약 테스트를 통과시킨다**

Run:

```powershell
python -m pytest test/test_supervisor_input_normalization_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Task 1을 커밋한다**

```powershell
git add -- app/config/supervisor_input_normalization_policy.v1.json app/services/supervisor_input_normalization_service.py test/test_supervisor_input_normalization_service.py docs/policies/supervisor-input-normalization
git commit -m "feat: define supervisor normalization policy"
```

---

### Task 2: 정확 표현·유사어·승인 오탈자 정규화

**Files:**

- Modify: `app/config/supervisor_input_normalization_policy.v1.json`
- Modify: `app/services/supervisor_input_normalization_service.py`
- Modify: `test/test_supervisor_input_normalization_service.py`
- Modify: `docs/policies/supervisor-input-normalization/accident-core.md`
- Modify: `docs/policies/supervisor-input-normalization/fine-notice.md`
- Modify: `docs/policies/supervisor-input-normalization/objection.md`

**Interfaces:**

- Produces: `normalize_supervisor_input(*, user_text: str, source_message_id: str) -> dict[str, Any]`
- Returns: `normalized_supervisor_input.v1`
- Consumes: Task 1의 `normalization_policy()`

- [ ] **Step 1: 정확·오탈자·구어체 매칭 실패 테스트를 작성한다**

```python
def test_normalizes_registered_accident_and_objection_phrases() -> None:
    result = service.normalize_supervisor_input(
        user_text="제가 직진했고 상대 차량은 좌해전했어요. 이의 재기하고 싶어요.",
        source_message_id="msg_normalize_1",
    )

    projected = {
        (item["field"], item["value"]): item
        for item in result["candidates"]
    }
    assert projected[("vehicle_actions.self", "straight")]["decision"] == "auto_applied"
    assert projected[("vehicle_actions.other", "left_turn")]["normalized_expression"] == "좌회전"
    assert projected[("requested_action", "objection")]["rule_id"] == (
        "objection.requested_action.objection.typo_01"
    )
    assert all(item["source_message_id"] == "msg_normalize_1" for item in projected.values())


def test_normalizes_notice_typo_and_preserves_source_span() -> None:
    text = "1챠 고지서를 받고 의견 재출을 준비 중입니다."
    result = service.normalize_supervisor_input(
        user_text=text,
        source_message_id="msg_normalize_2",
    )

    stage = next(item for item in result["candidates"] if item["field"] == "notice_stage")
    assert stage["value"] == "first_notice"
    assert stage["decision"] == "auto_applied"
    assert text[stage["source_span"]["start"]:stage["source_span"]["end"]] == stage["source_text"]
```

- [ ] **Step 2: 테스트가 후보 부재로 실패하는지 확인한다**

Run:

```powershell
python -m pytest test/test_supervisor_input_normalization_service.py -q
```

Expected: `candidates`가 없거나 필요한 field가 없어 FAIL.

- [ ] **Step 3: 실제 정책 규칙을 추가한다**

각 규칙은 다음 형태를 사용한다.

```json
{
  "rule_id": "fine_notice.notice_stage.first_notice.typo_01",
  "domain": "fine_notice",
  "schema": "fine_notice_intake",
  "field": "notice_stage",
  "value": "first_notice",
  "token_class": "state",
  "canonical_expression": "1차 고지서",
  "expressions": ["1차 고지서", "제1차 고지서"],
  "aliases": ["첫 고지서"],
  "approved_typos": ["1챠 고지서"],
  "decision": "auto_applied",
  "routing_intent": "fine_notice_procedure"
}
```

최소 규칙 집합은 다음 값을 포함한다.

- 사고: `intersection`, `straight`, `left_turn`, `right_turn`, `rear_end`,
  `self_green_signal`, `other_left_turn_signal`
- 과태료·범칙금: `fine`, `penalty`, `pre_notice`, `first_notice`, `payment_notice`
- 이의 절차: `opinion_submission`, `objection`, `payment_guidance`
- 법률 검색 쟁점어: `signal_violation`, `parking_violation`, `school_zone`,
  `driver_identity_dispute`

추가하는 모든 `rule_id`는 같은 Step에서 해당 도메인 Wiki 표에 원문 예시, canonical
value, decision, 부정·불확실 시 동작과 함께 기록한다. Task 1의 양방향 동기화 테스트가
JSON에만 있거나 Wiki에만 있는 rule ID를 모두 실패시킨다.

- [ ] **Step 4: 결정적 구간 매처를 구현한다**

`normalize_supervisor_input`은 다음 순서를 지킨다.

```python
def _nfkc_with_index_map(value: str) -> tuple[str, list[int]]:
    normalized: list[str] = []
    original_indexes: list[int] = []
    for index, character in enumerate(value):
        converted = unicodedata.normalize("NFKC", character)
        normalized.extend(converted)
        original_indexes.extend([index] * len(converted))
    return "".join(normalized), original_indexes


def normalize_supervisor_input(*, user_text: str, source_message_id: str) -> dict[str, Any]:
    original = str(user_text or "")
    normalized, original_indexes = _nfkc_with_index_map(original)
    matches = _registered_matches(
        original=original,
        normalized=normalized,
        original_indexes=original_indexes,
    )
    candidates = _prefer_longest_non_overlapping(matches)
    return {
        "contract_version": "normalized_supervisor_input.v1",
        "policy_version": POLICY_CONTRACT_VERSION,
        "candidates": [
            _candidate_from_match(item, source_message_id=source_message_id)
            for item in candidates
        ],
        "clarifications": [],
    }
```

`_registered_matches`는 `expressions`, `aliases`, `approved_typos`를 긴 문자열부터
찾는다. 같은 schema·field에서 구간이 겹치면 가장 긴 표현 하나만 남긴다.
`approved_typos`는 정책에 명시된 경우에만 `auto_applied`가 된다.
형태 토큰은 `re.finditer(r"[가-힣A-Za-z0-9]+", normalized)`로 찾고, 정책에 등록된
조사가 토큰 끝에 붙어 있으며 제거 후 두 글자 이상 남을 때만 조사 없는 비교 토큰을
추가한다. 후보의 `token_class`는 정책값 `entity`, `action`, `state`, `modifier` 중
하나이며 범용 품사 태깅을 시도하지 않는다.

- [ ] **Step 5: Task 2 테스트를 통과시킨다**

Run:

```powershell
python -m pytest test/test_supervisor_input_normalization_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Task 2를 커밋한다**

```powershell
git add -- app/config/supervisor_input_normalization_policy.v1.json app/services/supervisor_input_normalization_service.py test/test_supervisor_input_normalization_service.py docs/policies/supervisor-input-normalization/accident-core.md docs/policies/supervisor-input-normalization/fine-notice.md docs/policies/supervisor-input-normalization/objection.md
git commit -m "feat: normalize supervisor domain phrases"
```

---

### Task 3: 조사·어미, 부정·불확실성, 유사 후보 게이트

**Files:**

- Modify: `app/services/supervisor_input_normalization_service.py`
- Modify: `test/test_supervisor_input_normalization_service.py`

**Interfaces:**

- Produces: 후보의 `negated`, `uncertain`, `decision`
- Produces: `clarifications: list[dict[str, Any]]`
- Consumes: 정책의 `token_classes`와 `fuzzy_confirmation_threshold=0.9`

- [ ] **Step 1: 부정·불확실·미등록 오탈자 실패 테스트를 작성한다**

```python
def test_negated_action_is_never_auto_applied() -> None:
    result = service.normalize_supervisor_input(
        user_text="상대 차량은 좌회전하지 않았습니다.",
        source_message_id="msg_negated",
    )
    action = next(item for item in result["candidates"] if item["value"] == "left_turn")

    assert action["negated"] is True
    assert action["decision"] == "clarification_required"
    assert result["clarifications"][0]["field"] == "vehicle_actions.other"


def test_uncertain_action_requires_confirmation() -> None:
    result = service.normalize_supervisor_input(
        user_text="상대가 좌회전한 것 같아요.",
        source_message_id="msg_uncertain",
    )
    action = next(item for item in result["candidates"] if item["value"] == "left_turn")

    assert action["uncertain"] is True
    assert action["decision"] == "confirmation_required"


def test_unique_unregistered_typo_is_confirmation_only() -> None:
    result = service.normalize_supervisor_input(
        user_text="상대 차량이 좌회잔했어요.",
        source_message_id="msg_fuzzy",
    )
    action = next(item for item in result["candidates"] if item["value"] == "left_turn")

    assert action["match_kind"] == "fuzzy"
    assert action["decision"] == "confirmation_required"


def test_bare_notice_does_not_guess_legal_stage() -> None:
    result = service.normalize_supervisor_input(
        user_text="고지서를 받았습니다.",
        source_message_id="msg_ambiguous",
    )

    assert not any(item["field"] == "notice_stage" and item["decision"] == "auto_applied" for item in result["candidates"])
    assert any(item["field"] == "notice_stage" for item in result["clarifications"])
```

- [ ] **Step 2: 테스트가 현재 자동 후보 또는 후보 부재로 실패하는지 확인한다**

Run:

```powershell
python -m pytest test/test_supervisor_input_normalization_service.py -q
```

Expected: 부정·불확실·fuzzy·법적 단계 게이트가 없어 FAIL.

- [ ] **Step 3: 절 단위 부정·불확실성 판정을 구현한다**

문장부호와 접속 표현으로 나눈 같은 절에서 매칭 구간 뒤 12자와 앞 8자를 확인한다.

```python
def _apply_semantic_guards(
    candidate: dict[str, Any],
    *,
    clause: str,
    relative_start: int,
    relative_end: int,
) -> dict[str, Any]:
    before = clause[max(0, relative_start - 8):relative_start]
    after = clause[relative_end:relative_end + 12]
    local_context = f"{before}{after}"
    token_classes = normalization_policy()["token_classes"]
    negated = any(token in local_context for token in token_classes["negation"])
    uncertain = any(token in local_context for token in token_classes["uncertainty"])
    decision = candidate["decision"]
    if negated:
        decision = "clarification_required"
    elif uncertain:
        decision = "confirmation_required"
    return {**candidate, "negated": negated, "uncertain": uncertain, "decision": decision}
```

부정 토큰이 다른 주어의 절에 있는 경우 영향을 주지 않도록 절 경계를 넘지 않는다.

- [ ] **Step 4: 유일 후보 fuzzy 매칭과 재질문 생성을 구현한다**

표준 라이브러리 `difflib.SequenceMatcher`만 사용한다. 길이 3 이상인 미등록 토큰이
한 개의 정책 표현과 `ratio >= 0.9`로 일치할 때만 `confirmation_required` 후보를
만든다. 동률 후보 또는 0.9 미만은 `clarification_required`로 남긴다. fuzzy 후보는
절대 `auto_applied`로 승격하지 않는다.

- [ ] **Step 5: Task 3 테스트를 통과시킨다**

Run:

```powershell
python -m pytest test/test_supervisor_input_normalization_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Task 3을 커밋한다**

```powershell
git add -- app/services/supervisor_input_normalization_service.py test/test_supervisor_input_normalization_service.py
git commit -m "feat: gate ambiguous normalized facts"
```

---

### Task 4: 라우팅과 재질문 연결

**Files:**

- Create: `app/services/supervisor_input_projection_service.py`
- Create: `test/test_supervisor_input_projection_service.py`
- Modify: `app/services/supervisor_routing_service.py`
- Modify: `app/services/chat_orchestration_service.py`
- Modify: `test/test_chat_orchestration_service.py`

**Interfaces:**

- Produces: `normalization_routing_hints(value: Mapping[str, Any]) -> list[str]`
- Produces: `normalization_pending_questions(value: Mapping[str, Any]) -> list[dict[str, Any]]`
- Extends: `route_supervisor_input(user_text, attachments, *, normalized_input=None) -> str`
- Consumes: Task 2·3의 `normalized_supervisor_input.v1`

- [ ] **Step 1: 오탈자 라우팅과 실행 차단 실패 테스트를 작성한다**

```python
def test_registered_notice_typo_routes_to_fine_notice_procedure() -> None:
    response = submit_message(
        {
            "session_id": "ses_normalized_route",
            "user_text": "과태료 1챠 고지서를 받고 이의 재기하려고 합니다.",
        }
    )

    assert response["routing_intent"] == "fine_notice_procedure"
    assert response["input_normalization"]["contract_version"] == "normalized_supervisor_input.v1"


def test_uncertain_normalized_value_stops_before_agent_plan() -> None:
    response = submit_message(
        {
            "session_id": "ses_normalized_question",
            "user_text": "범칙금인지 과태료인지 모르겠고 이의 재기하고 싶어요.",
        }
    )

    assert response["status"] == "needs_input"
    assert response["pending_questions"]
    assert response["analysis_plan"]["steps"] == []
    assert response["reporting_payload"] is None


def test_normalizer_failure_keeps_original_routing_without_logging_raw_text(
    monkeypatch, caplog
) -> None:
    marker = "과태료-private-marker"
    monkeypatch.setattr(
        "app.services.chat_orchestration_service.normalize_supervisor_input",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("failed")),
    )

    response = submit_message({"session_id": "ses_normalizer_error", "user_text": marker})

    assert response["routing_intent"] == "fine_notice_procedure"
    assert response["input_normalization"]["candidates"] == []
    assert marker not in caplog.text
```

- [ ] **Step 2: 테스트가 오탈자 라우팅 또는 정규화 응답 부재로 실패하는지 확인한다**

Run:

```powershell
python -m pytest test/test_supervisor_input_projection_service.py test/test_chat_orchestration_service.py -q
```

Expected: 새 projection 또는 `input_normalization`이 없어 FAIL.

- [ ] **Step 3: 라우팅·질문 projection을 구현한다**

```python
DOMAIN_INTENT_ORDER = {
    "objection": "fine_notice_procedure",
    "fine_notice": "fine_notice_procedure",
    "accident": "accident_initial_consultation",
}


def normalization_routing_hints(value: Mapping[str, Any]) -> list[str]:
    return list(dict.fromkeys(
        DOMAIN_INTENT_ORDER[item["domain"]]
        for item in value.get("candidates", [])
        if isinstance(item, Mapping)
        and item.get("decision") == "auto_applied"
        and item.get("domain") in DOMAIN_INTENT_ORDER
    ))
```

`normalization_pending_questions`는 다음 field 질문표를 사용해 field별로 중복 제거한다.

```python
QUESTION_BY_NORMALIZED_FIELD = {
    "road_layout": "사고 장소의 도로 형태를 다시 확인해 주세요.",
    "vehicle_actions.self": "본인 차량이 어떻게 움직였는지 확인해 주세요.",
    "vehicle_actions.other": "상대 차량이 어떻게 움직였는지 확인해 주세요.",
    "signal_priority": "당시 신호 또는 우선권을 확인해 주세요.",
    "collision_location": "두 차량의 충돌 부위를 확인해 주세요.",
    "fine_type": "받은 문서가 과태료인지 범칙금인지 확인해 주세요.",
    "notice_stage": "문서가 사전통지서인지 납부고지서인지 확인해 주세요.",
    "requested_action": "의견제출, 이의신청, 납부 안내 중 원하는 절차를 확인해 주세요.",
}


def normalization_pending_questions(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    fields = list(dict.fromkeys(
        str(item.get("field") or "")
        for item in value.get("candidates", [])
        if isinstance(item, Mapping)
        and item.get("decision") in {"confirmation_required", "clarification_required"}
    ))
    fields.extend(
        str(item.get("field") or "")
        for item in value.get("clarifications", [])
        if isinstance(item, Mapping)
    )
    return [
        {"field": field, "question": QUESTION_BY_NORMALIZED_FIELD[field]}
        for field in dict.fromkeys(fields)
        if field in QUESTION_BY_NORMALIZED_FIELD
    ]
```

- [ ] **Step 4: 정규화를 입력 게이트 직후 연결한다**

`submit_message`에서 `safe_user_text` 확정 직후 다음 순서로 호출한다.

```python
def _normalize_input_safely(*, user_text: str, message_id: str) -> dict[str, Any]:
    try:
        return normalize_supervisor_input(
            user_text=user_text,
            source_message_id=message_id,
        )
    except Exception:
        logger.warning(
            "supervisor_input_normalization_failed",
            extra={"reason_code": "normalization_unavailable"},
        )
        return {
            "contract_version": "normalized_supervisor_input.v1",
            "policy_version": "supervisor_input_normalization_policy.v1",
            "candidates": [],
            "clarifications": [],
        }


input_normalization = _normalize_input_safely(
    user_text=user_text,
    message_id=message_id,
)
payload = {**payload, "input_normalization": input_normalization}
detected_routing_intent = route_supervisor_input(
    user_text,
    attachments,
    normalized_input=input_normalization,
)
```

정규화 이후 만들어지는 `_normalization_needs_input_response`,
`_supervisor_needs_input_response`, `_consultation_hold_response`,
`_supervisor_unavailable_response`, 정상 queued response에는 모두 동일한 top-level
`input_normalization`을 넣는다. 개인정보 또는 입력 의미 부족으로 정규화 전에 중단된
응답에는 이 필드를 추가하지 않는다. 기존 함수에는 keyword-only
`input_normalization: dict[str, Any]` 인자를 추가해 호출부가 빠지면 테스트가 실패하게 한다.

첨부 목적과 기존 원문 keyword 매칭은 정규화 hint보다 먼저 적용한다. 정규화 질문이
있으면 `_normalization_needs_input_response`로 `status=needs_input`, 빈 plan,
`reporting_payload=None`, top-level `input_normalization`을 반환한다.

- [ ] **Step 5: 라우팅·재질문 테스트를 통과시킨다**

Run:

```powershell
python -m pytest test/test_supervisor_input_projection_service.py test/test_chat_orchestration_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Task 4를 커밋한다**

```powershell
git add -- app/services/supervisor_input_projection_service.py app/services/supervisor_routing_service.py app/services/chat_orchestration_service.py test/test_supervisor_input_projection_service.py test/test_chat_orchestration_service.py
git commit -m "feat: route normalized supervisor input"
```

---

### Task 5: 사고 핵심 사실 projection과 확정 우선순위

**Files:**

- Modify: `app/services/supervisor_input_projection_service.py`
- Modify: `app/services/chat_orchestration_service.py`
- Modify: `test/test_supervisor_input_projection_service.py`
- Modify: `test/test_chat_orchestration_service.py`
- Modify: `test/test_supervisor_control_service.py`

**Interfaces:**

- Produces: `accident_fact_candidates(value, *, source_message_id) -> list[dict[str, Any]]`
- Produces: `accident_fact_sources(value, *, source_message_id) -> list[dict[str, Any]]`
- Consumes: `reduce_consultation_fact_state(..., fact_candidates=..., fact_sources=...)`

- [ ] **Step 1: 사고 사실 projection 실패 테스트를 작성한다**

```python
def test_projects_both_vehicle_actions_as_one_accident_fact() -> None:
    normalized = normalize_supervisor_input(
        user_text="저는 직진했고 상대 차량은 좌해전했습니다.",
        source_message_id="msg_accident_projection",
    )

    assert accident_fact_candidates(
        normalized,
        source_message_id="msg_accident_projection",
    ) == [
        {
            "field": "vehicle_actions",
            "value": "본인 차량 직진, 상대 차량 좌회전",
            "source_message_id": "msg_accident_projection",
            "confidence": 0.99,
            "confirmed": False,
        }
    ]


def test_negated_vehicle_action_is_not_projected() -> None:
    normalized = normalize_supervisor_input(
        user_text="상대 차량은 좌회전하지 않았습니다.",
        source_message_id="msg_accident_negated",
    )

    assert accident_fact_candidates(normalized, source_message_id="msg_accident_negated") == []
```

`test/test_chat_orchestration_service.py`에는 오탈자 포함 첫 문장에서
`vehicle_actions`가 수집되고, 후속 질문의 사용자 확정 답변이 같은 field의 미확정
규칙·LLM 후보를 덮어쓰며 충돌을 만들지 않는 E2E 테스트를 추가한다.

- [ ] **Step 2: 테스트가 기존 정규식 projection 때문에 실패하는지 확인한다**

Run:

```powershell
python -m pytest test/test_supervisor_input_projection_service.py test/test_chat_orchestration_service.py test/test_supervisor_control_service.py -q
```

Expected: 오탈자 행동이 `vehicle_actions`로 투영되지 않아 FAIL.

- [ ] **Step 3: 사고 fact adapter를 구현한다**

`auto_applied`, `negated=False`, `uncertain=False` 후보만 사용한다.
`vehicle_actions.self=straight`와 `vehicle_actions.other=left_turn`이 모두 있을 때
기존 core field인 `vehicle_actions` 한 건으로 합친다. 단일 주체만 있으면 fact를 만들지
않고 기존 질문 흐름을 유지한다. 나머지 core field는 정책의 canonical Korean display
값으로 투영한다.

- [ ] **Step 4: 기존 same-message 정규식을 정책 projection으로 교체한다**

`_fallback_accident_supervisor_state`의 `_same_message_accident_fact_candidates(...)`
호출을 다음으로 교체하고 기존 함수는 삭제한다.

```python
accident_fact_candidates(
    payload.get("input_normalization") or {},
    source_message_id=str(payload.get("message_id") or payload.get("session_id") or ""),
)
```

`fact_sources`에는 `source_type="rule_normalization"`, `rule_id`,
`source_message_id`만 넣고 사용자 원문은 넣지 않는다.

- [ ] **Step 5: 확정 우선순위 회귀를 통과시킨다**

Run:

```powershell
python -m pytest test/test_supervisor_input_projection_service.py test/test_chat_orchestration_service.py test/test_supervisor_control_service.py -q
```

Expected: PASS, 기존 `test_fact_reducer_prefers_confirmed_followup_over_unconfirmed_llm_candidate` 포함.

- [ ] **Step 6: Task 5를 커밋한다**

```powershell
git add -- app/services/supervisor_input_projection_service.py app/services/chat_orchestration_service.py test/test_supervisor_input_projection_service.py test/test_chat_orchestration_service.py test/test_supervisor_control_service.py
git commit -m "feat: project normalized accident facts"
```

---

### Task 6: 과태료·범칙금·이의신청 slot과 Agent package 연결

**Files:**

- Modify: `app/services/supervisor_input_normalization_service.py`
- Modify: `app/services/supervisor_input_projection_service.py`
- Modify: `app/services/fine_notice_intake_service.py`
- Modify: `app/services/chat_orchestration_service.py`
- Modify: `test/test_supervisor_input_normalization_service.py`
- Modify: `test/test_supervisor_input_projection_service.py`
- Modify: `test/test_fine_notice_intake_service.py`
- Modify: `test/test_chat_orchestration_service.py`
- Modify: `test/test_supervisor_execution_input_service.py`

**Interfaces:**

- Produces: `fine_notice_intake_slots(value) -> dict[str, dict[str, Any]]`
- Produces: `normalized_slot_state(value) -> dict[str, Any]`
- Extends: `reduce_fine_notice_intake(payload)` with `normalized_slots`
- Consumes: existing `agent_input_schema.v1.payload.slot_state`

- [ ] **Step 1: 법률 입력과 slot projection 실패 테스트를 작성한다**

```python
def test_projects_notice_and_objection_slots_without_legal_conclusions() -> None:
    normalized = normalize_supervisor_input(
        user_text="과태료 1챠 고지서를 받아서 이의 재기하려고 합니다.",
        source_message_id="msg_notice_projection",
    )

    slot_state = normalized_slot_state(normalized)

    assert slot_state["contract_version"] == "slot_filling_state.v1"
    assert slot_state["slots"]["fine_type"]["value"] == "fine"
    assert slot_state["slots"]["notice_stage"]["value"] == "first_notice"
    assert slot_state["slots"]["requested_action"]["value"] == "objection"
    assert "legal_conclusion" not in slot_state["slots"]
    assert "law_article" not in slot_state["slots"]
```

`test/test_fine_notice_intake_service.py`에는 다음 우선순위를 고정한다.

```python
def test_confirmed_ocr_and_structured_slots_outrank_rule_normalization() -> None:
    result = reduce_fine_notice_intake(
        {
            "message_id": "msg_notice_priority",
            "fine_notice_slots": {"document_disposition_type": "사전통지"},
            "normalized_slots": {
                "document_disposition_type": {
                    "value": "first_notice",
                    "source_type": "rule_normalization",
                    "confidence": 0.99,
                    "confirmed": False,
                }
            },
        }
    )
    assert result["slots"]["document_disposition_type"]["value"] == "사전통지"
```

- [ ] **Step 2: 테스트가 slot projection 부재로 실패하는지 확인한다**

Run:

```powershell
python -m pytest test/test_supervisor_input_normalization_service.py test/test_supervisor_input_projection_service.py test/test_fine_notice_intake_service.py test/test_chat_orchestration_service.py test/test_supervisor_execution_input_service.py -q
```

Expected: 새 slot과 `normalized_slots`가 없어 FAIL.

- [ ] **Step 3: 숫자·날짜·기관의 제한 패턴을 구현한다**

정책 규칙 이외의 자유 NER는 하지 않는다. 다음 패턴만 후보로 만든다.

```python
DATE_PATTERN = re.compile(r"(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|20\d{2}년\s*\d{1,2}월\s*\d{1,2}일)")
AMOUNT_PATTERN = re.compile(r"\d{1,3}(?:,\d{3})*\s*원")
AUTHORITY_PATTERN = re.compile(r"[가-힣]{2,20}(?:경찰서|시청|구청|군청|도로교통공단)")
```

날짜가 하나면 `notice_date`가 아니라 `confirmation_required` 후보로 둔다. `납부기한`,
`의견제출기한`, `까지`가 같은 절에 있을 때만 `due_date`로 자동 투영한다. 금액과 기관은
원문 값을 보존하되 Agent slot에 넣기 전 숫자·허용 접미사 형식만 검증한다.

- [ ] **Step 4: 과태료 intake와 fallback slot_state에 projection을 병합한다**

projection은 `auto_applied`, `negated=False`, `uncertain=False` 후보만 사용한다.

```python
FINE_NOTICE_INTAKE_FIELD_MAP = {
    "notice_stage": "document_disposition_type",
    "issuing_authority": "issuing_authority",
    "due_date": "response_deadline",
}


def fine_notice_intake_slots(value: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    slots: dict[str, dict[str, Any]] = {}
    for candidate in value.get("candidates", []):
        if not isinstance(candidate, Mapping):
            continue
        target = FINE_NOTICE_INTAKE_FIELD_MAP.get(str(candidate.get("field") or ""))
        if not target or candidate.get("decision") != "auto_applied":
            continue
        if candidate.get("negated") or candidate.get("uncertain"):
            continue
        slots[target] = {
            "value": candidate["value"],
            "source_type": "rule_normalization",
            "source_message_id": candidate["source_message_id"],
            "confidence": candidate["confidence"],
            "confirmed": False,
        }
    return slots
```

`reduce_fine_notice_intake`의 우선순위를 다음으로 고정한다.

```text
fine_notice_slots의 사용자 구조화 입력
> user_confirmed_ocr
> conversation_history의 사용자 확정 답변
> normalized_slots의 auto_applied 미확정 값
> server_attachment
```

`fine_notice_intake` 응답에는 기존 필드를 유지하면서 `normalized_fields`를 additive하게
추가한다. `_fallback_supervisor_state`의 `slot_state.slots`에는 `normalized_slot_state`
결과를 병합하고, 생성되는 모든 law·appeal Agent package가 동일한 server-owned
`slot_state`를 받게 한다.

- [ ] **Step 5: worker 경계가 정규화 slot만 전달하는지 검증한다**

`test/test_supervisor_execution_input_service.py`에서 서버 package의 `fine_type`,
`notice_stage`, `requested_action`, `legal_issue_terms`가
`bind_supervisor_plan_step_payload` 결과에 유지되고, public request가 넣은 동일 key는
덮어쓰지 못하는 테스트를 추가한다. `supervisor_execution_input_service.py` 자체는 현재
server-owned package 바인딩으로 충분하므로 수정하지 않는다.

- [ ] **Step 6: Task 6 테스트를 통과시킨다**

Run:

```powershell
python -m pytest test/test_supervisor_input_normalization_service.py test/test_supervisor_input_projection_service.py test/test_fine_notice_intake_service.py test/test_chat_orchestration_service.py test/test_supervisor_execution_input_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Task 6을 커밋한다**

```powershell
git add -- app/services/supervisor_input_normalization_service.py app/services/supervisor_input_projection_service.py app/services/fine_notice_intake_service.py app/services/chat_orchestration_service.py test/test_supervisor_input_normalization_service.py test/test_supervisor_input_projection_service.py test/test_fine_notice_intake_service.py test/test_chat_orchestration_service.py test/test_supervisor_execution_input_service.py
git commit -m "feat: project normalized legal intake slots"
```

---

### Task 7: LLM 사실 후보 policy allowlist

**Files:**

- Modify: `app/services/supervisor_input_projection_service.py`
- Modify: `app/services/supervisor_llm_service.py`
- Modify: `test/test_supervisor_input_projection_service.py`
- Modify: `test/test_supervisor_llm_service.py`

**Interfaces:**

- Produces: `policy_allowed_llm_facts(items, *, scenario) -> list[dict[str, Any]]`
- Produces: `canonical_policy_value(*, field: str, value: Any) -> str | None`
- Consumes: `supervisor_conversation_state.v2.scenario`
- Applies inside: `_normalize_llm_state(...)`

- [ ] **Step 1: 허용되지 않은 LLM field·value 실패 테스트를 작성한다**

```python
def test_policy_allowlist_discards_unknown_accident_llm_fact() -> None:
    assert policy_allowed_llm_facts(
        [
            {"field": "road_layout", "value": "교차로"},
            {"field": "legal_conclusion", "value": "상대방이 전적으로 위법"},
        ],
        scenario="accident_initial_consultation",
    ) == [
        {"field": "road_layout", "value": "교차로"}
    ]


def test_policy_allowlist_does_not_expand_general_consultation() -> None:
    facts = [{"field": "user_text", "value": "일반 교통 문의"}]
    assert policy_allowed_llm_facts(facts, scenario="general_consultation") == facts
```

`test/test_supervisor_llm_service.py`에는 targeted scenario에서 unknown field가 최종
`state["collected_facts"]`에 남지 않고, 정책 허용 accident fact는 미확정 후보로 유지되는
테스트를 추가한다.

- [ ] **Step 2: 테스트가 현재 모든 `collected_facts` 수용 때문에 실패하는지 확인한다**

Run:

```powershell
python -m pytest test/test_supervisor_input_projection_service.py test/test_supervisor_llm_service.py -q
```

Expected: `legal_conclusion`이 남아 FAIL.

- [ ] **Step 3: targeted scenario allowlist를 구현한다**

대상 scenario는 다음으로 고정한다.

```python
TARGETED_SCENARIO_FIELDS = {
    "accident_initial_consultation": {
        "road_layout", "vehicle_actions", "signal_priority", "collision_location"
    },
    "fine_notice_procedure": {
        "fine_type", "notice_stage", "issuing_authority", "notice_date",
        "due_date", "amount", "alleged_violation", "requested_action",
        "disputed_facts", "objection_reason", "evidence_references",
        "deadline_clarification_required", "legal_issue_terms"
    },
    "fine_notice_analysis": {
        "fine_type", "notice_stage", "issuing_authority", "notice_date",
        "due_date", "amount", "alleged_violation", "requested_action",
        "disputed_facts", "objection_reason", "evidence_references",
        "deadline_clarification_required", "legal_issue_terms"
    },
}
```

대상 scenario에서는 field allowlist를 통과하고 값이 정책 canonical 값 또는 등록 표현으로
정규화되는 항목만 남긴다. 비대상 scenario는 기존 동작을 유지한다.

```python
def policy_allowed_llm_facts(items: Any, *, scenario: str) -> list[dict[str, Any]]:
    allowed = TARGETED_SCENARIO_FIELDS.get(scenario)
    facts = [dict(item) for item in items or [] if isinstance(item, Mapping)]
    if allowed is None:
        return facts
    projected: list[dict[str, Any]] = []
    for item in facts:
        field = str(item.get("field") or "").strip()
        if field not in allowed:
            continue
        value = canonical_policy_value(field=field, value=item.get("value"))
        if value is not None:
            projected.append({**item, "field": field, "value": value})
    return projected
```

- [ ] **Step 4: `_normalize_llm_state`에 allowlist를 적용한다**

```python
state["collected_facts"] = policy_allowed_llm_facts(
    _list_of_dicts(candidate["collected_facts"]),
    scenario=str(fallback_state.get("scenario") or ""),
)
```

`fact_conflicts`, server-owned `missing_fields`, packages, report gate 동작은 변경하지 않는다.

- [ ] **Step 5: Task 7 테스트를 통과시킨다**

Run:

```powershell
python -m pytest test/test_supervisor_input_projection_service.py test/test_supervisor_llm_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Task 7을 커밋한다**

```powershell
git add -- app/services/supervisor_input_projection_service.py app/services/supervisor_llm_service.py test/test_supervisor_input_projection_service.py test/test_supervisor_llm_service.py
git commit -m "fix: constrain supervisor llm fact candidates"
```

---

### Task 8: 통합 회귀와 프로덕션 빌드

**Files:**

- No production or documentation changes expected.

**Interfaces:**

- Verifies: JSON rule와 Wiki 예시의 `rule_id` 동기화
- Verifies: Dockerfile의 `COPY app ./app`로 기본 정책 JSON 포함
- Verifies: 전체 Python·Django·Frontend 회귀와 Vite build

- [ ] **Step 1: JSON-Wiki 양방향 동기화와 집중 회귀를 실행한다**

Run:

```powershell
python -m pytest test/test_supervisor_input_normalization_service.py test/test_supervisor_input_projection_service.py test/test_fine_notice_intake_service.py test/test_chat_orchestration_service.py test/test_supervisor_control_service.py test/test_supervisor_llm_service.py test/test_supervisor_execution_input_service.py -q
```

Expected: PASS.

- [ ] **Step 2: 전체 Python 회귀를 실행한다**

Run:

```powershell
python -m pytest test -q
```

Expected: 0 failed.

- [ ] **Step 3: 전체 Django chatbot 회귀를 실행한다**

Run:

```powershell
python backend/manage.py test chatbot
```

Expected: `System check identified no issues`, 0 failed.

- [ ] **Step 4: 프론트엔드 회귀와 프로덕션 빌드를 실행한다**

Run:

```powershell
node --test app/web/*.test.js
npm.cmd --prefix app/web run build
```

Expected: Node test 0 failed, Vite build exit 0. 기존 bundle-size 경고만 발생하면 경고로 기록하고 실패로 보지 않는다.

- [ ] **Step 5: 정책 패키징과 diff 범위를 확인한다**

Run:

```powershell
python -c "from app.services.supervisor_input_normalization_service import normalization_policy_metadata; print(normalization_policy_metadata())"
git diff --check
git status --short
```

Expected: 기본 정책 경로가 `app/config/supervisor_input_normalization_policy.v1.json`,
공백 오류 없음, 제공 파일과 사용자 검증 보고서가 staged 변경에 없음.

---

### Task 9: 병합·빌드 후 실제 파일 브라우저 인수 검증

**Files:**

- No repository file changes required.
- Test inputs only: `22-11-18-_.png`, `15-07-18-.jpg`, `form2_별지154_위반사실통지및과태료사전통지서.pdf`, `form3_별지152_과태료납부고지서원부_운전자.pdf`

**Interfaces:**

- Validates: production URL `https://skn27-traffic-pilot.duckdns.org/`
- Validates: `normalized_supervisor_input.v1`, `case_ready`, Case APIs, persisted report, objection draft
- Re-validates: confirmed follow-up answer precedence hotfix

- [ ] **Step 1: 최종 SHA가 dev에 병합되고 해당 SHA의 build가 완료됐는지 확인한다**

`origin/dev`의 병합 SHA와 AWS pipeline build SHA가 같은지 확인한다. 다른 SHA면 브라우저
인수 검증을 시작하지 않는다. 운영 수동 승인은 이 최종 SHA에만 수행한다.

- [ ] **Step 2: 사고 사실확인원 정상 페이지를 검증한다**

`22-11-18-_.png`를 `교통사고 사실확인원`으로 업로드하고 다음을 확인한다.

```text
OCR 결과가 성공 또는 허용된 partial
개인정보 마스킹 표시
문서의 실제 사고 사실과 일치하는 질문
오탈자·구어체 답변의 정규화
확정 답변 이후 거짓 fact conflict 없음
case_ready 표시
```

- [ ] **Step 3: 사고 사실확인원 잘린 페이지를 검증한다**

`15-07-18-.jpg`를 업로드한다. 부족한 페이지를 성공으로 꾸미지 않고 partial 또는 failed와
완전한 페이지 재업로드 안내를 표시해야 한다. 추정 사실이 input schema에 들어가면 실패다.

- [ ] **Step 4: 과태료 사전통지서를 검증한다**

`form2_별지154_위반사실통지및과태료사전통지서.pdf`를 `과태료 고지서`로 업로드하고
`notice_stage=pre_notice`, 기관·기한·위반 사실 확인 카드, 의견제출 경로를 확인한다.
`고지서`라는 단어만으로 부과 완료 단계가 만들어지면 실패다.

- [ ] **Step 5: 과태료 납부고지서를 검증한다**

`form3_별지152_과태료납부고지서원부_운전자.pdf`를 업로드하고 사전통지서와 다른
`notice_stage`가 생성되는지, 이의신청·납부 안내가 문서 단계에 맞는지 확인한다.

- [ ] **Step 6: 전체 Case·리포트 연결을 검증한다**

정상 사고 시나리오에서 다음 순서를 끝까지 실행한다.

```text
case_ready
→ 사건 생성
→ 사실 확정
→ 분석 실행
→ polling 완료
→ persisted report route
→ 실제 사건 자료가 반영된 상담 분석 리포트
→ 이의신청서 초안 진입
```

리포트가 임시 preview이거나 모든 항목이 `확인된 자료 없음`이면 실패다.

- [ ] **Step 7: 배포 판정을 기록한다**

네 파일과 전체 Case 연결이 모두 통과하면 PASS다. 하나라도 실패하면 다음 핫픽스로
넘어가지 않고, 재현 입력·단계·표시된 안전한 오류 코드만 기록한 뒤 해당 범위만 수정한다.

---

## Final Review Checklist

- [ ] 새 런타임 의존성이 추가되지 않았다.
- [ ] JSON 정책만 실행 기준이며 모든 rule ID가 Wiki에 존재한다.
- [ ] 부정·불확실·복수 후보는 자동 확정되지 않는다.
- [ ] 사용자 확정 사실이 미확정 규칙·LLM 후보보다 우선한다.
- [ ] 확인 또는 재질문이 필요한 후보가 Agent package에 들어가지 않는다.
- [ ] 법률 Agent에 법적 결론이나 생성된 조문이 주입되지 않는다.
- [ ] 전체 Python·Django·Frontend 회귀와 Vite build가 통과한다.
- [ ] 사용자 파일과 사용자 작성 검증 보고서가 커밋에 포함되지 않는다.
- [ ] 네 실제 파일의 배포 브라우저 검증과 persisted report·이의신청서 초안 연결이 통과한다.
