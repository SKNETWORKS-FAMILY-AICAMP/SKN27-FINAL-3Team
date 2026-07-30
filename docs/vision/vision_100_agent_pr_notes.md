# PR 초안: Vision 100건 검증 계약의 웹·Agent 연결

## PR 목적

검증된 카테고리별 100건 실험의 Vision 계약을 기존 웹→RunPod→Supervisor 경로에 반영한다. 새 Agent나 별도 웹 흐름을 만들지 않고 기존 `vision_media_analysis` 노드를 재사용한다.

## 변경 요약

- 기본 설명 모델을 `Qwen/Qwen3-VL-4B-Instruct`로 변경
- VideoMAE 32프레임, OpenCV·YOLO·Qwen 16프레임 기본값 적용
- 16프레임을 context/pre-impact/impact/post-impact 각 4개로 선정
- VideoMAE `canonical_label`과 `confirmed_accident=true`를 읽기 전용 계약으로 고정
- YOLO class/confidence/bbox와 프레임 시간·역할을 Qwen 입력에 전달
- `vision-qwen-explanation-v1` JSON 검증, 오류별 1회 재시도, 안전 fallback 적용
- Supervisor handoff에 `qwen_explanation` 추가, 기존 `qwen` 입력은 adapter에서 호환
- Qwen3 지원을 위해 RunPod `transformers>=4.57.0,<5` 명시
- 검증된 100건 compact 지표, 발표자용 MD, 비교 HTML, Notebook 추가

## 사용자에게 보이는 동작

1. 사용자가 scan-ready 블랙박스 영상을 올린다.
2. 기존 Vision Agent가 RunPod endpoint를 호출한다.
3. VideoMAE가 사고유형 후보를 고정하고 YOLO가 객체 근거를 만든다.
4. Qwen3가 유형을 바꾸지 않고 상황 설명 JSON을 만든다.
5. 실패 시 VideoMAE·YOLO 결과는 남고 Qwen만 fallback 처리된다.
6. 안전한 handoff가 기존 Supervisor 경로로 전달된다.

## 배포 설정

```dotenv
VISION_RUNTIME_PROVIDER=runpod
VISION_QWEN_MODEL_ID=Qwen/Qwen3-VL-4B-Instruct
VISION_QWEN_MODEL_REVISION=
VISION_TRAINED_CLASSIFIER_CHECKPOINT=/runpod-volume/models/videomae
```

RunPod image를 새 `requirements-vision-runpod.txt`로 다시 빌드해야 한다. VideoMAE checkpoint와 YOLO weight는 Git에 넣지 않고 RunPod volume/cache에서 제공한다.

## 검증 기준

- Vision client/worker/adapter 회귀 테스트 통과
- Qwen frame reference와 schema contract 테스트 통과
- `confirmed_accident`와 `canonical_label` 보존 테스트 통과
- 보고서 compact metrics와 MD/HTML 수치 일치
- Notebook의 모든 Python code cell이 저장소 root에서 실행
- 대용량 영상·프레임·weight가 Git diff에 없어야 함

## 의도적으로 제외한 항목

- 원본 영상 400건과 6,400개 프레임
- 환경·날씨·노면 확장 schema
- 16/24프레임 A/B
- Vision 이후 FR 자동 진행
- 모델 weight와 Hugging Face cache

## 위험과 롤백

- Qwen3 평균 latency가 Qwen2.5보다 약 3.77초 길다.
- 배포 이미지에 Qwen3 지원 transformers가 없으면 dependency error로 degraded된다.
- 즉시 롤백은 `VISION_QWEN_MODEL_ID=Qwen/Qwen2.5-VL-3B-Instruct`로 가능하며, adapter는 구형 `qwen` handoff도 계속 허용한다.

## PR 본문 예시

### Summary

- wire the verified Vision 100/category contract into the existing web→RunPod→Supervisor path
- use VideoMAE 32-frame classification plus 16 impact-centred YOLO/Qwen evidence frames
- default to Qwen3-VL-4B with strict JSON retry/fallback and locked accident labels
- add verified 100-run metrics and presenter-ready MD/HTML/Notebook

### Test plan

- `python -m pytest test/test_runpod_vision_client.py test/test_runpod_vision_worker.py test/test_vision_media_analysis_adapter.py test/test_vision_run_to_supervisor.py test/test_vision_vlm_contract.py test/test_vision_report_artifacts.py -q`

### Validation result

- Vision integration and report suite: `106 passed`
- Changed Python modules: `py_compile` passed
- Patch hygiene: `git diff --check` passed
- Secret and large-file scan: passed
- The standalone HTML was structurally validated by the report tests. Browser visual QA was unavailable because neither the in-app webview nor the Chrome extension could attach in this session.
- A broader unrelated suite had four environment/base-branch failures: one missing `ai.agents.appeal_decision_flow` module and three missing PyMuPDF (`fitz`) imports. These files are outside this Vision diff.

### Data policy

No raw video, extracted frame, model weight/cache, or secret is included.
