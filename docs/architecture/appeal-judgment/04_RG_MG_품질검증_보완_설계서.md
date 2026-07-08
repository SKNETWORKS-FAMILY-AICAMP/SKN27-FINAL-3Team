# RG·MG 품질검증 보완 설계서
**과태료 이의가능성 판단 Agent** · Design Document (변경 제안, 미구현)

| 항목 | 값 |
|------|-----|
| 문서 번호 | QA-005 |
| 버전 | v0.1 (초안) |
| 작성일 | 2026-07-08 |
| 근거 문서 | ARCH-001 v4.3 §11-2·§11-3, DATA-003 §2-2·§8, RG_MG_비교정리.md, `ai/agents/appeal_decision_flow/`(risk_gate.py, merit_gate.py, guide.py, state.py), `test/`(unit 75 + integration 19 + real_llm 7 = 108) |
| 상태 | 설계 단계 — 코드 미변경. 구현 착수 전 리뷰용 |
| 배경 | 리뷰 Q3~Q5(FAQ 답변)에서 "솔직히 말하면 아직 검증/구현되지 않았다"고 인정한 세 가지 공백을 해소하기 위한 변경 설계 |

---

## 0. 배경 — 이 문서가 다루는 세 가지 공백

기존 FAQ(리뷰 Q&A)에서 스스로 인정한 미해결 항목 세 가지를 변경 대상으로 삼는다.

| # | 질문 요지 | 인정한 공백 | 실제 불이익 방향 |
|---|---|---|---|
| Q3 | 시행규칙 142조 6호(포괄조항)처럼 키워드로 못 잡는 사유의 판단 정확도 검증 | 6호형 표현만 따로 뽑아 정확도를 측정한 전용 테스트셋이 없음. 108건 테스트 중 몇 건이 이런 케이스인지도 집계 안 됨 | 테스트 커버리지 공백 — 회귀 발생을 못 잡을 위험 |
| Q4 | RG(재현율 우선)·MG(보류 우선)의 폴백 방향 비대칭이 사용자에게 불리한 경우 | MG가 LLM 호출 실패로 `merit="보류"`를 반환하면, 실제로는 승산 강한 사유였어도 사용자에게 "애매하다"고 안내됨 → 사용자가 승산 있는 이의신청을 포기할 수 있음 | **사용자 실제 불이익** — 가장 시급 |
| Q5 | temperature=0의 재현성과 별개로, 패러프레이즈 간 판정 일관성(강건성) 검증 | 같은 의미의 다른 문장이 같은 판정을 받는지 보는 강건성 테스트가 없음. 현재 108건이 정형화된 문구 위주일 가능성 | 테스트셋 대표성 공백 — 실사용자 표현 다양성 미반영 |

세 항목은 서로 독립적으로 구현 가능하다. 우선순위는 **Q4 > Q3 > Q5**로 둔다 — Q4만 유일하게
"기술적 실패가 사용자의 실제 의사결정을 왜곡"하는 경로이기 때문이다.

---

## 1. 변경 목표 요약

| 변경 | 대상 파일(현행) | 신규 산출물 | 코드 변경 여부 |
|---|---|---|---|
| ① LLM 실패/실제 판단 구분 (Q4) | `risk_gate.py`, `merit_gate.py`, `state.py`, `guide.py` | 신규 상태 필드 + disclaimer 분기 + 재시도 1회 | **있음** |
| ② 142조 6호 전용 gold 테스트셋 (Q3) | `test/test_appeal_decision_flow_real_llm.py` | `ai/evaluation/` 하위 gold셋 + 측정 스크립트 | 테스트/평가 코드만 추가 (판정 로직 불변) |
| ③ 패러프레이즈 강건성 테스트 (Q5) | 상동 | `ai/evaluation/` 하위 패러프레이즈셋 + 일관성 측정 스크립트 | 테스트/평가 코드만 추가 (판정 로직 불변) |

②·③은 같은 성격(실제 GPT API 기반 평가, `ai/evaluation/`에 배치)이라 실행 인프라를 공유한다.

---

## 2. 변경 ① — LLM 호출 실패와 실제 판단의 구분 (Q4 대응)

### 2-1. 문제 재확인

`merit_gate.py`의 현재 폴백:

```python
except Exception:
    return {"merit": "보류", "merit_basis": "LLM 판단 실패로 보류 처리"}
```

`merit_basis`에 실패 사유가 텍스트로 남긴 하지만, `guide_generation_node`(`guide.py`)는
`merit` 값만 보고 톤을 결정하는 `_merit_risk_tone()`을 쓰므로, 최종 사용자 안내 문구에는
"판단 유보"와 "호출 실패"가 구분 없이 같은 "보류" 톤으로 나간다. `risk_gate.py`도 동일한
구조로 `risk_flag=true`만 반환하고 실패 여부를 안내에 반영하지 않는다.

결과적으로 사용자는 "이 사유는 법적으로 애매합니다"와 "지금 시스템이 일시적으로 판단하지
못했습니다, 다시 시도하세요"를 구분할 방법이 없다 — 후자인데 전자로 오인해 실제로는 승산
있는 이의신청을 포기할 위험이 있다.

### 2-2. 설계

#### (a) 재시도를 먼저 추가한다 — 폴백 이전 단계

실패의 상당수(네트워크 순단, 레이트리밋)는 즉시 재시도로 해소된다. 폴백 문구를 정교화하기
전에, 애초에 폴백까지 가는 빈도를 줄이는 게 우선이다.

```python
# risk_gate.py / merit_gate.py 공통 패턴
def _call_llm_with_retry(fn, *args, retries=1, **kwargs):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
    raise last_exc
```

- 재시도 1회, 백오프 없음(짧은 타임아웃성 오류가 대상이므로 즉시 재시도로 충분 — 레이트리밋이
  의심되면 추후 조정). 재시도 자체가 응답 지연을 유발하므로 과도한 횟수는 지양.
- 파싱 실패(`JSONDecodeError`, 정규식 매칭 실패)는 네트워크 문제가 아니라 프롬프트/모델 응답
  품질 문제이므로 재시도해도 같은 결과가 나올 가능성이 높다 — 재시도는 예외 종류를 구분하지
  않고 동일하게 적용하되(단순성 우선), 재시도 후에도 실패하면 §2-2(b)로 폴백한다.

#### (b) 상태 필드 신설 — "판단 결과"와 "판단 실패"를 분리

`state.py`에 각 게이트별로 판단 실패 여부를 나타내는 필드를 추가한다. 기존 `merit`·`risk_flag`
값 자체(폴백 정책)는 ARCH-001 §11-2 원칙을 그대로 유지한다 — 새 필드는 안내 문구 분기용이지,
판정 로직을 바꾸지 않는다.

```python
# state.py 추가안
GateFailureReason = Literal["llm_call_failed", "llm_response_invalid"]

class AppealJudgmentState(TypedDict, total=False):
    ...
    # ── risk_classification_node (RG) 출력 ──
    risk_judgment_degraded:   Optional[bool]              # True면 risk_flag는 폴백값
    risk_degraded_reason:     Optional[GateFailureReason]

    # ── merit_classification_node (MG) 출력 ──
    merit_judgment_degraded:  Optional[bool]               # True면 merit는 폴백값("보류")
    merit_degraded_reason:    Optional[GateFailureReason]
```

`merit_gate.py` 변경 방향:

```python
try:
    result = _call_llm_with_retry(_call_llm_merit, reason, law_context, retries=1)
    merit = result.get("merit")
    merit_basis = result.get("merit_basis")
    degraded = merit not in _VALID_MERIT   # 형식은 응답했지만 값이 잘못된 경우도 degraded로 취급
    if degraded:
        merit = "보류"
except Exception:
    return {
        "merit": "보류",
        "merit_basis": "LLM 판단 실패로 보류 처리",
        "merit_judgment_degraded": True,
        "merit_degraded_reason": "llm_call_failed",
    }

return {
    "merit": merit,
    "merit_basis": merit_basis,
    "merit_judgment_degraded": degraded,
    "merit_degraded_reason": "llm_response_invalid" if degraded else None,
}
```

`risk_gate.py`도 동일 패턴(`risk_judgment_degraded`, `risk_degraded_reason`)을 2단계 LLM
분기에 적용한다. 1단계 키워드 매칭·0단계 도난 예외는 LLM을 안 쓰므로 이 필드와 무관(`None`
유지).

#### (c) `guide_generation_node`에서 안내 문구 분기

`guide.py`의 `_merit_risk_tone()` 계열에 `merit_judgment_degraded`/`risk_judgment_degraded`를
반영해, 폴백 상황에서는 기존 "보류"/"위험" 톤 앞에 **원인이 다르다는 것을 명시**하는 문구를
추가한다.

```
(기존 "보류" 톤 앞에 추가)
"※ 이 판정은 일시적인 시스템 오류로 정상적으로 완료되지 못했습니다. 실제 승산과 무관하게
안전하게 '보류'로 표시된 것이니, 잠시 후 다시 시도하거나 채팅으로 다시 요청해 주세요."
```

이 문구가 붙는 조건은 `merit_judgment_degraded=True` 또는 `risk_judgment_degraded=True`
(둘 중 하나만 실패해도 노출 — RG·MG는 병렬 호출이라 한쪽만 실패할 수 있음, ARCH-001 §11-3
`TestParallelDispatch` 참고).

#### (d) Supervisor 연동 계약 갱신 (ARCH-001 §6)

`agent_results["appeal_judgment"]["structured_result"]`에 위 신규 필드가 추가되므로,
Supervisor가 이 필드를 보고 **자동 재시도**를 트리거할 수 있는 여지를 계약에 명시한다.

- 제안: `*_judgment_degraded=True`인 응답을 받으면 Supervisor는 (a) 사용자에게 위 disclaimer
  문구를 그대로 노출하거나, (b) 동일 입력으로 즉시 1회 자동 재호출 후 그래도 degraded면 그때
  사용자에게 노출하는 두 가지 전략 중 선택 가능. 이 설계서는 (a)를 최소 구현으로 제안하고,
  (b)는 Supervisor 쪽 재호출 비용·루프 방지 로직이 필요해 별도 설계로 분리한다(§7 미결 사항).

### 2-3. 산출물

- `state.py`: `risk_judgment_degraded`, `risk_degraded_reason`, `merit_judgment_degraded`,
  `merit_degraded_reason` 4개 필드 추가
- `risk_gate.py`, `merit_gate.py`: 재시도 래퍼 + degraded 필드 반환
- `guide.py`: degraded 상태 disclaimer 분기 추가
- `02_데이터모델_설계서.md` §2-2/§8, `03_API인터페이스_설계서.md`: 신규 필드 스키마 반영
- `01_아키텍처_설계서.md` §6: Supervisor 연동 계약에 degraded 필드 처리 방침 추가
- 단위 테스트: LLM 호출을 mock으로 강제 실패시켜 `*_judgment_degraded=True`가 정확히
  반환되는지, 재시도 1회 후 성공하면 degraded가 안 남는지 검증 (`test/unit/`에 케이스 추가)

---

## 3. 변경 ② — 142조 6호(포괄조항) 전용 gold 테스트셋 (Q3 대응)

### 3-1. 문제 재확인

RG 1단계 키워드(`_CATEGORY_C_KEYWORDS`)는 142조 1~5호 대응 시드만 다룬다. 6호(포괄조항)와
1차 고지서의 14조 정황요소(동기·목적·방법·결과, 태도, 연령·재산상태·환경)는 표현이 정형화돼
있지 않아 전부 2단계 LLM 판단(`_call_llm_classifier`)으로 위임된다. 이 경로는 결정론적
키워드 매칭이 아니므로 정확도를 별도로 측정해야 하는데, 현재 108건(unit 75 + integration
19 + real_llm 7 = 101 mock + 7 real, 업데이트_기록.md 2026-07-02 기준) 중 이 경로만 격리해
집계한 적이 없다.

### 3-2. 설계

#### (a) 기존 테스트 재태깅 — 우선 순위가 낮은 선행 작업

새 gold셋을 만들기 전에, 기존 108건 중 "1단계 키워드로 종결되는 케이스"와 "2단계 LLM까지
가는 케이스"를 구분하는 메타데이터부터 추가한다. `test_appeal_decision_flow_real_llm.py`는
이미 주석("2단계 LLM까지 가야만 판단 가능한 애매한 표현만 쓴다")으로 이 구분을 의도하고
있으므로, `pytest.mark`로 명시화한다.

```python
pytestmark_llm_path = pytest.mark.gate_path("llm_stage2")   # vs "keyword_stage1"
```

이 태그만으로도 "108건 중 몇 건이 6호형인가"라는 원 질문에 즉답할 수 있다 (`pytest -m
gate_path_llm_stage2 --collect-only`로 집계).

#### (b) 신규 gold 테스트셋 구성

`ai/evaluation/rg_category_c_gold.jsonl` (신설) — 142조 6호·14조 정황요소류 표현만 모은
라벨셋. 각 레코드:

```json
{
  "id": "c6-001",
  "notice_stage": "사전통지",
  "user_appeal_reason": "차가 갑자기 고장나서 견인차를 부를 때까지 어쩔 수 없이 그 자리에 세워둘 수밖에 없었습니다",
  "gold_category": "C",
  "gold_risk_flag": true,
  "source_clause": "142조 6호(포괄조항, 차량 고장)",
  "notes": "1단계 키워드 미매칭 확인됨 — _CATEGORY_C_KEYWORDS 어느 것도 부분일치 없음"
}
```

- **규모**: 최소 30건 — 6호(포괄조항, notice_stage 무관 정황) 15건 + 14조 정황요소(1차
  고지서 전용) 15건. 신규 문구를 만들 때는 반드시 `_CATEGORY_C_KEYWORDS`와 부분일치가
  없는지 기계적으로 검증해(`assert not any(kw in reason for kw in _CATEGORY_C_KEYWORDS)`)
  1단계에서 우회되지 않고 실제로 2단계까지 가는 케이스만 포함시킨다.
- **라벨링 기준**: RG_MG_비교정리.md의 "화자 본인이 위반 당시 운전자였음을 전제로 정황을
  설명하는 진술 전반" 정의를 그대로 적용. 라벨은 최소 2인이 독립적으로 부여 후 불일치
  건만 합의(inter-rater agreement 기록).
- **출처**: (1) 팀 기존 심의사례 데이터(`etl/fault_cases/Fault_cases_MD/심의사례`)에서
  6호/14조 해당 문구 추출, (2) 실사용자 문의 패턴(있다면), (3) 위 두 출처가 부족하면
  법조문 문언을 참고해 수작업 작성 — 단, (3)만으로 채우면 "정형화된 문구 위주"라는
  기존 한계가 반복되므로 (1)·(2)를 우선한다.

#### (c) 측정 스크립트

`ai/evaluation/run_category_c_eval.py` (신설) — gold셋을 실제 `graph.invoke()`(또는
`risk_classification_node` 단독)로 돌려 지표를 계산한다.

- **정확도(accuracy)**: `risk_flag` 일치율, `risk_trigger_category` 일치율(해당 시)
- **False Negative Rate 우선 관리**: RG는 재현율 우선 설계이므로(ARCH-001 §5-2), gold
  `risk_flag=true`인데 예측이 `false`인 건을 별도로 강조 리포트 — 이게 실제 안전 문제로
  이어지는 케이스
- **재현성 체크**: 각 레코드 3회 반복 호출 후 `risk_flag` 다수결과 매회 일치 여부 기록
  (temperature=0 재현성이 6호형 표현에서도 유지되는지 별도 확인 — 업데이트_기록.md
  2026-07-02 항목이 이미 이 재현성 문제를 다뤘으나 검증은 일반 표현 위주였음)
- **실행 방식**: `OPENAI_API_KEY` 필요, CI 상시 실행 대상이 아니라 수동/정기 실행
  (§5 참고) — `test_appeal_decision_flow_real_llm.py`와 같은 `_requires_api` skip 패턴 재사용

### 3-3. 산출물

- `ai/evaluation/rg_category_c_gold.jsonl` — 최소 30건 라벨셋
- `ai/evaluation/run_category_c_eval.py` — 정확도/FN율/재현성 측정 스크립트, 결과를
  `ai/evaluation/reports/`(신설)에 마크다운 리포트로 출력
- 기존 `test_appeal_decision_flow_real_llm.py`에 `gate_path` 마커 추가
- `RG_MG_비교정리.md` §2에 "6호형 표현 정확도는 QA-005 gold셋으로 정기 측정"이라는 참조 추가

---

## 4. 변경 ③ — 패러프레이즈 강건성 테스트 (Q5 대응)

### 4-1. 문제 재확인

`temperature=0`은 **같은 입력**에 대한 재현성만 보장한다(업데이트_기록.md 2026-07-02).
**의미가 같고 표현만 다른** 여러 문장이 같은 판정을 받는지는 별도 축의 문제이며, 현재
테스트셋(108건)은 각 시나리오당 문장 하나씩만 있어 이 축을 전혀 커버하지 못한다.

### 4-2. 설계

#### (a) 패러프레이즈 그룹 구성

`ai/evaluation/paraphrase_robustness_gold.jsonl` (신설) — 기존 대표 시나리오(카테고리
A/B/C 각각, merit 강함/보류/낮음 각각)를 **그룹**으로 묶고, 그룹마다 원문 1개 + 패러프레이즈
3~4개를 배치한다.

```json
{
  "group_id": "cat-a-3rd-party-driver",
  "gold_risk_flag": true,
  "gold_risk_trigger_category": "A_제3자운전주장",
  "variants": [
    {"id": "orig", "text": "다른 사람이 운전했습니다"},
    {"id": "v1", "text": "그날 운전대는 제가 아니라 동생이 잡았어요"},
    {"id": "v2", "text": "제 차이긴 한데 운전은 지인이 했습니다"},
    {"id": "v3", "text": "제가 아니라 다른 사람 몰던 차예요"}
  ]
}
```

- **패러프레이즈 작성 방법**: LLM으로 초안 생성 후(예: "다음 문장을 의미는 유지하되 표현만
  바꿔 3개 변형을 만들어줘") 사람이 검수 — 의미가 실제로 동일한지, 우연히 1단계 키워드에
  다시 걸리지 않는지(그러면 강건성 테스트가 아니라 키워드 테스트가 됨) 확인 필수.
  케이스 절반은 의도적으로 1단계 키워드를 피해가는 완곡한 표현으로 구성해 2단계 LLM
  강건성을 직접 겨냥한다.
- **규모**: RG 6개 그룹(A/B/C × 확정/애매) + MG 6개 그룹(강함/보류/낮음 × notice_stage
  2종) 수준에서 시작, 그룹당 4개 변형 → 약 48건.

#### (b) 강건성 지표

- **그룹 내 일치율(consistency rate)**: 한 그룹의 모든 변형이 동일한 예측값(`risk_flag`
  또는 `merit`)을 받은 비율. 100%면 완전 강건, 아니면 어느 변형에서 갈리는지 리포트.
- **정확도와 분리해서 본다**: 그룹 전체가 일관되게 틀렸다면(gold와 다르지만 그룹 내부는
  일치) 이는 강건성 문제가 아니라 정확도 문제 — §3의 gold셋 이슈로 분류. 강건성은
  "같은 그룹 안에서 표현만 바꿨는데 판정이 갈리는가"만 본다.

#### (c) 실행 방식과 비용

- 실제 GPT API 호출 기반(mock으로는 강건성 자체를 검증할 수 없음)이라 §3과 마찬가지로
  CI 상시 실행 대상이 아니다. `ai/evaluation/run_paraphrase_eval.py` (신설)로 수동/정기
  실행, `schedule` 스킬로 주 1회 자동 실행 + 결과 리포트 저장을 제안(§5).
- 48건 × 온도 0 단일 호출 기준 비용은 gpt-4o-mini 기준 미미하나, §3-2(c)의 재현성
  체크(3회 반복)까지 합치면 호출 수가 늘어나므로 두 평가를 한 번에 묶어 실행하는 배치
  스크립트를 공유하는 게 효율적이다(§5).

### 4-3. 산출물

- `ai/evaluation/paraphrase_robustness_gold.jsonl` — 약 48건(12그룹 × 4변형)
- `ai/evaluation/run_paraphrase_eval.py` — 그룹 내 일치율 측정 스크립트
- `업데이트_기록.md`에 강건성 테스트 도입 항목 추가(재현성 항목과 구분되는 별도 축임을
  명시)

---

## 5. 공통 구현 계획

### 5-1. 순서 제안

1. **①(Q4) 먼저** — 사용자 실제 불이익 경로이므로 최우선. `state.py`·`risk_gate.py`·
   `merit_gate.py`·`guide.py` 변경은 서로 의존적이라 한 번에 묶어 구현.
2. **②(Q3)** — ③(Q5)과 평가 인프라(`ai/evaluation/`, gold셋 포맷, 실행 스크립트 골격)를
   공유하므로 먼저 인프라를 만들면서 진행.
3. **③(Q5)** — ②의 인프라 위에서 패러프레이즈셋만 추가하는 형태로 이어서 진행.

②·③은 코드 변경이 아니라 테스트/평가 자산 추가이므로 ①과 별도로 병행 가능하다.

### 5-2. `ai/evaluation/` 디렉토리 구조 (신설)

```
ai/evaluation/
├── rg_category_c_gold.jsonl
├── paraphrase_robustness_gold.jsonl
├── run_category_c_eval.py
├── run_paraphrase_eval.py
└── reports/                     # 실행 결과 마크다운 스냅샷 (날짜별)
```

현재 `ai/evaluation/.gitkeep`만 있는 빈 디렉토리이므로 이름 충돌 없음.

### 5-3. 완료 기준 (Definition of Done)

| 변경 | 완료 기준 |
|---|---|
| ① | degraded 필드가 실제 LLM 실패 mock 테스트로 검증됨 + disclaimer 문구가 degraded 시에만 노출됨을 단위 테스트로 확인 + 02/03 설계서 필드 반영 |
| ② | gold 30건 이상 + 라벨 2인 합의 기록 + FN율 리포트 산출 + 108건 중 "2단계 경로" 건수가 `pytest -m` 집계로 즉답 가능 |
| ③ | 12그룹 이상 + 그룹 내 일치율 리포트 산출 + 갈리는 변형이 있으면 원인 가설(표현 모호성/프롬프트 한계 등) 기록 |

---

## 6. 영향 범위

| 파일 | 변경 유형 |
|---|---|
| `ai/agents/appeal_decision_flow/state.py` | 필드 4개 추가 |
| `ai/agents/appeal_decision_flow/risk_gate.py` | 재시도 래퍼 + degraded 반환 |
| `ai/agents/appeal_decision_flow/merit_gate.py` | 재시도 래퍼 + degraded 반환 |
| `ai/agents/appeal_decision_flow/guide.py` | degraded disclaimer 분기 추가 |
| `test/unit/test_appeal_decision_flow_nodes.py` | degraded 케이스 단위 테스트 추가 |
| `test/test_appeal_decision_flow_real_llm.py` | `gate_path` 마커 추가 |
| `ai/evaluation/*` | 신설 (gold셋 2종 + 스크립트 2종) |
| `docs/architecture/appeal-judgment/01_아키텍처_설계서.md` | §6 Supervisor 계약 갱신 |
| `docs/architecture/appeal-judgment/02_데이터모델_설계서.md` | §2-2/§8 필드 추가 반영 |
| `docs/architecture/appeal-judgment/03_API인터페이스_설계서.md` | 응답 스키마 갱신 |
| `docs/architecture/appeal-judgment/RG_MG_비교정리.md` | 6호 gold셋 참조 추가 |
| `docs/architecture/appeal-judgment/업데이트_기록.md` | 이번 변경 이력 추가 |

---

## 7. 리스크 및 미결 사항

- **Supervisor 자동 재호출(§2-2d의 전략 b)**: 이 설계서는 최소 구현(사용자 안내 노출)만
  다룬다. Supervisor가 degraded 응답을 감지해 자동 재시도할지는 Supervisor 쪽(`app/services/
  supervisor_llm_service.py`) 설계가 필요 — 무한 재시도 루프 방지, 재시도 횟수 상한,
  사용자 대기시간 트레이드오프를 별도로 검토해야 한다.
- **gold셋 라벨링 주관성**: 142조 6호·14조 정황요소는 원래 "포괄조항"이라 법조문 자체가
  경계가 불명확하다 — 2인 합의로도 완전히 객관적인 라벨을 보장하진 못한다. 리포트에
  inter-rater 불일치율을 함께 남겨 이 한계를 투명하게 기록한다.
  - **재시도 비용**: 재시도 1회 추가는 실패 시 응답 지연을 최대 2배로 늘린다. RG·MG는
  병렬 호출(ARCH-001 §11-3 `TestParallelDispatch`)이라 전체 파이프라인 지연에 미치는
  영향은 제한적이나, 타임아웃 설정값(현재 프롬프트 호출에 명시적 타임아웃 없음)도 함께
  검토가 필요하다.
- **평가 스크립트의 지속적 유지 비용**: gold셋·패러프레이즈셋은 법 개정이나 프롬프트
  변경 시 재검증이 필요하다 — 1회성 산출물이 아니라 `schedule` 스킬로 정기 실행하는
  운영 자산으로 관리해야 한다(§4-2c).

---

## 참고 문서

- `01_아키텍처_설계서.md` §5-2, §6, §11-2, §11-3 — RG/MG 구조적 비대칭, Supervisor 계약,
  기존 폴백 정책·테스트 커버리지
- `02_데이터모델_설계서.md` §2-2, §2-3, §8 — MeritLevel/RiskFlag 정의
- `RG_MG_비교정리.md` — RG/MG 판단 기준·카테고리 C 정의 원문
- `업데이트_기록.md` 2026-07-02 — temperature=0 재현성 문제 해결 이력(본 문서 §4가 다루는
  강건성과는 별개 축)
- `ai/agents/appeal_decision_flow/` — 실제 구현(risk_gate.py, merit_gate.py, guide.py, state.py)
- `test/` — 기존 108건 테스트(unit 75 + integration 19 + real_llm 7)
