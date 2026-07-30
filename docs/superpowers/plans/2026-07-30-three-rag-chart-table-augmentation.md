# Three-RAG Chart and Table Augmentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the card-heavy 10-slide deck with a 12-slide presentation that visibly includes one evidence graph per RAG and a real three-RAG comparison table.

**Architecture:** Extend the existing artifact-tool build module so it adds two clean slides to the 10-slide starter, rebuilds all twelve slides with the established template chrome, embeds existing report PNGs as data URLs, and draws only the standard-RAG summary bars and comparison table as editable PowerPoint objects. Export to a new PPTX, remove the inherited orphan chart part, then validate the final package with Microsoft PowerPoint rendering.

**Tech Stack:** JavaScript ES modules, `@oai/artifact-tool`, JSZip post-processing, Microsoft PowerPoint COM verification, local PNG assets.

## Global Constraints

- Use only the three supplied RAG reports and their existing `charts/assets`.
- Do not include OCR/Vision content.
- Produce exactly 12 slides in 16:9.
- Keep every external claim and asset traceable through `[Sources]` speaker-note blocks.
- Do not label Recall@50, Rule Hit@1, and Final Ratio Exact as reverse search.
- Preserve the current beige template, typography, section labels, footer, and dataset colors.
- Graph labels and denominators must remain readable in a 1280×720 PowerPoint render.

---

### Task 1: Register chart assets and twelve-slide output

**Files:**
- Modify: `tmp/three_rag_ppt_build/build-three-rag-deck.mjs`
- Modify: `tmp/three_rag_ppt_build/sanitize-pptx.mjs`

**Interfaces:**
- Consumes: the existing 10-slide template starter and local PNG chart files.
- Produces: a twelve-slide in-memory `deck` and a new output path ending in `_그래프표보강_12장.pptx`.

- [ ] **Step 1: Add the new report assets**

Register these exact files in `ASSET` and convert them through the existing
`asDataUrl()` helper:

```js
reviewRankChange: path.join(
  ROOT,
  "etl/fault_cases/review_case_test/08_PRESENTATION_REPORT/charts/09_reranker_rank_change.png",
),
precedentFunnel: path.join(
  ROOT,
  "etl/fault_cases/precedents_test/00_docs/assets/39_precedent_ppt_report/04_collection_classification_funnel.png",
),
```

- [ ] **Step 2: Extend the imported deck to twelve slides**

After import, add two slides before reading `deck.slides.items`:

```js
while (deck.slides.items.length < 12) {
  deck.slides.add();
}
const slides = deck.slides.items;
if (slides.length !== 12) {
  throw new Error(`Expected 12 slides, got ${slides.length}`);
}
```

- [ ] **Step 3: Set the new output filename**

Use:

```text
etl/fault_cases/ppt/판례_심의사례_인정기준_RAG_그래프표보강_12장.pptx
```

- [ ] **Step 4: Run the module once and verify the pre-sanitize export**

Run:

```powershell
$env:FINAL_PPTX='C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\ppt\판례_심의사례_인정기준_RAG_그래프표보강_12장.pptx'
node build-three-rag-deck.mjs
```

Expected: `slides=12` and the output file exists.

---

### Task 2: Recompose the twelve-slide narrative

**Files:**
- Modify: `tmp/three_rag_ppt_build/build-three-rag-deck.mjs`

**Interfaces:**
- Consumes: `slides[0]` through `slides[11]`, registered chart data URLs, and existing drawing helpers.
- Produces: twelve audience-facing slides matching the approved design.

- [ ] **Step 1: Preserve slides 1–5**

Keep the current roles, common pipeline, standard data build, corrected
standard search metrics, and review data build content. Update their page
numbers only if necessary.

- [ ] **Step 2: Make slide 6 a search-structure slide**

Use the existing Qwen→collapse→BGE→Top-5 flow, but remove the performance
bars so the slide explains only retrieval responsibility.

- [ ] **Step 3: Add slide 7 for review-case evidence graphs**

Place `08_reranker_metric_comparison.png` as the dominant graph and
`09_reranker_rank_change.png` as a smaller supporting graph. Add only these
two conclusions:

```text
Hit@1 20/32 → 24/32
기존 정답 강등 0건
```

- [ ] **Step 4: Add slide 8 for precedent collection evidence**

Place `04_collection_classification_funnel.png` at readable size and reinforce
the exact counts:

```text
17,512 수집 문서 → 825 최종 판례 → 3,339 의미 블록
```

- [ ] **Step 5: Add slide 9 for precedent search structure**

Show:

```text
의미 블록 후보 → 판례별 통합 → Top-200 → BGE 의미형 리랭크 → Top-5
```

Keep the service limitation that candidates outside Top-200 cannot be
recovered.

- [ ] **Step 6: Add slide 10 for precedent performance**

Use `06_final_five_way_metrics.png` as the main graph and call out:

```text
Hit@1 46.7% → 66.7%
nDCG@10 0.6114 → 0.7526
```

- [ ] **Step 7: Rebuild slide 11 as a true comparison table**

Create a header row and five body rows with these row labels:

```text
질문
검색 단위
후처리
출력
대표 지표
```

The data columns are `인정기준`, `심의사례`, and `판례`. Use thin grid lines,
alternating row fills, and dataset-colored column headers.

- [ ] **Step 8: Move the Agent integration to slide 12**

Reuse the current Agent diagram and update the page number to 12.

- [ ] **Step 9: Ensure every slide has source notes**

Run an inspect query and require twelve `[Sources]` blocks.

---

### Task 3: Export and sanitize the PowerPoint package

**Files:**
- Modify: `tmp/three_rag_ppt_build/sanitize-pptx.mjs`
- Output: `etl/fault_cases/ppt/판례_심의사례_인정기준_RAG_그래프표보강_12장.pptx`

**Interfaces:**
- Consumes: the artifact-tool PPTX export.
- Produces: a PowerPoint-readable package without the inherited unsupported chart part.

- [ ] **Step 1: Run the sanitizer against the new output**

Run:

```powershell
node sanitize-pptx.mjs 'C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\ppt\판례_심의사례_인정기준_RAG_그래프표보강_12장.pptx'
```

Expected: exit code `0`.

- [ ] **Step 2: Verify the ZIP package**

Open the PPTX with `System.IO.Compression.ZipFile` and assert:

```text
slide XML entries = 12
orphan chart entries = 0
```

---

### Task 4: PowerPoint visual verification

**Files:**
- Create: `tmp/three_rag_ppt_build/chart-table-powerpoint-render/slide-01.png` through `slide-12.png`
- Create: `tmp/three_rag_ppt_build/chart-table-powerpoint-render/qa-montage.png`

**Interfaces:**
- Consumes: the sanitized twelve-slide PPTX.
- Produces: fresh Microsoft PowerPoint renders and a visual QA result.

- [ ] **Step 1: Open the PPTX with Microsoft PowerPoint**

Open read-only and assert:

```text
Slides.Count = 12
SlideWidth × SlideHeight = 960 × 540 points
```

- [ ] **Step 2: Export every slide**

Export each slide to `1280×720` PNG and assert `png_count=12`.

- [ ] **Step 3: Inspect all slides**

Check each slide at full size for:

```text
graph labels and denominators readable
no clipped table text
no unresolved placeholders
no backward arrows
section labels remain one line
```

- [ ] **Step 4: Build and inspect the montage**

Run the existing `make-montage.mjs` against
`chart-table-powerpoint-render` and confirm the narrative alternates between
process, graph, and table slides without dense repetition.

- [ ] **Step 5: Record final verification**

Report only evidence from the fresh run:

```text
zip_slides=12
zip_charts=0
powerpoint_slides=12
png_count=12
```

