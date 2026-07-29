# VideoMAE-Locked Qwen Explanation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make VideoMAE the only accident-category authority, use Qwen only for evidence-grounded explanation, and rerun 300 samples per category on RunPod.

**Architecture:** VideoMAE produces an immutable classification context. YOLO frames become an evidence packet, Qwen returns the compact `vision-qwen-explanation-v1` schema, and Supervisor receives the VideoMAE prediction separately from the optional explanation. Invalid Qwen output gets one compact retry and then a deterministic fallback without changing the canonical label.

**Tech Stack:** Python, Pydantic-compatible explicit validation, pytest, Qwen2.5-VL, VideoMAE, YOLO, Jupyter/RunPod.

## Global Constraints

- Work only in `D:\dev\SKN27-FINAL-3Team\.worktrees\feat-accident-image-video-agent-result-flow` and `/workspace/SKN27-FINAL-3Team`.
- Do not copy RunPod files to `C:\Users\pc\Documents\최종 프로젝트`.
- Preserve existing raw results; write the new evaluation to a versioned output directory.
- Use 32 frames for VideoMAE and 8-12 event-centered frames for Qwen.
- Run all four categories with 300 prepared assets each.

---

### Task 1: Lock the Qwen contract to explanation-only

**Files:**
- Modify: `ai/vision/vlm_json.py`
- Modify: `ai/vision/vlm_input.py`
- Test: `test/test_vlm_json.py`
- Test: `test/test_vlm_input_contract.py`

**Interfaces:**
- Consumes: canonical VideoMAE classification and selected YOLO frame metadata.
- Produces: validated `vision-qwen-explanation-v1` with narrative, evidence sentences, conflict, conflict reason, and uncertainties.

- [ ] Add failing tests for the new schema, limits, frame-reference validation, and read-only classification context.
- [ ] Run the focused tests and confirm they fail for the missing contract.
- [ ] Implement the minimal prompt, validator, and input envelope.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Preserve the canonical label through service and handoff

**Files:**
- Modify: `ai/vision/run_to_supervisor.py`
- Modify: `ai/vision/build_supervisor_handoff.py`
- Modify: `ai/vision/merge_analysis.py`
- Test: `test/test_vision_run_to_supervisor.py`

**Interfaces:**
- Consumes: immutable VideoMAE prediction and Qwen explanation.
- Produces: Supervisor `trained_accident_prediction` as the sole category field plus `qwen_explanation`.

- [ ] Add failing tests for label preservation on conflict, malformed JSON, timeout, and deterministic fallback.
- [ ] Run the focused tests and confirm they fail for the current Qwen classification path.
- [ ] Pass VideoMAE context to Qwen, remove Qwen category override, and generate fallback on final failure.
- [ ] Update handoff compaction and run the focused tests.

### Task 3: Update the 300-per-category RunPod runner

**Files:**
- Modify: `scripts/vision/run_vlm32_independent.py`
- Test: `test/test_vlm_runner_build.py`

**Interfaces:**
- Consumes: cached 32-frame/YOLO assets for 300 samples per category.
- Produces: versioned explanation results with 8-12 event-centered frames, retry/fallback fields, latency, and validation status.

- [ ] Add failing notebook-build tests for 12-frame maximum, classification context, explanation schema, and versioned outputs.
- [ ] Run the focused tests and confirm they fail.
- [ ] Apply the minimum notebook transformations and preserve prior CSV files.
- [ ] Run runner build checks for all categories.

### Task 4: Sync and execute on RunPod

**Files:**
- Sync only the modified Vision files to `/workspace/SKN27-FINAL-3Team`.
- Create: versioned RunPod logs/results under `storage/vision/outputs`.

**Interfaces:**
- Consumes: locally verified files.
- Produces: four completed 300-row evaluations and an aggregate report.

- [ ] Compare local and RunPod hashes before upload.
- [ ] Upload only modified Vision files and verify hashes after upload.
- [ ] Run focused tests on RunPod.
- [ ] Start the four-category 300-row evaluation without deleting earlier outputs.
- [ ] Monitor process, unique rows, schema pass, retry/fallback, latency, and GPU memory.
- [ ] Aggregate classification preservation and explanation reliability metrics.
