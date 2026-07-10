# 🛠 교통사고사실확인원 OCR 파이프라인 가이드 (실행 및 테스트 순서)

본 문서는 `traffic_accident_confirmation_ocr` 모듈을 개발 환경에서 테스트하고, 모델을 평가하며, 최종적으로 프로덕션(운영)에 적용하기까지의 전체 실행 순서를 정리한 기술 문서입니다.

---

## 1. 환경 변수 설정
가장 먼저 OpenAI API 키가 필요합니다. 프로젝트 루트 경로의 `.env` 파일에 아래와 같이 환경변수를 설정합니다.
```env
OPENAI_API_KEY="sk-..."
```
*(참고: 스크립트 내부에서 `dotenv`를 통해 자동으로 로드됩니다.)*

---

## 2. 단위 테스트 (Mock Test) 실행
API 비용을 소모하지 않고 파이프라인의 논리 구조(마스킹, 라우팅 분기, Envelope 포장 등)를 검증하는 단위 테스트입니다.
코드 수정 후에는 가장 먼저 이 테스트를 통과시켜야 합니다.

**실행 명령어:**
```powershell
python -m unittest etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.test_mock_graph
```

**확인 사항:**
- `Success`, `Partial`, `Failed` 흐름이 모두 정상적으로 라우팅되는지 확인
- 주민등록번호, 전화번호가 `[MASKED]`로 치환되는지 확인

---

## 3. 실전 모델 성능 평가 (Model Evaluation)
준비된 5장의 실제 이미지 샘플을 통해 여러 Vision 모델들의 성능(추출률), 속도(ms), 비용(USD)을 평가합니다.

**평가 가능 모델 목록 확인:**
```powershell
python -m etl.fault_cases.src.OCR.eval.run_eval --list
```

**개별 모델 평가 실행 (예: gpt-5.4-nano):**
```powershell
python -m etl.fault_cases.src.OCR.eval.run_eval --model gpt-5.4-nano
```
*원하는 모델명(`gpt-4o`, `gpt-4o-mini` 등)을 바꿔가며 개별적으로 실행합니다. 결과는 `artifacts/eval_results/` 폴더에 JSON으로 누적 저장됩니다.*

---

## 4. 최종 랭킹 보고서 생성 (Report)
누적된 JSON 파일들을 집계하여 어떤 모델이 가장 우수한지 100점 만점으로 정규화된 랭킹 표와 마크다운 보고서를 생성합니다.

**보고서 생성 명령어:**
```powershell
python -m etl.fault_cases.src.OCR.eval.run_eval --report
```

**확인 사항:**
- 터미널에 출력되는 비교표 확인
- `artifacts/eval_results/model_comparison_report.md` 파일이 생성되었는지 확인
- (선택) 가중치 변경: `eval/config.py` 파일 내 `WEIGHT_COST`, `WEIGHT_PERF` 값을 수정한 뒤 위 명령어를 다시 실행하면 점수가 즉시 재계산됩니다.

---

## 5. 프로덕션 적용 및 이관
가장 우수한 평가를 받은 모델(예: `gpt-5.4-nano`)을 실서비스에 적용하는 과정입니다.

1. **모델 고정:** `src/OCR/traffic_accident_confirmation_ocr/prompts.py` 파일을 열고, 상단을 아래와 같이 수정합니다.
   ```python
   DEFAULT_OCR_MODEL = "gpt-5.4-nano"
   ```
2. **폴더 이관 (PM 수행):** `src/OCR/` 아래에 있던 `traffic_accident_confirmation_ocr` 폴더 전체를 잘라내기 하여, 최종 목적지인 `ai/agents/` 폴더 안으로 붙여넣기 합니다.
3. **Supervisor 연동:** 메인 파이프라인에서 해당 Agent 노드를 호출하여 실제 서비스(과실 비율 판단 에이전트 등)와 연동을 시작합니다.
