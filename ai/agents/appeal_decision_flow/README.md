# Appeal Decision Flow (과태료·범칙금 이의가능성 판단 에이전트)

## 🎯 목적
OCR 에이전트가 추출한 고지서 정보를 바탕으로 **이의신청 가능성을 판단**하고, 사용자가 이의신청 진행 시 겪을 수 있는 **불필요한 불이익(신원 노출로 인한 범칙금 전환 및 벌점 부과 등)을 예방하는 맞춤형 가이드를 제공**하는 것을 목적으로 합니다.

## 👥 협업 팀을 위한 핵심 설계 의도
이 모듈은 단순한 "가능/불가능" 판정을 넘어, **"사용자의 안전(리스크 회피)"**을 최우선으로 설계되었습니다.

### 1. 단일 책임 원칙 (OCR과 판단의 분리)
- OCR 에이전트(`fine_notice_analysis`)는 텍스트 추출과 문서 분류에만 집중합니다.
- 본 `appeal_decision_flow` 모듈은 Supervisor로부터 전달받은 OCR 결과(`fine_type`, `notice_stage`, `opinion_deadline` 등)를 입력으로 받아, 오직 **법적/절차적 판단과 안내**에만 집중합니다.

### 2. 신원 노출 리스크 방어 (Risk Gate, RG)
- **문제점:** 과태료는 소유자 책임이라 벌점이 없지만, "제가 운전하지 않았습니다" 등 실제 운전자를 특정하는 사유로 이의를 제기할 경우 사건이 범칙금으로 전환되어 **벌점 및 보험료 할증 등 큰 불이익**이 발생할 수 있습니다.
- **해결책:** 사용자의 이의 사유 텍스트를 분석하여 이러한 신원 특정 리스크가 있는지 판단하고, 위험이 감지되면 강한 톤으로 경고합니다.

### 3. 법조문 기반 승산 판별 (Merit Gate, MG)
- 고정된 참조 조문(시행규칙 제142조, 질서위반행위규제법 제14조 등)을 LLM의 컨텍스트로 주입하여 사용자의 사유가 법적으로 인용될 만한지(승산이 있는지) 단일 호출로 판별합니다.
- 최종 출력은 단순한 점수가 아니라 **Risk(리스크 유무) × Merit(승산 강도)**의 6칸 매트릭스 조합으로 결정되며, 항상 리스크(Risk) 정보를 승산(Merit)보다 우선하여 경고합니다.

### 4. 절차적 예외 처리 및 가이드
- **다단계 기한 계산:** 문서 유형(`사전통지`, `1차 고지서` 등)에 따라 기한(`opinion_deadline` 등)을 다르게 해석하여 법정 이의제기 마감일을 정확히 안내합니다.
- **법령 경량 검증:** 사내 법령DB 파이프라인을 재사용해 고지서에 적힌 법조항(`law_code`)의 실존 여부를 가볍게 검증하고, 실패 시 사용자에게 고지서 원본 대조를 권고합니다.
- **통합된 채널 안내:** 접수 채널은 지자체마다 상이하므로, 발부기관(경찰/지자체) 구분 없이 "서면 접수 원칙 + 관할 기관 직접 확인"이라는 단일 문구로 통합 안내하여 유지보수 부담을 줄였습니다.

## 🔄 전체 실행 파이프라인 요약
1. **분기 처리:** 범칙금 문서일 경우 판정을 생략하고 즉결심판 절차 가이드만 제공. 과태료일 경우 다음 단계로 진행.
2. **기한 도과 체크:** 이의제기 기한이 지났다면 즉시 '불가' 판정 후 조기 종료.
   - `notice_stage`와 무관하게 항상 이 체크가 가장 먼저 실행됩니다. 1차 고지서의 기산일인
     `notice_received_date`(수령일, Supervisor 공급 필드)는 필수가 아니라 선택 입력이라, 없으면
     기한 계산을 생략하고 방어적으로 통과시킵니다 — 이 경우 최종 가이드에 "법정 기한을 계산할
     수 없다"는 경고가 대신 포함됩니다. 상세는
     `docs/architecture/appeal-judgment/01_아키텍처_설계서.md` §9-8 참고.
3. **병렬 판정 (RG & MG):** 이의 사유를 바탕으로 리스크(신원 노출 위험)와 승산(인용 가능성)을 동시에 판별.
4. **최종 가이드 조립:** 
   - ① 타임라인 안내 
   - ② 유불리 경고 (과태료 유지 vs 범칙금 전환) 
   - ③ 절차 방식 (대면/서면) 
   - ④ 철회 가능 시점 
   - ⑤ 벌점·전과 오해 정정 
   - ⑥ 법률자문 아님 (Disclaimer)
   위 6가지 가이드를 결합하여 최종 응답을 반환합니다.

## 📂 파일 구조

`fine_notice_analysis`(OCR 에이전트)의 파일당 단일 책임 패턴을 그대로 재사용합니다. 상세 매핑
근거는 `docs/architecture/appeal-judgment/01_아키텍처_설계서.md` §10이 정본입니다.

| 파일 | 역할 |
|---|---|
| `state.py` | `AppealJudgmentState` + 열거형 (`JudgmentStatus`, `MeritLevel` 등) |
| `law_refs.py` | MG·RG 참조 법조문 원문 상수 (142조/제7조/제14조/제160조4항1호 등). **MVP 하드코딩 대상** — 나중에 팀 법령DB API로 교체 시 이 파일만 손대면 됨 |
| `deadline.py` | `deadline_gate_node` |
| `law_code_check.py` | `law_code_check_node` (`LDB_CHECK`). MVP: `law_code_verified` 항상 `True` 스텁 |
| `reason_intake.py` | `reason_intake_node` — `user_appeal_reason` 부재만 재질문 트리거. 1차 고지서면 재질문 시 수령일도 선택적으로 함께 요청 |
| `risk_gate.py` | `risk_classification_node` (RG) — 도난 예외(0단계) → 카테고리 A/B/C(1단계) → LLM(2단계) |
| `merit_gate.py` | `merit_classification_node` (MG) — notice_stage×위반유형별 참조 법조문 선택 후 LLM 판단 |
| `verdict.py` | `verdict_node` (E) — RG×MG 매트릭스 |
| `guide.py` | `guide_generation_node` (G) — ①~⑥ 가이드 조립 |
| `prompts.py` | RG 2단계·MG LLM 프롬프트 |
| `utils.py` | `make_envelope` 등 공용 헬퍼 (OCR 에이전트와 동일 패턴) |
| `graph.py` | `StateGraph` 조립 — notice_stage 무관 단일 순서(`deadline_gate_node → law_code_check_node → reason_intake_node`) |
| `__init__.py` | `graph` export |
