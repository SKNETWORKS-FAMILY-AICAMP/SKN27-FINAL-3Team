# OCR·RAG 발표 슬라이드 v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실제 교통사고사실확인원에서 OCR 구조화 결과와 RAG 활용으로 이어지는 과정을 설명하는 편집 가능한 한 장짜리 PPTX를 만든다.

**Architecture:** `@oai/artifact-tool`로 1280×720 프레젠테이션을 새로 생성한다. 실제 문서는 이미지로 삽입하고, 주석·표·연결선·RAG 패널·하단 결론은 PowerPoint 네이티브 객체로 작성한다.

**Tech Stack:** JavaScript ES modules, `@oai/artifact-tool`, Microsoft PowerPoint COM 기반 최종 렌더 검수

## Global Constraints

- 기존 v1 파일은 보존하고 v2 파일을 새로 생성한다.
- 모든 텍스트, 표, 연결선, 도형은 편집 가능해야 한다.
- 실제 문서 이미지는 개인정보가 마스킹된 사용자 제공 PNG를 사용한다.
- 제목 35pt 이상, 소제목 24pt 이상, 본문 16pt 이상을 유지한다.

---

### Task 1: 슬라이드 구성

**Files:**
- Create: `tmp/ocr_rag_editable_ppt_v2_20260730/build-slide-v2.mjs`
- Create: `etl/fault_cases/ppt/ocr_fact_card_rag_editable_v2.pptx`

**Interfaces:**
- Consumes: 사용자 제공 사실확인원 PNG
- Produces: 한 장짜리 편집 가능 PPTX

- [ ] **Step 1:** 1280×720 프레젠테이션과 아이보리 배경을 만든다.
- [ ] **Step 2:** 상단 제목·부제, 왼쪽 원본, 중앙 OCR 표, 오른쪽 RAG 영역, 하단 결론을 배치한다.
- [ ] **Step 3:** 사고 필드 주석과 OCR 행을 오렌지 연결선으로 연결한다.
- [ ] **Step 4:** 발표자 노트에 발표 멘트와 `[Sources]` 블록을 추가한다.

### Task 2: 렌더 및 구조 검수

**Files:**
- Create: `etl/fault_cases/ppt/ocr_fact_card_rag_editable_v2.png`
- Create: `tmp/ocr_rag_editable_ppt_v2_20260730/qa/slide-01.layout.json`

**Interfaces:**
- Consumes: Task 1의 PPTX
- Produces: 미리보기와 검수 결과

- [ ] **Step 1:** Artifact Tool로 전체 슬라이드를 PNG와 layout JSON으로 내보낸다.
- [ ] **Step 2:** PNG를 전체 크기로 확인하고 글자 잘림과 연결선 겹침을 수정한다.
- [ ] **Step 3:** Microsoft PowerPoint에서 PPTX를 다시 열어 PNG로 내보낸다.
- [ ] **Step 4:** 슬라이드 수, 텍스트 객체, 이미지 객체, 발표자 노트 존재 여부를 확인한다.
