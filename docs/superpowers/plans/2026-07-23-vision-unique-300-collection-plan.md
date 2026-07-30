# Vision Unique 300 Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 100건을 포함해 카테고리별 고유·가독 영상 300건을 확보하고 동일한 32프레임 전처리를 완료한다.

**Architecture:** 기존 Drive candidate manifest와 다운로더를 재사용한다. 하나의 작은 수집 검증 도구가 기존·후보 영상의 식별자, SHA-256, 영상 메타데이터와 프레임 지문을 계산하고 카테고리별 300건을 선택하며, 기존 `extract_videomae_frames.py`가 선택 manifest를 32프레임으로 전처리한다.

**Tech Stack:** Python 표준 라이브러리, 기존 OpenCV·NumPy, 기존 CSV 유틸리티

## Global Constraints

- 현재 Qwen/LLaVA GPU 분석, 모델 캐시, 기존 400건 결과를 변경하지 않는다.
- 신규 의존성을 설치하지 않는다.
- 원본은 `storage/vision/staging/per_label_300/raw`에만 저장한다.
- 카테고리별 중복·손상·전처리 실패를 대체해 최종 성공 수를 정확히 300건으로 유지한다.
- VLM 추론과 VideoMAE 학습은 실행하지 않는다.

---

### Task 1: 고유 영상 판정기

**Files:**
- Create: `etl/vision/collect_unique_media.py`
- Create: `test/test_collect_unique_media.py`

**Interfaces:**
- Consumes: candidate manifest rows containing `asset_id`, `drive_url`, `local_path`, `coarse_label`
- Produces: `fingerprint_video(path: Path) -> dict`, `select_unique(rows: list[dict], target_per_label: int) -> tuple[list[dict], list[dict]]`

- [ ] **Step 1: 중복·손상 판정 테스트 작성**

테스트에서 OpenCV로 서로 다른 짧은 영상 두 개와 동일 파일 복사본을 만들고 다음을 검증한다.

```python
selected, rejected = select_unique(rows, target_per_label=2)
assert [row["asset_id"] for row in selected] == ["a", "c"]
assert rejected[0]["rejection_reason"] == "exact_duplicate"
assert all(row["media_readable"] == "True" for row in selected)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m unittest test.test_collect_unique_media -v`

Expected: `ModuleNotFoundError: etl.vision.collect_unique_media`

- [ ] **Step 3: 최소 구현**

`hashlib.sha256`로 완전 중복을 판정하고 OpenCV로 프레임 수·FPS·크기·길이와 5개 균등 시점 16×16 grayscale average hash를 계산한다. 식별자, SHA-256, 동일 `incident_id`, 메타데이터와 프레임 지문이 허용 거리 이내인 순서로 중복을 제외한다. 읽기 실패는 `unreadable`로 제외한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m unittest test.test_collect_unique_media -v`

Expected: all tests `OK`

- [ ] **Step 5: 커밋**

```bash
git add etl/vision/collect_unique_media.py test/test_collect_unique_media.py
git commit -m "feat: select unique readable vision media"
```

### Task 2: 카테고리별 300건 수집 루프

**Files:**
- Modify: `etl/vision/collect_unique_media.py`
- Modify: `test/test_collect_unique_media.py`

**Interfaces:**
- Consumes: full candidate manifest, existing fixed100 manifest, staging directory
- Produces: `unique_300_manifest.csv`, `rejected_candidates.csv`, exit code 0 only when every category has 300 rows

- [ ] **Step 1: 부족분 보충 테스트 작성**

다운로드 함수를 임시 파일 생성 함수로 대체하고 중복 후보 뒤의 다음 후보가 선택되어 목표 개수를 채우는지 검증한다.

```python
result = collect_until_target(candidates, existing, target_per_label=3, download=fake_download)
assert result.counts == {"car_vs_car": 3}
assert result.complete is True
```

- [ ] **Step 2: 실패 확인**

Run: `python -m unittest test.test_collect_unique_media.CollectionLoopTest -v`

Expected: `NameError` 또는 import failure

- [ ] **Step 3: 최소 수집 루프 및 CLI 구현**

후보를 manifest 순서대로 한 건씩 내려받아 즉시 검사하고, 고유·가독 영상만 카운트한다. 카테고리별 300건이 되면 해당 카테고리 다운로드를 중단한다. 후보 소진 시 비정상 종료하고 부족 수를 출력한다.

- [ ] **Step 4: 테스트 통과 및 dry-run**

Run: `python -m unittest test.test_collect_unique_media -v`

Expected: all tests `OK`

Run: `python etl/vision/collect_unique_media.py --help`

Expected: `--candidates`, `--existing`, `--target-per-label`, `--staging-dir`, `--output` 표시

- [ ] **Step 5: 커밋**

```bash
git add etl/vision/collect_unique_media.py test/test_collect_unique_media.py
git commit -m "feat: fill unique vision categories to target"
```

### Task 3: RunPod 수집과 32프레임 전처리

**Files:**
- Runtime output: `storage/vision/staging/per_label_300/unique_300_manifest.csv`
- Runtime output: `storage/vision/staging/per_label_300/rejected_candidates.csv`
- Runtime output: `storage/vision/staging/per_label_300/frames32/`
- Runtime output: `storage/vision/staging/per_label_300/preprocess_summary.csv`

**Interfaces:**
- Consumes: Task 2 manifest
- Produces: 카테고리별 300개 원본과 영상별 32개 전처리 프레임

- [ ] **Step 1: RunPod 자원·기존 분석 상태 확인**

Run: `nvidia-smi; df -h /workspace; ps -eo pid,etime,%cpu,%mem,cmd | grep -E 'jupyter.*nbconvert|python.*vlm' | grep -v grep`

Expected: 기존 GPU 분석 PID 유지, staging 저장 여유 확인

- [ ] **Step 2: 별도 staging에서 수집 실행**

Run:

```bash
nohup python etl/vision/collect_unique_media.py \
  --candidates storage/vision/datasets/classification/manifests/classification_manifest.csv \
  --existing storage/vision/manifests/videomae_labeled_fixed100_metadata.csv \
  --target-per-label 300 \
  --staging-dir storage/vision/staging/per_label_300/raw \
  --output storage/vision/staging/per_label_300/unique_300_manifest.csv \
  > /workspace/collect_unique_300.log 2>&1 &
```

Expected: GPU 분석 PID와 별개인 background PID 출력

- [ ] **Step 3: 정확히 300건 검증**

Run: `python etl/vision/collect_unique_media.py --verify storage/vision/staging/per_label_300/unique_300_manifest.csv`

Expected: 각 카테고리 `unique=300 unreadable=0 duplicates=0`

- [ ] **Step 4: 기존 32프레임 전처리 재사용**

Run:

```bash
python etl/vision/extract_videomae_frames.py \
  --input storage/vision/staging/per_label_300/unique_300_manifest.csv \
  --output-dir storage/vision/staging/per_label_300/frames32 \
  --output storage/vision/staging/per_label_300/preprocess_summary.csv \
  --frame-count 32
```

Expected: 1,200건 모두 `sampled_frames=32`

- [ ] **Step 5: 실패분 대체 후 최종 감사**

전처리 실패 asset을 rejected manifest로 이동하고 Task 2를 재개한 뒤 해당 신규 영상만 전처리한다.

Run: `python etl/vision/collect_unique_media.py --verify storage/vision/staging/per_label_300/unique_300_manifest.csv --frames-dir storage/vision/staging/per_label_300/frames32`

Expected: 전체 `videos=1200`, `frames=38400`, `duplicates=0`, `failures=0`

### Task 4: 로컬 동기화와 결과 보고

**Files:**
- Create: `docs/vision/vision_unique_300_collection_report_2026-07-23.md`

- [ ] **Step 1: manifest·요약·보고서만 로컬로 동기화**

원본 1,200개와 38,400개 프레임은 용량 확인 전 자동 복사하지 않는다. `unique_300_manifest.csv`, `rejected_candidates.csv`, `preprocess_summary.csv`와 보고서만 로컬 저장소에 복사한다.

- [ ] **Step 2: 로컬 독립 감사**

Run: `python etl/vision/collect_unique_media.py --verify storage/vision/staging/per_label_300/unique_300_manifest.csv`

Expected: 카테고리별 300건과 중복 0건

- [ ] **Step 3: 최종 커밋**

```bash
git add docs/vision/vision_unique_300_collection_report_2026-07-23.md storage/vision/staging/per_label_300/*.csv
git commit -m "docs: report unique 300-video preprocessing"
```
