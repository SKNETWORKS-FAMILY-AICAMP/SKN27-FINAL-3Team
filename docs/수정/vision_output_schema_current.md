# Vision Output Schema 현재 구현 기준

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-29 |
| 목적 | YOLO/bbox 기반 Vision Agent Output과 VideoMAE 보조 추론이 추가된 이후의 현재 Output Schema를 정리한다. |
| 기준 코드 | `ai/vision/schemas.py`, `ai/vision/videomae_infer.py`, `ai/vision/merge_analysis.py` |
| 최종 산출물 | `storage/vision/outputs/final_analysis/final_analysis_*.json` |

## 1. 결론

모델 흐름이 변경되면서 Output은 1개가 아니라 3단계로 나뉜다.

```text
1. agent_output_*.json
   YOLO/bbox 기반 Vision Agent Output

2. videomae_results_*.json
   VideoMAE pretrained clip-level action hint

3. final_analysis_*.json
   1 + 2를 병합한 최종 POC Output
```

외부 Agent, Supervisor, RAG, 리포트에서 우선 참조할 최종 파일은 다음이다.

```text
storage/vision/outputs/final_analysis/final_analysis_*.json
```

단, PM 계약에 가까운 핵심 Vision Agent Output은 여전히 `agent_output_*.json` 내부의 `agent_output`이다. `final_analysis_*.json`은 POC 검증을 위해 VideoMAE 보조 결과를 감싼 확장 결과로 본다.

---

## 2. 최종 Output Schema: `vision-final-analysis-v1`

생성 코드:

```text
ai/vision/merge_analysis.py
```

저장 위치:

```text
storage/vision/outputs/final_analysis/final_analysis_*.json
```

### 2.1 JSON 구조

```json
{
  "schema_version": "vision-final-analysis-v1",
  "status": "success | partial | failed | unknown",
  "analysis_scope": "single_video_poc",
  "vision_agent_output": {
    "agent_output": {}
  },
  "video_understanding": {},
  "comparison_summary": {},
  "limitations": []
}
```

### 2.2 필드 설명

| 필드 | 타입 | 설명 |
|---|---|---|
| `schema_version` | string | 최종 병합 결과 스키마 버전. 현재 `vision-final-analysis-v1` |
| `status` | string | 기존 Vision Agent Output의 처리 상태를 승계한다. |
| `analysis_scope` | string | 현재 POC 범위. 단일 영상 검증이므로 `single_video_poc` |
| `vision_agent_output` | object | YOLO/bbox 기반 기존 Vision Agent Output 전체를 보존한다. |
| `video_understanding` | object | VideoMAE pretrained 추론 결과를 보조 분석으로 담는다. |
| `comparison_summary` | object | YOLO/bbox 결과와 VideoMAE 결과의 역할 차이를 요약한다. |
| `limitations` | array | 최종 결과 사용 시 제한 사항이다. 과실비율, 법적 책임, 사고유형 확정 불가를 명시한다. |

---

## 3. `vision_agent_output.agent_output` Schema

생성 코드:

```text
ai/vision/schemas.py
```

저장 위치:

```text
storage/vision/outputs/agent_outputs/agent_output_*.json
```

스키마 버전:

```text
vision-agent-output-v2
```

### 3.1 JSON 구조

```json
{
  "agent_output": {
    "node_code": "accident_situation_analysis",
    "status": "success | partial | failed",
    "summary": "",
    "structured_result": {
      "media_type": "video | image | unknown",
      "event_window_candidates": [],
      "key_clips": [],
      "key_frames": [],
      "detected_objects": [],
      "object_change_observations": [],
      "scene_context_candidates": [],
      "user_claim_comparison": {},
      "field_summary": "",
      "evidence_candidates": [],
      "unavailable_items": [],
      "limitations": []
    },
    "metadata": {}
  }
}
```

### 3.2 핵심 필드 설명

| 필드 | 타입 | 설명 |
|---|---|---|
| `node_code` | string | 현재 구현 기준 `accident_situation_analysis` |
| `status` | string | 탐지 결과가 있으면 `success`, 없으면 `partial` |
| `summary` | string | 사람이 읽을 수 있는 요약. 과실비율/법적 책임을 확정하지 않는다는 문구 포함 |
| `structured_result.media_type` | string | 입력 매체 유형 |
| `event_window_candidates` | array | bbox 변화량이 큰 구간 기반 사고/위험 후보 구간 |
| `key_clips` | array | event window를 clip 후보 형태로 변환한 목록 |
| `key_frames` | array | key frame 목록. `event_before`, `risk_increase`, `event_peak`, `event_after` 역할 포함 |
| `detected_objects` | array | YOLO 탐지 객체 목록. class, confidence, bbox 포함 |
| `object_change_observations` | array | key frame 간 객체 bbox 중심 이동, 면적 변화, 등장/소실 변화 |
| `scene_context_candidates` | array | 보행자/신호등 등 장면 맥락 후보 |
| `user_claim_comparison` | object | 사용자 진술과 Vision 결과 비교 영역. 현재는 진술 미입력 상태 |
| `field_summary` | string | 현장 관찰 요약 |
| `evidence_candidates` | array | 근거 프레임/객체 탐지 후보 목록 |
| `unavailable_items` | array | Vision 단독으로 산정할 수 없는 항목 |
| `limitations` | array | POC, tracking, legal 한계 |
| `metadata` | object | schema version, source path, model, purpose policy 등 |

### 3.3 `event_window_candidates[]`

```json
{
  "event_candidate_id": "event_window_01",
  "event_window_start_sec": 2.933,
  "event_window_end_sec": 9.467,
  "priority_score": 1.0,
  "source_refs": ["frame_03", "frame_04"],
  "basis": "bbox_motion_peak_with_2sec_context",
  "clip_status": "candidate_for_inference"
}
```

의미:

- key frame 사이 객체 bbox 변화량이 큰 구간을 우선 후보로 잡는다.
- 현재는 동일 객체 tracking이 아니라 class 단위 bbox 변화 기반이다.
- 사고 확정 구간이 아니라 clip 생성과 검토를 위한 후보 구간이다.

### 3.4 `detected_objects[]`

```json
{
  "object_id": "obj_frame_04_001",
  "source_ref": "frame_04",
  "class_id": 0,
  "class_name": "person",
  "confidence": 0.8564,
  "bbox": {
    "format": "xyxy",
    "values": [x1, y1, x2, y2]
  },
  "timestamp_sec": 7.467,
  "frame_path": "storage/vision/processed/frames/...jpg"
}
```

### 3.5 `unavailable_items[]`

현재 반드시 명시하는 불가 항목:

```text
fault_ratio
liable_party
traffic_violation
final_accident_type
```

Vision 단독 결과는 관찰 근거일 뿐이며, 과실비율·책임 주체·법적 판단은 확정하지 않는다.

---

## 4. VideoMAE Result Schema

생성 코드:

```text
ai/vision/videomae_infer.py
```

저장 위치:

```text
storage/vision/outputs/videomae_results/videomae_results_*.json
```

스키마 버전:

```text
videomae-inference-result-v1
```

### 4.1 JSON 구조

```json
{
  "schema_version": "videomae-inference-result-v1",
  "source_manifest": "storage/vision/outputs/videomae_inputs/videomae_clip_manifest_*.json",
  "model_name": "MCG-NJU/videomae-base-finetuned-kinetics",
  "device": "cuda | cpu",
  "top_k": 5,
  "clip_count": 1,
  "note": "Kinetics pretrained labels are action hints, not accident-type labels.",
  "clips": []
}
```

### 4.2 `clips[]`

```json
{
  "clip_id": "clip_01",
  "clip_path": "storage/vision/processed/clips/...mp4",
  "clip_start_sec": 0.0,
  "clip_end_sec": 10.0,
  "basis": "short_video_full_context",
  "frame_count": 16,
  "top_predictions": [
    {
      "rank": 1,
      "label_id": 123,
      "label": "driving car",
      "score": 0.563136
    }
  ]
}
```

주의:

- VideoMAE는 현재 사고 도메인 fine-tuning 모델이 아니다.
- 반환 label은 Kinetics action label이다.
- 따라서 `driving car` 같은 결과는 clip 맥락 참고용이며, 사고유형·과실비율·책임 판단값이 아니다.

---

## 5. `video_understanding` 병합 Schema

`final_analysis_*.json` 내부의 VideoMAE 보조 분석 영역이다.

```json
{
  "analysis_type": "videomae_pretrained_clip_inference",
  "model_name": "MCG-NJU/videomae-base-finetuned-kinetics",
  "device": "cuda",
  "source_manifest": "storage/vision/outputs/videomae_inputs/videomae_clip_manifest_*.json",
  "clip_count": 1,
  "clips": [
    {
      "clip_id": "clip_01",
      "clip_path": "storage/vision/processed/clips/...mp4",
      "clip_start_sec": 0.0,
      "clip_end_sec": 10.0,
      "basis": "short_video_full_context",
      "frame_count": 16,
      "top_prediction": {
        "rank": 1,
        "label_id": 123,
        "label": "driving car",
        "score": 0.563136
      },
      "top_predictions": []
    }
  ],
  "interpretation_note": "VideoMAE Kinetics labels are supplementary action hints..."
}
```

---

## 6. 모델 변경 전후 Output 차이

| 구분 | 기존 | 현재 |
|---|---|---|
| 중심 Output | `agent_output_*.json` | `final_analysis_*.json` |
| 모델 | YOLO/bbox 중심 | YOLO/bbox + VideoMAE pretrained 보조 |
| 사고 구간 | `event_window_candidates` | 유지 |
| 객체 근거 | `detected_objects`, `evidence_candidates` | 유지 |
| clip 이해 | 없음 | `video_understanding` 추가 |
| 최종 판단 | Vision 단독 판단 금지 | 동일하게 판단 금지 |
| 과실비율 | 산정하지 않음 | 산정하지 않음 |
| 사고유형 확정 | 확정하지 않음 | 확정하지 않음 |

---

## 7. 현재 기준으로 외부에 전달할 Output

### 7.1 Supervisor/RAG/리포트가 볼 최종 파일

```text
storage/vision/outputs/final_analysis/final_analysis_*.json
```

### 7.2 실제 계약에 가까운 핵심 필드

```text
final_analysis.schema_version
final_analysis.status
final_analysis.vision_agent_output.agent_output.summary
final_analysis.vision_agent_output.agent_output.structured_result.event_window_candidates
final_analysis.vision_agent_output.agent_output.structured_result.key_frames
final_analysis.vision_agent_output.agent_output.structured_result.detected_objects
final_analysis.vision_agent_output.agent_output.structured_result.evidence_candidates
final_analysis.video_understanding.clips[].top_prediction
final_analysis.limitations
```

### 7.3 후속 Agent에게 전달하면 안 되는 의미

아래 값들은 확정값으로 넘기면 안 된다.

```text
fault_ratio
liable_party
traffic_violation
final_accident_type
```

이들은 `unavailable_items` 또는 `limitations`에 남기고, RAG/상담/사용자 진술/법률 판단 노드에서 별도로 처리해야 한다.

---

## 8. 정리

현재 Output Schema의 기준은 다음과 같다.

```text
기존 PM/Vision Agent 계약: agent_output_*.json
현재 POC 최종 산출물: final_analysis_*.json
VideoMAE 결과의 성격: 보조 clip 이해 결과
최종 판단 가능 여부: 불가
```

따라서 문서나 이슈에는 다음과 같이 쓰는 것이 가장 안전하다.

```text
Vision POC Output은 YOLO/bbox 기반 agent_output을 기본 계약으로 유지하고,
VideoMAE pretrained 추론 결과는 video_understanding 보조 섹션으로 병합한다.
최종 산출물은 final_analysis_*.json이며, 과실비율·법적 책임·최종 사고유형은 확정하지 않는다.
```
