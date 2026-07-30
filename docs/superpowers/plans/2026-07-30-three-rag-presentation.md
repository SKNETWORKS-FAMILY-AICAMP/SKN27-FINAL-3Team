# Three-RAG Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a new 10-slide Korean PowerPoint deck explaining the collection, structuring, retrieval, and integration strategies for fault-standard, review-case, and precedent RAG.

**Architecture:** Normalize the existing 61-slide reference deck through PowerPoint so artifact-tool can inspect and duplicate its native slides. Reuse its master, layouts, typography, navy/orange/off-white palette, and slide furniture; then replace inherited content with the approved 10-slide narrative. Use the three verified presentation reports and their chart assets as the only quantitative sources.

**Tech Stack:** Microsoft PowerPoint COM for source normalization, `@oai/artifact-tool` JavaScript ES modules for slide editing and PPTX export, bundled presentation inspection/rendering tools for QA.

## Global Constraints

- The output contains exactly 10 slides in 16:9.
- The main deck excludes OCR and Vision details.
- Each slide targets roughly 30% text and 70% visual information design.
- Titles are natural Korean takeaway statements, not section labels or AI-style sentence fragments.
- The three RAGs use fixed visual identities consistently across the deck.
- Use the latest verified figures: precedent `825 cases / 3,339 semantic blocks`; review case `226 cases / 904 structured chunks`; fault standard `277 unique rules`.
- Do not describe `Recall@50 100%` as final legal or ratio accuracy.
- Do not describe RAG output as an automatic legal judgment.
- Preserve the source deck; save a new PPTX.
- Implement and export the deck with `@oai/artifact-tool`; do not use `python-pptx`.
- Add `[Sources]` blocks to speaker notes for every slide with quantitative claims or reused external assets.

---

### Task 1: Normalize and inventory the reference deck

**Files:**
- Read: `etl/fault_cases/ppt/ref/차분해_최종발표자료_v64_RAG역할분리슬라이드추가.pptx`
- Create temporary: `tmp/three_rag_ppt_build/reference-normalized.pptx`
- Create temporary: `tmp/three_rag_ppt_build/template-inspect/`
- Create temporary: `tmp/three_rag_ppt_build/template-audit.txt`

**Interfaces:**
- Consumes: the original 61-slide PPTX.
- Produces: a PowerPoint-normalized copy and a complete artifact-tool slide inventory.

- [ ] **Step 1: Save a normalized copy through PowerPoint**

Open the source deck read-only with PowerPoint COM from an ASCII temporary path and save it as `reference-normalized.pptx`. This rewrites the malformed chart axis that currently prevents artifact-tool import while preserving the original file.

- [ ] **Step 2: Initialize the artifact-tool workspace**

Run:

```powershell
node "C:\Users\Playdata\.codex\plugins\cache\openai-primary-runtime\presentations\26.727.11326\skills\presentations\container_tools\setup_artifact_tool_workspace.mjs" `
  --workspace "C:\dev\project\SKN27-FINAL-3Team\tmp\three_rag_ppt_build"
```

Expected: exit code 0 and local workspace links to the bundled artifact-tool package.

- [ ] **Step 3: Inspect every source slide**

Run:

```powershell
node "C:\Users\Playdata\.codex\plugins\cache\openai-primary-runtime\presentations\26.727.11326\skills\presentations\template_following_scripts\inspect_template_deck.mjs" `
  --workspace "C:\dev\project\SKN27-FINAL-3Team\tmp\three_rag_ppt_build" `
  --pptx "C:\dev\project\SKN27-FINAL-3Team\tmp\three_rag_ppt_build\reference-normalized.pptx"
```

Expected: 61 rendered source slides, layout JSON, `template-inspect.ndjson`, extracted media, and `template-manifest.json`.

- [ ] **Step 4: Write the template audit**

Record the reusable source-slide patterns, title positions, typography, footer/page-number behavior, palette, chart treatment, and inherited placeholders in `template-audit.txt`.

- [ ] **Step 5: Verify the inventory**

Confirm that all 61 source slides render and that source slides 27, 37, 40, 42, 46, 50, 51, and 53 have editable inherited elements suitable for the new narrative.

---

### Task 2: Build the exact 10-slide content and frame map

**Files:**
- Read: `docs/superpowers/specs/2026-07-30-three-rag-presentation-structure-design.md`
- Read: `etl/fault_cases/precedents_test/00_docs/39_판례_RAG_PPT_발표용_근거중심_최종보고서.md`
- Read: `etl/fault_cases/review_case_test/08_PRESENTATION_REPORT/00_심의사례_RAG_발표용_종합보고서.md`
- Read: `etl/fault_cases/standard_TEST/08_PRESENTATION/01_Fault_Standard_RAG_Presentation_Report.md`
- Create temporary: `tmp/three_rag_ppt_build/content.txt`
- Create temporary: `tmp/three_rag_ppt_build/source-notes.txt`
- Create temporary: `tmp/three_rag_ppt_build/template-frame-map.json`
- Create temporary: `tmp/three_rag_ppt_build/deviation-log.txt`

**Interfaces:**
- Consumes: inspected source element IDs and the approved narrative.
- Produces: final audience-facing copy, source provenance, and a validated source-slide mapping.

- [ ] **Step 1: Write slide 1–2 copy**

Use these titles and messages:

1. `하나의 사고를 세 종류의 근거로 검토합니다`
   - 인정기준: 공식 Rule과 기준 비율
   - 심의사례: 유사 분쟁의 판단과 과실비율
   - 판례: 법원의 책임 판단 논리
2. `공통 파이프라인은 같지만 데이터 전략은 달랐습니다`
   - 수집 → 검증 → 구조화 → 검색 단위 → Qwen 임베딩 → 후보 검색 → 데이터별 후처리 → Agent

- [ ] **Step 2: Write fault-standard slide copy**

3. `모델보다 먼저, 오염된 인정기준 구조를 다시 만들었습니다`
   - 공식 PDF 4종, 1,109 rows, 277 unique rules
   - PDF → Core → Search → Embedding → DB → Calculator
4. `인정기준은 Rule을 찾은 뒤 조건과 비율을 다시 검증합니다`
   - vector Top-50 → PostgreSQL → Neo4j → Calculator
   - Recall@50 `30/30`, Hit@1 `22/30`, Final Ratio Exact `18/30`

- [ ] **Step 3: Write review-case slide copy**

5. `심의사례는 판단 과정을 네 개 의미 단위로 보존했습니다`
   - 472-page PDF, 226 cases, 904 structured chunks
   - overview / arguments / evidence issue / decision
6. `심의사례는 더 찾는 것보다 정답을 먼저 보여주는 문제였습니다`
   - Qwen retrieval → case collapse → BGE rerank → Top-5
   - Hit@1 `20/32 → 24/32`, zero prior-answer demotions

- [ ] **Step 4: Write precedent slide copy**

7. `판례 검색의 병목은 모델이 아니라 검색할 판례의 품질이었습니다`
   - OLD `987 cases / 8,334 chunks`
   - collection and quality gates
   - NEW `825 cases / 3,339 semantic blocks`
8. `판례는 넓게 찾고 의미형 리랭커로 Top-5를 고릅니다`
   - Qwen Top-200 → case collapse → BGE rerank → Top-5
   - Hit@1 `46.7% → 66.7%`, nDCG@10 `0.6114 → 0.7526`

- [ ] **Step 5: Write integration slide copy**

9. `같은 모델을 사용해도 세 RAG의 검색 책임은 다릅니다`
   - Compare question, search unit, first-stage retrieval, post-processing, and output for all three RAGs.

- [ ] **Step 6: Write fault-ratio Agent slide copy**

10. `과실비율 Agent는 세 근거를 조립해 설명 가능한 범위를 만듭니다`
    - user facts → standard anchor → review-case comparison → precedent reasoning
    - output: expected range, sources, similarities, differences, uncertainty, and additional evidence
    - explicit note: not a final legal judgment and not a simple average

- [ ] **Step 7: Map each output slide to a source slide**

Use the inspected slide patterns as the starting map:

| Output | Preferred source slide | Narrative role |
|---:|---:|---|
| 1 | 42 | three evidence roles |
| 2 | 27 | shared pipeline |
| 3 | 46 | fault-standard collection and structure |
| 4 | 37 | fault-standard search flow |
| 5 | 46 | four-part review-case structure |
| 6 | 50 | review-case retrieval and reranking |
| 7 | 53 | precedent collection funnel |
| 8 | 51 | precedent performance and reranking |
| 9 | 42 | three-RAG responsibility comparison |
| 10 | 40 | Agent integration flow |

For every mapped slide, classify inherited elements as `keep`, `rewrite`, `replace`, or `delete` using exact source element IDs from `template-inspect.ndjson`.

- [ ] **Step 8: Validate the frame map**

Run:

```powershell
node "C:\Users\Playdata\.codex\plugins\cache\openai-primary-runtime\presentations\26.727.11326\skills\presentations\template_following_scripts\validate_template_plan.mjs" `
  --workspace "C:\dev\project\SKN27-FINAL-3Team\tmp\three_rag_ppt_build" `
  --pptx "C:\dev\project\SKN27-FINAL-3Team\tmp\three_rag_ppt_build\reference-normalized.pptx" `
  --map "C:\dev\project\SKN27-FINAL-3Team\tmp\three_rag_ppt_build\template-frame-map.json"
```

Expected: the 10 output slides each resolve to editable inherited elements with no unhandled placeholders.

---

### Task 3: Build and export the new deck

**Files:**
- Create temporary: `tmp/three_rag_ppt_build/template-starter.pptx`
- Create temporary: `tmp/three_rag_ppt_build/build-three-rag-deck.mjs`
- Create: `etl/fault_cases/ppt/판례_심의사례_인정기준_RAG_발표자료_10장.pptx`

**Interfaces:**
- Consumes: the normalized source deck, frame map, final copy, report chart assets, and source notes.
- Produces: the editable 10-slide PPTX.

- [ ] **Step 1: Prepare the 10-slide starter deck**

Run:

```powershell
node "C:\Users\Playdata\.codex\plugins\cache\openai-primary-runtime\presentations\26.727.11326\skills\presentations\template_following_scripts\prepare_template_starter_deck.mjs" `
  --workspace "C:\dev\project\SKN27-FINAL-3Team\tmp\three_rag_ppt_build" `
  --pptx "C:\dev\project\SKN27-FINAL-3Team\tmp\three_rag_ppt_build\reference-normalized.pptx" `
  --map "C:\dev\project\SKN27-FINAL-3Team\tmp\three_rag_ppt_build\template-frame-map.json" `
  --out "C:\dev\project\SKN27-FINAL-3Team\tmp\three_rag_ppt_build\template-starter.pptx"
```

Expected: exactly 10 duplicated source slides with inherited masters and layouts.

- [ ] **Step 2: Implement inherited element edits**

Create `build-three-rag-deck.mjs` as an ES module. Import the starter PPTX with `PresentationFile.importPptx`, rewrite only mapped inherited text and visual slots, insert native charts or supplied PNG/SVG assets into approved inherited media frames, add `[Sources]` note blocks, and export with `PresentationFile.exportPptx`.

- [ ] **Step 3: Use the approved visual system**

Apply fixed data colors:

- Fault standard: orange
- Review case: teal
- Precedent: blue
- Integration/Agent: navy with the three data colors converging

Reuse the source deck’s typography, title alignment, footer, page numbers, and navy/orange/off-white palette. Keep body copy at 16pt or larger and titles at the source title size.

- [ ] **Step 4: Export the final deck**

Run the ES module with the bundled Node.js runtime and save:

```text
C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\ppt\판례_심의사례_인정기준_RAG_발표자료_10장.pptx
```

Expected: artifact-tool export succeeds and the PPTX contains exactly 10 slides.

---

### Task 4: Render, inspect, and correct all slides

**Files:**
- Create temporary: `tmp/three_rag_ppt_build/final-render/`
- Create temporary: `tmp/three_rag_ppt_build/final-montage.png`
- Create temporary: `tmp/three_rag_ppt_build/qa-ledger.txt`
- Verify: `etl/fault_cases/ppt/판례_심의사례_인정기준_RAG_발표자료_10장.pptx`

**Interfaces:**
- Consumes: the exported 10-slide PPTX.
- Produces: visual QA evidence and the corrected final deck.

- [ ] **Step 1: Render every slide**

Render all 10 slides at 16:9 and create a montage. If artifact-tool rendering fails, stop and repair the generated PPTX rather than switching to a separate visual rebuild.

- [ ] **Step 2: Inspect each slide at full size**

Check title wrapping, text overflow, chart labels, arrow direction, source footers, visual hierarchy, and that each slide communicates one claim.

- [ ] **Step 3: Run structural QA**

Run `slides_test.py` and the template fidelity checker. Inspect exported PPTX XML for empty inherited placeholders, including slide number, date, and footer placeholders.

- [ ] **Step 4: Verify content accuracy**

Check the final deck against this exact list:

- 10 slides
- no OCR or Vision detail
- `277 unique rules`
- `226 cases / 904 chunks`
- `825 cases / 3,339 semantic blocks`
- fault-standard `30/30`, `22/30`, `18/30`
- review-case `20/32 → 24/32`
- precedent `46.7% → 66.7%`, `0.6114 → 0.7526`
- no claim of automatic legal judgment

- [ ] **Step 5: Correct and rerun full QA**

Fix every unintended overlap, clipping, placeholder, or source mismatch. Rerender all 10 slides and repeat structural checks after the last correction.

- [ ] **Step 6: Commit the final presentation**

Stage only the final PPTX and any explicitly requested durable source file, then commit with:

```text
docs: add three-rag final presentation
```
