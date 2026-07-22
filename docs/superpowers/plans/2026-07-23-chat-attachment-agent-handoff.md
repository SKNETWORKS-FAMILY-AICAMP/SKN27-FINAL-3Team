# Chat Attachment Agent Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 채팅에서 검사 완료된 이미지·PDF·MP4를 드래그앤드롭으로 접수하고, 영상은 기존 Vision 파이프라인의 실제 실행 결과를 증거 분석·사례·법령 검색으로 안전하게 전달한다.

**Architecture:** 업로드 경계는 MIME와 목적을 검증해 영상만 `blackbox_video`로 정규화한다. `accident_evidence_analysis`는 기존 초동상담과 분리된 정적 Supervisor 계획으로 실행되며, Vision 결과는 실행별 임시 작업공간에서 생성·정제한 뒤 후속 검색 노드에만 전달된다. 영속화 시에는 재실행에 필요한 식별자와 계획 정보만 남기고 원본 바이트·경로·OCR 원문·예외 원문을 제거한다.

**Tech Stack:** React JSX/CSS, Django repository and Worker queue, Python 3, pytest, 기존 VideoMAE·YOLO·Qwen Vision 파이프라인, PostgreSQL 모델.

## Global Constraints

- #294의 1차 설계 검토는 이슈 의도와의 일치를 확인했고, 2차 설계 검토는 기존 초동상담 보류 흐름·mock Vision·공용 산출물 경로·개인정보 영속화 위험을 확인했다.
- `accident_initial_consultation`의 사실확인·사건 승격 보류 흐름은 변경하지 않는다.
- scan gate를 통과한 canonical `ready`/`clean` S3 첨부만 실제 Vision Worker에 전달한다.
- `accident_evidence_analysis`의 순서는 `input_context_validation → vision_media_analysis → text_ml_case_search → law_ground_search → agent_result_validation → final_response_merge`이며, 결과는 항상 `partial`이다.
- 고지서 OCR의 핵심 필드는 사용자가 화면에서 확인·수정한 뒤에만 법령 검색과 이의신청 판단으로 전달한다. OCR 결과가 고지서가 아니거나 입력 목적과 충돌하면 후속 실행 대신 추가 확인을 요청한다.
- 이 경로에서는 과실비율, 법적 책임, 최종 사고유형, 이의신청·보고서 생성, 새 Vision 모델·제공자·학습·성능 튜닝을 구현하지 않는다.
- 사용자 응답, DB, 이벤트·운영 trace에는 원본 파일 바이트, OCR 원문, 전체 사용자 문장, 내부 경로, storage URI, 비밀값, 예외 원문을 남기지 않는다.
- 실제 Vision smoke test는 체크포인트와 의존성이 준비된 환경에서만 수행한다. CI는 subprocess를 대체한 계약 테스트만 수행한다.
- Git 작업은 이 작업공간에서 변경한 파일만 명시적으로 스테이징·커밋·푸시한다. 이슈·PR·머지·worktree 생성은 수행하지 않는다.

---

## File Structure

| 경로 | 책임 |
| --- | --- |
| `backend/chatbot/attachment_intake_policy.py` | canonical 업로드의 MIME·목적·파일 유형 정규화와 안정된 거부 코드 |
| `backend/chatbot/repositories.py` | intake 적용, AgentResult raw execution metadata 축소, 재수화 호환성 유지 |
| `app/config/supervisor_routing_policy.v1.json` | 영상 전용 intent와 고정 실행 계획, 부분 결과 정책 |
| `app/config/service_scope_policy.v1.json` | 차량 간 영상 증거 분석의 지원 범위·제한 문구 |
| `app/services/supervisor_routing_service.py` | 라우팅 정책 검증과 partial-only intent 정책 노출 |
| `app/services/chat_orchestration_service.py` | 전용 intent의 report 차단, `evidence_only` 실행 컨텍스트 |
| `app/services/supervisor_control_service.py` | evidence-only 병합의 `partial` 상태와 비결정적 응답 경계 |
| `ai/vision/run_to_supervisor.py` | 한국어 학습 라벨의 canonical label 변환 및 Qwen 오류 정규화 |
| `ai/vision/build_supervisor_handoff.py` | 내부 경로·원본 참조를 빼고 Worker에 넘길 최소 Vision handoff 생성 |
| `app/services/vision_media_analysis_adapter.py` | scan-ready 영상 materialize, preflight, 격리 subprocess, 안정 오류 코드, handoff allowlist |
| `app/services/agent_node_service.py` | Vision을 mock에서 실제 sync adapter로 전환하고 Adapter contract에 등록 |
| `app/web/FrontendAppShell.jsx` | 파일 선택과 DnD의 단일 intake handler, 영상 목적 정규화, 상태·오류 표기 |
| `app/web/styles.css` | 활성 drop zone 및 파일 상태의 접근 가능한 시각 상태 |
| `docs/ops/vision-media-adapter-runbook.md` | preflight, 실패 코드, safe trace, 선택적 smoke test 운영 절차 |

## Task 1: Canonical attachment intake policy

**Files:**
- Create: `backend/chatbot/attachment_intake_policy.py`
- Modify: `backend/chatbot/repositories.py:585-618`
- Test: `test/test_attachment_intake_policy.py`
- Test: `test/test_attachment_mock_service.py`

**Interfaces:**
- Consumes: multipart file의 `content_type`, `name`, 요청 `purpose`.
- Produces: `classify_attachment_intake(content_type: str, filename: str, purpose: str) -> dict[str, str | bool]`.
- Stable failure codes: `unsupported_media_type`, `purpose_media_mismatch`.

- [x] **Step 1: Write failing policy tests for accepted video and rejected MIME/purpose combinations.**

```python
from chatbot.attachment_intake_policy import classify_attachment_intake


def test_mp4_is_normalized_to_the_blackbox_video_route() -> None:
    decision = classify_attachment_intake(
        content_type="video/mp4",
        filename="dashcam.mp4",
        purpose="unknown",
    )

    assert decision == {
        "accepted": True,
        "error_code": "",
        "file_type": "video",
        "routing_purpose": "blackbox_video",
        "purpose_conflict": False,
    }


def test_video_with_document_purpose_is_rejected_before_storage() -> None:
    decision = classify_attachment_intake(
        content_type="video/mp4",
        filename="dashcam.mp4",
        purpose="fine_notice",
    )

    assert decision["accepted"] is False
    assert decision["error_code"] == "purpose_media_mismatch"


def test_executable_mime_is_not_an_attachment_analysis_input() -> None:
    decision = classify_attachment_intake(
        content_type="application/x-msdownload",
        filename="unsafe.exe",
        purpose="unknown",
    )

    assert decision["accepted"] is False
    assert decision["error_code"] == "unsupported_media_type"
```

- [x] **Step 2: Run the focused tests to verify the new module is absent.**

Run: `python -m pytest backend/chatbot/test_file_retention.py test/test_attachment_mock_service.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'chatbot.attachment_intake_policy'` after the new import is added to the tests.

- [x] **Step 3: Implement one MIME allowlist and normalize only the routing purpose.**

```python
# backend/chatbot/attachment_intake_policy.py
from __future__ import annotations

from pathlib import Path


_MIME_TO_FILE_TYPE = {
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "application/pdf": "pdf",
    "video/mp4": "video",
    "video/quicktime": "video",
}
_DOCUMENT_PURPOSES = {
    "fine_notice",
    "accident_scene",
    "evidence",
    "traffic_accident_confirmation",
    "unknown",
}


def classify_attachment_intake(*, content_type: str, filename: str, purpose: str) -> dict[str, str | bool]:
    normalized_mime = str(content_type or "").split(";", 1)[0].strip().lower()
    file_type = _MIME_TO_FILE_TYPE.get(normalized_mime, "")
    requested_purpose = str(purpose or "unknown").strip() or "unknown"
    if not file_type:
        return {
            "accepted": False,
            "error_code": "unsupported_media_type",
            "file_type": "",
            "routing_purpose": "",
            "purpose_conflict": False,
        }
    if file_type == "video":
        conflict = requested_purpose not in {"unknown", "blackbox_video"}
        return {
            "accepted": not conflict,
            "error_code": "purpose_media_mismatch" if conflict else "",
            "file_type": "video",
            "routing_purpose": "blackbox_video",
            "purpose_conflict": conflict,
        }
    accepted = requested_purpose in _DOCUMENT_PURPOSES
    return {
        "accepted": accepted,
        "error_code": "purpose_media_mismatch" if not accepted else "",
        "file_type": file_type,
        "routing_purpose": requested_purpose,
        "purpose_conflict": not accepted,
    }
```

In `register_uploaded_file`, call the classifier before `register_mock_attachment`, raise `UploadValidationError(str(decision["error_code"]))` on rejection, and pass `routing_purpose` into `registration_payload["purpose"]`. Persist only `file_type`, `routing_purpose`, and `purpose_conflict` under existing safe metadata; do not persist the filename-derived decision rationale.

- [x] **Step 4: Run the focused tests and the canonical upload API contract.**

Run: `python -m pytest test/test_attachment_intake_policy.py test/test_attachment_mock_service.py -q`

Expected: PASS; `video/mp4` is accepted as `blackbox_video`, legacy `supporting_evidence` is normalized to `evidence`, and executable MIME/video-purpose mismatch produce only stable validation codes.

Run: `& 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend/manage.py test chatbot.test_consultation_v2 -v 1`

Expected: PASS; canonical upload preserves existing session/case ownership responses after intake normalization.

- [x] **Step 5: Commit the intake boundary.**

```bash
git add backend/chatbot/attachment_intake_policy.py backend/chatbot/repositories.py test/test_attachment_intake_policy.py test/test_attachment_mock_service.py docs/superpowers/plans/2026-07-23-chat-attachment-agent-handoff.md
git commit -m "feat(#294): validate attachment intake routing"
```

### Task 2: Add the evidence-only video Supervisor route

**Files:**
- Modify: `app/config/supervisor_routing_policy.v1.json`
- Modify: `app/config/service_scope_policy.v1.json`
- Modify: `app/services/supervisor_routing_service.py:25-150`
- Modify: `app/services/chat_orchestration_service.py:114-255,779-819`
- Modify: `app/services/supervisor_control_service.py:101-190,267-299`
- Test: `test/test_chat_orchestration_service.py`
- Test: `test/test_service_scope_policy_service.py`
- Test: `test/test_supervisor_control_service.py`

**Interfaces:**
- Consumes: `purpose="blackbox_video"` on a scan-ready attachment.
- Produces: routing intent `accident_evidence_analysis`, no report plan step, `evidence_only=True` in validation and merge step contexts.
- Preserves: `accident_initial_consultation` remains the only route that enters `_consultation_hold_response`.

- [ ] **Step 1: Write failing tests for exact plan order, no report node, and unchanged text-only consultation.**

```python
def test_blackbox_video_uses_partial_evidence_plan_without_a_report() -> None:
    response = submit_message(
        {
            "session_id": "ses_video_1",
            "user_text": "블랙박스 영상의 관련 법령과 사례를 확인해 주세요.",
            "attachments": [{"attachment_id": "att_video_1", "purpose": "blackbox_video", "status": "ready"}],
        }
    )

    assert response["routing_intent"] == "accident_evidence_analysis"
    assert [step["node_code"] for step in response["analysis_plan"]["steps"]] == [
        "input_context_validation",
        "vision_media_analysis",
        "text_ml_case_search",
        "law_ground_search",
        "agent_result_validation",
        "final_response_merge",
    ]
    assert response["reporting_payload"] is None
    assert response["analysis_plan"]["steps"][-2]["context"]["evidence_only"] is True


def test_text_only_accident_still_waits_for_fact_confirmation() -> None:
    response = submit_message({"session_id": "ses_text_only", "user_text": "교차로 충돌 사고입니다."})

    assert response["routing_intent"] == "accident_initial_consultation"
    assert response["status"] == "needs_input"
    assert response["analysis_plan"]["steps"] == []
```

- [ ] **Step 2: Run the focused tests to verify the policy has no video route.**

Run: `python -m pytest test/test_chat_orchestration_service.py test/test_service_scope_policy_service.py test/test_supervisor_control_service.py -q`

Expected: FAIL because `blackbox_video` falls through to `general_consultation` and there is no `evidence_only` context.

- [ ] **Step 3: Add the versioned route and force non-determinative final merging.**

Add this rule before keyword rules and this plan to `supervisor_routing_policy.v1.json`:

```json
{
  "intent": "accident_evidence_analysis",
  "attachment_purposes": ["blackbox_video"],
  "keywords": []
}
```

```json
"accident_evidence_analysis": [
  "input_context_validation",
  "vision_media_analysis",
  "text_ml_case_search",
  "law_ground_search",
  "agent_result_validation",
  "final_response_merge"
]
```

Add `accident_evidence_analysis` to `supported_intents` with `scope_code` `vehicle_to_vehicle_video_evidence`, a limitation that it does not determine fault ratio or legal liability, and a next action requesting missing factual context. Add `partial_result_intents: ["accident_evidence_analysis"]` to `agent_result_validation_policy`, then validate it as a string list in `supervisor_routing_service._validate_policy` and return it from `agent_result_validation_policy`.

In `chat_orchestration_service.py`, compute report intent as follows and place `evidence_only` in both internal-node contexts:

```python
report_requested = (
    report_generation_requested(user_text)
    and routing_intent != "accident_evidence_analysis"
)

# inside _analysis_plan
evidence_only = routing_intent == "accident_evidence_analysis"
if node_code == "agent_result_validation":
    context.update({
        "expected_node_codes": expected_node_codes,
        "report_requested": report_requested,
        "evidence_only": evidence_only,
    })
elif node_code == "final_response_merge":
    context.update({
        "pending_questions": list(supervisor_state.get("next_questions") or []),
        "evidence_only": evidence_only,
    })
```

Extend `validate_agent_results(..., evidence_only: bool)` to return `"result_status": "partial" if evidence_only else normal_status`. Extend `merge_final_response(..., evidence_only: bool)` so it uses the fixed statement below as the response prefix, excludes report links/cards, and retains only sanitized evidence and law/case references:

```python
EVIDENCE_ONLY_NOTICE = (
    "영상과 참고 근거를 증거 검토용으로 정리했습니다. "
    "이 결과는 과실비율, 법적 책임, 최종 사고유형을 확정하지 않습니다."
)
```

- [ ] **Step 4: Run policy, scope, and Supervisor tests.**

Run: `python -m pytest test/test_chat_orchestration_service.py test/test_service_scope_policy_service.py test/test_supervisor_control_service.py -q`

Expected: PASS; the video path has exactly six ordered steps, its validation/final response status is `partial`, and no text-only accident route is changed.

- [ ] **Step 5: Commit the Supervisor route.**

```bash
git add app/config/supervisor_routing_policy.v1.json app/config/service_scope_policy.v1.json app/services/chat_orchestration_service.py app/services/supervisor_control_service.py test/test_chat_orchestration_service.py test/test_service_scope_policy_service.py test/test_supervisor_control_service.py
git commit -m "feat(#294): add video evidence analysis route"
```

### Task 3: Make the existing Vision handoff safe and callable

**Files:**
- Modify: `ai/vision/run_to_supervisor.py:101-135`
- Modify: `ai/vision/build_supervisor_handoff.py:39-161`
- Test: `test/test_vision_run_to_supervisor.py`

**Interfaces:**
- Consumes: existing `run(input_path, checkpoint=...) -> Path` contract.
- Produces: a handoff that contains time-based evidence identifiers, object summaries, limitations, and `not_determined_by_vision`, but not local paths, source video URI, model checkpoint path, or raw Qwen exception text.
- Required correctness fix: map `trained_category_classifier.LABELS` before selecting `BEST_YOLO_MODELS`.

- [ ] **Step 1: Add failing tests for Korean class-label routing and handoff redaction.**

```python
def test_korean_videomae_label_routes_to_a_yolo_model() -> None:
    prediction, model = select_yolo_model(
        {"clips": [{"top_predictions": [{"label": "차대차", "score": 0.9}]}]}
    )

    assert prediction["raw_label"] == "차대차"
    assert prediction["label"] == "car_vs_car"
    assert model == "yolov8m.pt"


def test_handoff_drops_local_paths_and_qwen_exception_text() -> None:
    handoff = build_handoff({
        "status": "partial",
        "vision_agent_output": {"agent_output": {"structured_result": {
            "key_frames": [{"frame_path": "C:/private/frame.jpg", "timestamp_sec": 1.2}],
            "qwen_analysis": {"valid": False, "error": "RuntimeError: private path"},
        }, "metadata": {"source_path": "C:/private/video.mp4"}}},
    })

    serialized = json.dumps(handoff, ensure_ascii=False)
    assert "C:/private" not in serialized
    assert "RuntimeError" not in serialized
```

- [ ] **Step 2: Run the Vision unit test file to verify the tests fail.**

Run: `python -m pytest test/test_vision_run_to_supervisor.py -q`

Expected: FAIL because `select_yolo_model` receives the Korean label unchanged and the current handoff contains `source_video`, `frame_path`, and raw Qwen error text.

- [ ] **Step 3: Apply the label conversion and output allowlist.**

```python
# ai/vision/run_to_supervisor.py, inside select_yolo_model
from ai.vision.trained_category_classifier import LABELS

raw_label = str(prediction["label"])
label = LABELS.get(raw_label, raw_label)
prediction = {
    **prediction,
    "label": label,
    "raw_label": raw_label,
    "requires_review": score < min_confidence,
}
```

Replace `safe_analyze_qwen`'s exception payload with this stable form:

```python
return {
    "valid": False,
    "error_code": "vision_qwen_unavailable",
    "requires_review": True,
    "limitations": ["Qwen analysis was unavailable; VideoMAE and YOLO results remain available."],
}
```

In `build_supervisor_handoff.py`, remove `source_video`, all `frame_path` fields, model-name/path fields, raw `qwen.error`, the report-agent routing recommendation, and fault-ratio recommendation fields. Keep only `frame_id`, `timestamp_sec`, `frame_role`, `selection_reason`, evidence IDs/types/timestamps/object classes/scores, detected-object counts, canonical prediction label/score, Qwen `valid`/summary/uncertainties/review flag/error code, limitations, and `NOT_DETERMINED_BY_VISION`.

- [ ] **Step 4: Run the Vision tests.**

Run: `python -m pytest test/test_vision_run_to_supervisor.py -q`

Expected: PASS; the real pipeline keeps its callable interface, Korean labels select a model, and serialized handoff data contains no local path or raw exception diagnostic.

- [ ] **Step 5: Commit Vision source hardening.**

```bash
git add ai/vision/run_to_supervisor.py ai/vision/build_supervisor_handoff.py test/test_vision_run_to_supervisor.py
git commit -m "fix(#294): harden vision supervisor handoff"
```

### Task 4: Add the isolated Vision Worker adapter and replace the mock node

**Files:**
- Create: `app/services/vision_media_analysis_adapter.py`
- Modify: `app/services/agent_node_service.py:1-70,157-173,615-624,1152-1170,1827-1854`
- Test: `test/test_vision_media_analysis_adapter.py`
- Test: `test/test_agent_node_service.py`
- Test: `test/test_supervisor_plan_execution.py`

**Interfaces:**
- Consumes: a canonical attachment with `purpose="blackbox_video"`, `metadata_source="canonical_scan_gate"`, `resolution_status="scan_ready"`, `status="ready"`, `scan_status="clean"`, and ready uploaded-file object storage metadata.
- Produces: `run_vision_media_analysis(agent_input: dict[str, Any], adapter_context: dict[str, Any]) -> dict[str, Any]`, a raw adapter result compatible with `_complete_adapter_output`.
- Stable failure codes: `attachment_not_scan_ready`, `vision_checkpoint_missing`, `vision_dependency_missing`, `vision_media_decode_failed`, `vision_execution_timeout`, `vision_execution_failed`.

- [ ] **Step 1: Write failing adapter tests with no real Vision dependency.**

```python
def test_adapter_runs_in_an_execution_scoped_workspace_and_returns_partial(monkeypatch) -> None:
    monkeypatch.setenv("VISION_TRAINED_CLASSIFIER_CHECKPOINT", "C:/models/checkpoint")
    monkeypatch.setattr(adapter, "_read_scan_ready_video_bytes", lambda _attachment: b"video")
    monkeypatch.setattr(adapter, "_checkpoint_is_complete", lambda _path: True)
    monkeypatch.setattr(adapter, "_run_vision_subprocess", _write_safe_handoff)

    result = adapter.run_vision_media_analysis(
        _canonical_video_input(),
        {"execution_id": "exec_vision_1"},
    )

    assert result["status"] == "partial"
    assert result["structured_result"]["analysis_kind"] == "accident_evidence"
    assert result["structured_result"]["not_determined_by_vision"]
    assert "C:/" not in repr(result)


def test_missing_checkpoint_returns_a_stable_failure_without_path(monkeypatch) -> None:
    monkeypatch.delenv("VISION_TRAINED_CLASSIFIER_CHECKPOINT", raising=False)

    result = adapter.run_vision_media_analysis(_canonical_video_input(), {"execution_id": "exec_vision_2"})

    assert result["status"] == "partial"
    assert result["structured_result"]["error_code"] == "vision_checkpoint_missing"
    assert "checkpoint" not in result["summary"].lower()
```

- [ ] **Step 2: Run focused adapter and registry tests to verify they fail.**

Run: `python -m pytest test/test_vision_media_analysis_adapter.py test/test_agent_node_service.py -q`

Expected: FAIL because the adapter does not exist and `vision_media_analysis` is still advertised as mock-only.

- [ ] **Step 3: Implement preflight, subprocess isolation, and a strict handoff allowlist.**

```python
# app/services/vision_media_analysis_adapter.py
def run_vision_media_analysis(agent_input: dict[str, Any], adapter_context: dict[str, Any]) -> dict[str, Any]:
    attachment = _select_scan_ready_video(agent_input.get("attachments") or [])
    if attachment is None:
        return _failure("attachment_not_scan_ready")
    checkpoint = _configured_checkpoint()
    if checkpoint is None or not _checkpoint_is_complete(checkpoint):
        return _failure("vision_checkpoint_missing")
    with TemporaryDirectory(prefix=f"vision-{_safe_execution_id(adapter_context)}-") as directory:
        workspace = Path(directory)
        input_path = workspace / "input.mp4"
        input_path.write_bytes(_read_scan_ready_video_bytes(attachment))
        completed = _run_vision_subprocess(input_path=input_path, checkpoint=checkpoint, workspace=workspace)
        if completed.returncode != 0:
            return _failure(_subprocess_failure_code(completed))
        handoff_path = _single_handoff_path(workspace)
        return _success(_safe_worker_handoff(json.loads(handoff_path.read_text(encoding="utf-8"))))


def _failure(error_code: str) -> dict[str, Any]:
    return {
        "status": "partial",
        "execution_status": "degraded",
        "summary": "영상 증거 분석을 완료하지 못해 재시도 또는 자료 확인이 필요합니다.",
        "structured_result": {"analysis_kind": "accident_evidence", "error_code": error_code},
        "evidence": [],
        "next_actions": ["review_video_analysis_preflight"],
        "limitations": ["Vision result is unavailable; no fault or legal conclusion was produced."],
    }


def _success(handoff: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "partial",
        "execution_status": "completed_with_review_required",
        "summary": "영상에서 확인 가능한 증거와 제한사항을 정리했습니다.",
        "structured_result": handoff,
        "evidence": list(handoff.get("evidence") or []),
        "next_actions": ["review_evidence_with_case_and_law_sources"],
        "limitations": list(handoff.get("limitations") or []),
    }
```

`_run_vision_subprocess` must invoke `sys.executable -m ai.vision.run_to_supervisor`, set `cwd=workspace`, prepend repository root to `PYTHONPATH`, use `capture_output=True`, and apply `VISION_RUNTIME_TIMEOUT_SECONDS` (default `180`). It must never copy stdout/stderr, command text, local file path, or checkpoint path into a returned result. `_subprocess_failure_code` may inspect stderr only to classify `ModuleNotFoundError`/`ImportError` as `vision_dependency_missing`; all other non-zero exits map to `vision_execution_failed`.

`_safe_worker_handoff` must use an allowlist from Task 3 and set `analysis_kind="accident_evidence"`, `not_determined_by_vision`, and a `partial` status even when the subprocess succeeded.

In `agent_node_service.py`:

```python
DL_MOCK_NODE_CODES: set[str] = set()

# NODE_REGISTRY["vision_media_analysis"]
"required_inputs": ["attachments[purpose=blackbox_video, scan_ready]"],
"status": "sync_adapter_ready",
"adapter_modes": ["sync"],
```

Add `vision_media_analysis` to `_sync_adapter_node_codes`, dispatch it in `_run_sync_adapter`, and use the adapter's stable error code in `_adapter_error_trace`. Keep the canonical scan-ready check in the new module rather than permitting inline or mock attachments.

- [ ] **Step 4: Run adapter, registry, and plan-execution tests.**

Run: `python -m pytest test/test_vision_media_analysis_adapter.py test/test_agent_node_service.py test/test_supervisor_plan_execution.py -q`

Expected: PASS; public capabilities advertise Vision as sync, the execution mode contains no `mock`, a synthetic handoff is `partial`, and each temporary workspace is removed after the run.

- [ ] **Step 5: Commit the actual Vision adapter integration.**

```bash
git add app/services/vision_media_analysis_adapter.py app/services/agent_node_service.py test/test_vision_media_analysis_adapter.py test/test_agent_node_service.py test/test_supervisor_plan_execution.py
git commit -m "feat(#294): connect vision media sync adapter"
```

### Task 5: Keep Agent result persistence observable without retaining sensitive raw output

**Files:**
- Modify: `backend/chatbot/repositories.py:7074-7111,7577-7610,8231-8244`
- Test: `test/test_privacy_boundaries.py`
- Test: `backend/chatbot/test_analysis_job_queue.py`

**Interfaces:**
- Consumes: runtime execution envelopes and the existing `AgentResult` normalized columns.
- Produces: `AgentResult.raw_output` containing only source marker, execution ID/mode, redacted adapter context, structural plan step, and timestamp.
- Preserves: `_node_execution_from_persisted_results` falls back to `_agent_result_handoff_record(result)` when the raw envelope intentionally excludes `agent_output`.

- [ ] **Step 1: Write a failing regression test that persists a private Vision execution and rehydrates it.**

```python
def test_agent_result_raw_output_excludes_media_bytes_paths_and_agent_payload() -> None:
    raw = repositories._agent_result_raw_output(
        {
            "execution_id": "exec_private",
            "execution_mode": "sync",
            "adapter_context": {"execution_id": "exec_private", "input_path": "C:/private/video.mp4"},
            "plan_step": {"node_code": "vision_media_analysis", "context": {"user_text": "홍길동의 원문"}},
        },
        {"summary": "010-1234-5678", "structured_result": {"file_base64": "c2VjcmV0"}},
    )

    assert raw["execution_id"] == "exec_private"
    assert "agent_output" not in raw
    assert "C:/private" not in repr(raw)
    assert "홍길동" not in repr(raw)
    assert "c2VjcmV0" not in repr(raw)
```

- [ ] **Step 2: Run the privacy and queue tests to verify the old raw envelope fails.**

Run: `python -m pytest test/test_privacy_boundaries.py backend/chatbot/test_analysis_job_queue.py -q`

Expected: FAIL because `_agent_result_raw_output` currently embeds the full `agent_output` and unfiltered context.

- [ ] **Step 3: Replace the raw envelope with a structural persistence record.**

```python
def _agent_result_raw_output(execution: dict[str, Any], agent_output: dict[str, Any]) -> dict[str, Any]:
    del agent_output
    return {
        "source": "agent_execution_metadata.v1",
        "execution_id": _text(execution.get("execution_id")),
        "execution_mode": _text(execution.get("execution_mode")),
        "adapter_context": _safe_adapter_context(execution.get("adapter_context")),
        "plan_step": _safe_plan_step(execution.get("plan_step")),
        "created_at": _text(execution.get("created_at")),
    }
```

`_safe_adapter_context` must retain only `contract_version`, `execution_id`, `execution_mode`, `node_code`, and `plan_step_id`. `_safe_plan_step` must retain only `order`, `node_code`, `status`, `execution_mode`, `depends_on`, `required_inputs`, plus the non-content context keys `routing_intent`, `expected_node_codes`, `report_requested`, and `evidence_only`. Do not copy unknown keys. Update `_node_execution_from_persisted_results` to use `_agent_result_handoff_record(result)` whenever raw `agent_output` is absent, which preserves the existing AgentResult columns as the authoritative output.

- [ ] **Step 4: Run the privacy and queue regression suite.**

Run: `python -m pytest test/test_privacy_boundaries.py backend/chatbot/test_analysis_job_queue.py test/test_report_query_service.py -q`

Expected: PASS; query/replay paths still rebuild the execution envelope while persisted raw JSON has no content payload or private runtime detail.

- [ ] **Step 5: Commit the persistence boundary.**

```bash
git add backend/chatbot/repositories.py test/test_privacy_boundaries.py backend/chatbot/test_analysis_job_queue.py
git commit -m "fix(#294): redact persisted agent execution metadata"
```

### Task 6: Add a single DnD/file-picker intake UX

**Files:**
- Modify: `app/web/FrontendAppShell.jsx:25-40,400-500,1940-2075`
- Modify: `app/web/styles.css:2647-2660`
- Test: `test/test_frontend_auth_session_contract.py`
- Test: `test/test_consultation_v2_contract.py`

**Interfaces:**
- Consumes: browser `File`, drop events, capability-derived attachment purposes, existing `api.uploadFile`.
- Produces: one selected file, an accepted/blocked client status, video purpose `blackbox_video`, and the existing `registerAttachmentMetadata` upload call.
- Preserves: Google login handoff, asynchronous scan status polling, file picker operation, and no inline base64 upload.

- [ ] **Step 1: Write source-contract tests for DnD, media accept list, and no legacy video exclusion.**

```python
def test_frontend_attachment_intake_supports_drag_drop_and_video() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")

    assert 'accept="image/jpeg,image/png,image/webp,application/pdf,video/mp4,video/quicktime"' in shell
    assert "onDragOver={handleAttachmentDragOver}" in shell
    assert "onDrop={handleAttachmentDrop}" in shell
    assert "handleAttachmentFile" in shell
    assert 'setAttachmentPurpose("blackbox_video")' in shell
    assert "blackbox_video" in shell
```

- [ ] **Step 2: Run frontend contract tests to verify they fail against the old picker.**

Run: `python -m pytest test/test_frontend_auth_session_contract.py test/test_consultation_v2_contract.py -q`

Expected: FAIL because the picker accepts only `image/*,application/pdf` and `ChatScreenV2` has no drop handlers.

- [ ] **Step 3: Implement one client-side file handler and attach it to both entry points.**

```jsx
const ATTACHMENT_ACCEPT = "image/jpeg,image/png,image/webp,application/pdf,video/mp4,video/quicktime";
const VIDEO_MIME_TYPES = new Set(["video/mp4", "video/quicktime"]);
const DOCUMENT_MIME_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "application/pdf"]);

function handleAttachmentFile(file) {
  if (!file) return;
  if (!VIDEO_MIME_TYPES.has(file.type) && !DOCUMENT_MIME_TYPES.has(file.type)) {
    setStatusMessage("이미지(JPEG/PNG/WebP), PDF, MP4 또는 MOV 파일만 첨부할 수 있습니다.");
    setSelectedUploadFile(null);
    return;
  }
  if (VIDEO_MIME_TYPES.has(file.type)) {
    setAttachmentPurpose("blackbox_video");
  }
  setSelectedUploadFile(file);
  setStatusMessage(`${file.name}을(를) 검사 후 분석 대기열에 연결합니다.`);
}

function handleAttachmentDrop(event) {
  event.preventDefault();
  handleAttachmentFile(event.dataTransfer.files?.[0] || null);
}
```

Pass `handleAttachmentDrop` and `handleAttachmentDragOver={(event) => event.preventDefault()}` into `ChatScreenV2`. Replace the file picker `onChange` with `handleAttachmentFile(event.target.files?.[0] || null)`. Render the existing `.attachment-dropzone` inside the attachment bar with keyboard-accessible picker label, `role="status"` for selected/scan states, and text that says videos are sent to Vision while image/PDF files are sent to OCR classification. Extend `ATTACHMENT_PURPOSE_LABELS` with `blackbox_video`, `accident_scene`, `evidence`, and `traffic_accident_confirmation`.

- [ ] **Step 4: Run frontend contract tests.**

Run: `python -m pytest test/test_frontend_auth_session_contract.py test/test_consultation_v2_contract.py test/test_service_scope_frontend_contract.py -q`

Expected: PASS; both DnD and picker use the same handler, no unsupported MIME is submitted, and existing auth/session contracts remain intact.

- [ ] **Step 5: Commit the DnD UI.**

```bash
git add app/web/FrontendAppShell.jsx app/web/styles.css test/test_frontend_auth_session_contract.py test/test_consultation_v2_contract.py
git commit -m "feat(#294): add chat attachment drag and drop"
```

### Task 7: Gate OCR fields with an editable confirmation UX

**Files:**
- Modify: `app/config/supervisor_routing_policy.v1.json`
- Modify: `app/services/chat_orchestration_service.py:99-255,779-819`
- Modify: `app/services/agent_node_service.py:1241-1305,1664-1694`
- Modify: `app/web/FrontendAppShell.jsx:120-145,800-910,1940-2090`
- Test: `test/test_chat_orchestration_service.py`
- Test: `test/test_agent_node_service.py`
- Test: `test/test_frontend_auth_session_contract.py`

**Interfaces:**
- Consumes: `structured_results.fine_notice_analysis` fields `requires_confirmation`, `unconfirmed_fields`, `fine_type`, `notice_stage`, `law_code`, `violation_text`, `opinion_deadline`, and `issuing_authority`.
- Produces: chat payload `ocr_confirmation={"confirmed": true, "fields": {...}}` and a second fine-notice plan that permits `law_ground_search` and `appeal_decision_flow`.
- Rejects: unconfirmed/invalid field payloads with `ocr_confirmation_required` or `purpose_result_conflict`; no downstream law or appeal node is queued in those cases.

- [ ] **Step 1: Write failing backend and frontend contract tests for the confirmation gate.**

```python
def test_fine_notice_first_pass_stops_before_law_and_appeal() -> None:
    response = submit_message(
        {
            "session_id": "ses_ocr_gate",
            "user_text": "첨부한 고지서를 확인해 주세요.",
            "attachments": [{"attachment_id": "att_notice", "purpose": "fine_notice", "status": "ready"}],
        }
    )

    assert [step["node_code"] for step in response["analysis_plan"]["steps"]] == [
        "input_context_validation",
        "fine_notice_analysis",
        "agent_result_validation",
        "final_response_merge",
    ]


def test_confirmed_ocr_fields_enable_the_existing_follow_up_nodes() -> None:
    response = submit_message(
        {
            "session_id": "ses_ocr_confirmed",
            "user_text": "OCR 내용을 확인했고 후속 절차를 진행해 주세요.",
            "ocr_confirmation": {
                "confirmed": True,
                "fields": {"fine_type": "과태료", "notice_stage": "사전통지"},
            },
            "attachments": [{"attachment_id": "att_notice", "purpose": "fine_notice", "status": "ready"}],
        }
    )

    assert "law_ground_search" in [step["node_code"] for step in response["analysis_plan"]["steps"]]
    assert "appeal_decision_flow" in [step["node_code"] for step in response["analysis_plan"]["steps"]]
```

```python
def test_frontend_renders_editable_ocr_confirmation_before_follow_up() -> None:
    shell = read_text(ROOT / "app" / "web" / "FrontendAppShell.jsx")

    assert "ocr_confirmation" in shell
    assert "requires_confirmation" in shell
    assert "OCR 추출값 확인 후 후속 절차 진행" in shell
```

- [ ] **Step 2: Run the focused tests to verify the current fine-notice plan starts law/appeal too early.**

Run: `python -m pytest test/test_chat_orchestration_service.py test/test_agent_node_service.py test/test_frontend_auth_session_contract.py -q`

Expected: FAIL because the current `fine_notice_analysis` plan contains law/appeal on its first pass and no OCR confirmation UI contract exists.

- [ ] **Step 3: Split first-pass OCR from confirmed follow-up planning.**

Change the policy's `fine_notice_analysis` base plan to:

```json
[
  "input_context_validation",
  "fine_notice_analysis",
  "agent_result_validation",
  "final_response_merge"
]
```

Extend `_analysis_plan` with `ocr_confirmation: dict[str, Any] | None`. When the routing intent is `fine_notice_analysis` and `ocr_confirmation["confirmed"] is True`, insert `law_ground_search` then `appeal_decision_flow` immediately before `agent_result_validation`; otherwise leave the first-pass plan unchanged. Add this normalized confirmation payload to every fine-notice adapter context:

```python
def _normalized_ocr_confirmation(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
    allowed = {"fine_type", "notice_stage", "law_code", "violation_text", "opinion_deadline", "issuing_authority"}
    return {
        "confirmed": raw.get("confirmed") is True,
        "fields": {key: str(fields[key]).strip() for key in allowed if str(fields.get(key) or "").strip()},
    }
```

In `_run_fine_notice_analysis_adapter`, apply those normalized user-confirmed values only after the OCR graph returns a successful/partial fine-notice envelope. Set `requires_confirmation=False`, `unconfirmed_fields=[]`, and add `confirmation_source="user_confirmation"`; do not apply the override to rejected, non-fine, or failed OCR output. If the OCR result is rejected or its user-confirmed `fine_type` conflicts with OCR's recognized fine type, return a `partial` envelope with `error_code="purpose_result_conflict"` and no downstream-ready fields.

- [ ] **Step 4: Render an editable confirmation card and submit the explicit confirmation.**

```jsx
const ocrResult = analysisResponse?.structured_results?.fine_notice_analysis || null;
const [ocrConfirmationFields, setOcrConfirmationFields] = useState({});
const [pendingOcrConfirmation, setPendingOcrConfirmation] = useState(null);

function beginOcrConfirmation() {
  setOcrConfirmationFields({
    fine_type: ocrResult?.fine_type || "",
    notice_stage: ocrResult?.notice_stage || "",
    law_code: ocrResult?.law_code || "",
    violation_text: ocrResult?.violation_text || "",
    opinion_deadline: ocrResult?.opinion_deadline || "",
    issuing_authority: ocrResult?.issuing_authority || "",
  });
}
```

Render fields only when `ocrResult?.requires_confirmation === true`, provide editable labelled inputs, and place a button labelled `OCR 추출값 확인 후 후속 절차 진행` beside them. The button sets a pending confirmation object, sets the neutral follow-up message `OCR 추출값을 확인했습니다. 후속 절차를 진행해 주세요.`, and calls the existing submit flow. Add the following property only to that next `api.submitChatMessage` payload, then clear it after the request completes:

```jsx
ocr_confirmation: pendingOcrConfirmation || undefined,
```

Do not put extracted field values in browser diagnostics or status messages; render them only in the user-visible editable card.

- [ ] **Step 5: Run the confirmation-gate suite.**

Run: `python -m pytest test/test_chat_orchestration_service.py test/test_agent_node_service.py test/test_frontend_auth_session_contract.py test/test_fine_notice_ocr.py -q`

Expected: PASS; initial OCR never queues downstream legal/appeal work, an explicit confirmation does, conflicts stop the flow, and the card sends only the allowed confirmation field names.

- [ ] **Step 6: Commit the OCR confirmation gate.**

```bash
git add app/config/supervisor_routing_policy.v1.json app/services/chat_orchestration_service.py app/services/agent_node_service.py app/web/FrontendAppShell.jsx test/test_chat_orchestration_service.py test/test_agent_node_service.py test/test_frontend_auth_session_contract.py
git commit -m "feat(#294): gate fine notice follow-up on OCR confirmation"
```

### Task 8: Document operational diagnosis and verify the integrated contract

**Files:**
- Create: `docs/ops/vision-media-adapter-runbook.md`
- Modify: `docs/vision/vision-service-handoff-requirements-2026-07-23.md`
- Test: `test/test_runtime_worker_and_registry_contract.py`
- Test: `test/test_api_route_specs.py`

**Interfaces:**
- Consumes: `VISION_TRAINED_CLASSIFIER_CHECKPOINT`, optional `VISION_RUNTIME_TIMEOUT_SECONDS`, safe `AgentInvocation`/`AgentResult` fields.
- Produces: an operator-facing preflight and error-code table without secrets or local paths.

- [ ] **Step 1: Write a failing registry/runtime contract assertion.**

```python
def test_vision_is_a_public_sync_agent_without_mock_mode() -> None:
    nodes = {node["node_code"]: node for node in list_public_agent_nodes()}

    assert nodes["vision_media_analysis"]["adapter_contract"]["execution_modes"] == ["sync"]
    assert "mock" not in repr(nodes["vision_media_analysis"])
```

- [ ] **Step 2: Run the worker and API contract tests to verify the mock declaration fails.**

Run: `python -m pytest test/test_runtime_worker_and_registry_contract.py test/test_api_route_specs.py -q`

Expected: FAIL until the Vision node is public and uses the sync adapter contract from Task 4.

- [ ] **Step 3: Create the short operational runbook with concrete diagnostics.**

The runbook must contain this table and no actual checkpoint path, access key, user filename, raw error, or user content:

| Safe code | Verify | Operator action |
| --- | --- | --- |
| `attachment_not_scan_ready` | `UploadedFile.status=ready`, `scan_status=clean`, canonical scan marker | Wait for scan or re-upload; do not retry Agent execution first. |
| `vision_checkpoint_missing` | checkpoint environment value exists and contains `config.json` plus `model.safetensors` or `pytorch_model.bin` | Deploy a complete approved checkpoint and rerun one smoke test. |
| `vision_dependency_missing` | Worker image contains `requirements-vision-runpod.txt` dependencies | Rebuild the Worker image; do not expose dependency diagnostics to chat users. |
| `vision_media_decode_failed` | Reproduce with a non-sensitive fixture in the isolated worker workspace | Ask for re-upload in MP4/MOV; preserve only stable trace IDs. |
| `vision_execution_timeout` | Compare `latency_ms` and configured timeout | Review runtime capacity and retry through the queue. |
| `vision_execution_failed` | Query `job_id`, `execution_id`, `attachment_id`, node code, result status | Investigate server-only logs; return the generic retry guidance to the user. |

Document the optional smoke command as `python -m ai.vision.run_to_supervisor <fixture.mp4> --checkpoint <approved-checkpoint-dir>` and state it runs only on a secured runtime with a non-production fixture.

- [ ] **Step 4: Run the complete #294 contract suite and static checks.**

Run: `python -m pytest test/test_attachment_mock_service.py test/test_chat_orchestration_service.py test/test_service_scope_policy_service.py test/test_supervisor_control_service.py test/test_fine_notice_ocr.py test/test_vision_run_to_supervisor.py test/test_vision_media_analysis_adapter.py test/test_agent_node_service.py test/test_supervisor_plan_execution.py test/test_privacy_boundaries.py backend/chatbot/test_analysis_job_queue.py test/test_frontend_auth_session_contract.py test/test_consultation_v2_contract.py test/test_runtime_worker_and_registry_contract.py test/test_api_route_specs.py -q`

Expected: PASS with no real model download, no subprocess Vision invocation, and no `mock` execution for `vision_media_analysis`.

Run: `git diff --check`

Expected: no output except an optional line-ending warning.

- [ ] **Step 5: Commit the runbook and verification contract.**

```bash
git add docs/ops/vision-media-adapter-runbook.md docs/vision/vision-service-handoff-requirements-2026-07-23.md test/test_runtime_worker_and_registry_contract.py test/test_api_route_specs.py
git commit -m "docs(#294): add vision adapter operations runbook"
```

## Completion Review

- Issue-intent review: confirms chat DnD/file upload, actual existing Vision handoff, editable OCR confirmation before fine-notice follow-up, OCR/document intake boundary, post-Vision case/law search, stable failure diagnosis, and agent trace visibility are implemented. It explicitly excludes model-quality improvement and new provider/model work.
- Existing-implementation collision review: verifies text-only initial consultation still enters its original fact-confirmation hold, report generation remains limited to `fine_notice_analysis`, canonical scan gate remains mandatory, Vision output is execution-isolated, and AgentResult replay works without raw `agent_output`.
- Pre-merge review: rerun Task 7's suite, inspect the complete diff for scope creep, verify no raw path/content/secret appears in a persisted result or user response, and compare the final plan order against the #294 issue before the user opens a PR.
