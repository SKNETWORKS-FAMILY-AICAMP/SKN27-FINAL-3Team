# Fine-Notice OCR 필드 확인 — 구현 요약 및 설계 결정

**작성일**: 2026-07-20
**관련 이슈/PR**: #243(작업 지시), #244(`patch/issues-from-dev`, 커밋 `7f3e799`)
**관련 문서**: `docs/ops/project-readiness-master-checklist.md`(B, C-2, D-1), `docs/issues/2026-07-20-agent-readiness-gap-report.md`, `docs/architecture/프롬프트.txt`(작업 분담 지시서)

## 배경

PR #244가 마스터 체크리스트 B/C-2/D-1 항목에 대응하며 `requires_confirmation`/`unconfirmed_fields`를 추가했으나, GitHub 리뷰(hi20260204-maker)에서 이 값이 `structured_result`(Supervisor 경계를 넘는 envelope), `AppealJudgmentState` 어디에도 전달·소비되지 않는 **죽은 상태값**이라는 지적을 받았다. 이 문서는 그 지적을 해소하기 위해 실제로 구현한 내용과, 범위 검토 끝에 되돌린 부분, 그리고 의도적으로 범위에서 뺀 부분을 정리한다.

## 담당 범위와 범위 위반 정정 이력

담당 범위는 `docs/architecture/프롬프트.txt`(작업 분담 지시서, 팀원 hi20260204-maker 작성) 기준 **`ai/agents/fine_notice_analysis/**`와 `ai/agents/appeal_decision_flow/**`의 내부 구현·입출력 품질**로 한정되며, 지시서는 다음을 명시적으로 금지한다.

- "서버 게이트, 케이스 분석 시작 API, 큐잉 권한은 건드리지 말아야 한다"
- `backend/chatbot/views.py`의 "HTTP 오류 응답 및 권한 처리"
- `backend/chatbot/case_repository.py`, 분석 작업 생성·큐잉·소유권 검증
- `ai/agents/law_ground_search/**`, `ai/agents/objection_report_generation/**` (별도 담당자)

1차 구현(커밋 `7f3e799`)에서는 Agent 내부 데이터 배선 외에 **`backend/chatbot/{views,repositories,urls}.py`에 신규 확인 API를, `app/web/*`에 신규 확인 UI 패널을 직접 만들었다** — 지시서가 "구현하지 말고 먼저 보고하라"고 명시한 영역을 사전 보고 없이 침범한 것이다. 이후 지시서를 다시 대조 점검하는 과정에서 이 사실을 발견했고, 사용자 확인을 거쳐 **API·프런트엔드 부분만 되돌렸다**(Agent 내부 구현은 유지). 아래 "구현 내용"은 되돌린 뒤 최종적으로 남은 범위만 서술한다.

## 구현 내용 (최종, Agent 내부로 한정)

### 1. 데이터 배선 (`ai/agents/fine_notice_analysis/verification.py`, `ai/agents/appeal_decision_flow/state.py`, `app/services/agent_node_service.py`)
- `_structured_from_state`가 `requires_confirmation`/`unconfirmed_fields`를 envelope의 `structured_result`에 포함하도록 수정 — 기존엔 `confidence_verification_node`의 top-level 반환값에만 있어 Supervisor 경계를 넘지 못했다.
- `AppealJudgmentState`에 두 필드를 선언 — `_appeal_decision_state`(agent_node_service.py)가 `AppealJudgmentState.__annotations__` 교집합으로 필드를 옮기므로, 선언만으로 자동 배선된다.
- `_fine_notice_structured_result`의 fallback allowlist에도 두 필드 추가(그래프 미사용 경로 누락 방지). 이 파일(`agent_node_service.py`)은 Agent 실행 경로 글루코드라 경계에 가깝지만, 필드명 2개를 allowlist에 추가하는 것 외의 로직 변경은 없어 "Agent 입출력 품질"의 연장으로 보고 유지했다.

### 2. 이의신청 생성 노드의 미확인 경고 (`ai/agents/appeal_decision_flow/guide.py`)
- `requires_confirmation=True`면 disclaimer에 미확인 필드 목록을 경고로 추가하고, `next_actions`에 "OCR 추출 정보 확인 필요"를 명시. 판정 자체는 막지 않는다(차단은 서버 게이트 영역, 손대지 않음).

### 3. 법령 최신성 표시 — 축소판 (`etl/legal/search.py`, `ai/agents/appeal_decision_flow/law_code_check.py`, `guide.py`)
- `law_code_last_verified()` 신설 — `law_chunks.created_at`을 조회해 반환(스키마 변경 없음).
- `law_code_check_node`가 이 값을 `law_reference_verified_at`으로 state에 반영.
- 하드코딩된 "과거(2026년) 기준" 문구를 실제 수집일 기반 문구로 교체.

## 되돌린 부분 (범위 위반으로 판단, revert 완료)

| 파일 | 내용 | 되돌린 이유 |
|---|---|---|
| `app/contracts/analysis_job.py` | `FineNoticeConfirmation`, `ConfirmFineNoticeFieldsRequest/Response` DTO | API 계약 — 서버 게이트 담당자 영역 |
| `backend/chatbot/repositories.py` | `confirm_fine_notice_fields`, `get_fine_notice_confirmation_state`, `AnalysisJobReferenceError` 등 | 저장소/권한 로직 — "HTTP 오류 응답 및 권한 처리" 금지 항목과 동일 성격 |
| `backend/chatbot/views.py` | `analysis_job_fine_notice_confirmation` 뷰 | 지시서가 명시적으로 금지한 파일·영역 |
| `backend/chatbot/urls.py` | `POST /analysis/jobs/<job_id>/fine-notice-confirmation/` 라우트 | 위와 동일 |
| `app/web/FrontendAppShell.jsx`, `apiClient.js`, `styles.css` | `FineNoticeConfirmationPanel` 확인 UI, `confirmFineNoticeFields` 클라이언트 함수, 관련 CSS | 지시서 어디에도 프런트엔드 작업은 없음 — 담당은 "Agent 내부 구현·입출력 품질"까지 |
| `backend/chatbot/test_supervisor_reporting_pipeline.py`, `test/test_consultation_v2_contract.py` | 위 API/프런트엔드에 대응하는 테스트·계약 토큰 | 대응 코드 제거에 따라 함께 제거 |

**부수 발견**: revert 과정에서 `app/web/FrontendAppShell.jsx`의 `confirmCurrentFineNoticeFields` 함수가 dev 머지(`2e552e3`, PR #246 document-type-separation) 도중 닫는 중괄호(`}`) 없이 다음 함수(`copyReportDocumentCard`) 정의와 합쳐져 있었다 — git이 텍스트 충돌로 감지하지 못하고 조용히 깨진 병합이었다. `vite build`를 재실행하지 않아 이 세션에서는 늦게 발견했다. 이번 함수 전체 제거로 자연스럽게 함께 해소됐고, `vite build`로 정상 컴파일을 재확인했다.

## 의도적으로 설계에서 제외한 부분

| 항목 | 이유 |
|---|---|
| Supervisor 실행 계획이 `requires_confirmation`을 보고 `law_ground_search`/`appeal_decision_flow` 실행을 실제로 차단·재개하는 로직 | 서버 게이트 담당자 영역. |
| 확인/수정 API, 확인 UI 패널 | 위 "되돌린 부분" 참고 — 서버 게이트·프런트엔드 담당자 영역으로 판단해 구현을 철회했다. |
| `law_ground_search`, `objection_report_generation` Agent 내부 구현 | 별도 담당자 영역으로 명시됨. |
| `reference_drift_check.py` 결과를 DB에 상시 기록하는 파이프라인 | gap report가 요구한 전체 범위지만, 스키마 변경(신규 컬럼)이 필요해 "축소판"(기존 `created_at`만 노출)으로 좁혔다. |
| OCR 모델 비용·성능 지표화, 악조건 평가셋 구축, 문서 유형별 정확도 측정 | 코드가 아닌 데이터/평가 작업이라 Agent 구현 범위 밖. |
| `case_repository.py`, 케이스 분석 시작 API, `supervisor_routing_policy.v1.json` | 작업 분담 지시서의 절대 수정 금지 목록. |

## 서버 게이트 담당자에게 필요한 계약 (지시서의 "최종 보고 형식" 요청 항목)

지시서는 코드 작업 후 "내 서버 게이트 작업에 필요한 입력 계약 또는 주의사항"을 보고하라고 명시했다. API/UI는 구현하지 않았지만, Agent가 이미 아래 계약을 만족하므로 서버 게이트 쪽에서 그대로 소비할 수 있다.

- `fine_notice_analysis`의 `agent_results["fine_notice_analysis"]["structured_result"]`에 `requires_confirmation: bool`, `unconfirmed_fields: list[str]`가 항상 포함된다.
- `appeal_decision_flow`가 `fine_notice_analysis`의 `structured_result`를 상위 컨텍스트로 받으면(`AppealJudgmentState`에 동일 필드 선언됨), `agent_results["appeal_judgment"]["structured_result"]`에도 동일 필드가 그대로 전달되고, `next_actions`에 "OCR 추출 정보 확인 필요" 항목이 조건부로 추가된다.
- 서버 게이트가 이 값을 읽어 확인 API/UI를 구현하거나, `law_ground_search`/`appeal_decision_flow` 실행 전 차단 로직을 붙이면 된다 — Agent 쪽은 값만 정확히 흘려보낼 뿐 아무것도 차단하지 않는다.

## 알려진 제한사항

- **법령 최신성 경고가 조건부가 아님**: disclaimer는 수집일을 항상 노출할 뿐, 실제로 얼마나 오래됐는지·드리프트가 발생했는지에 따라 경고 강도를 바꾸지는 않는다.

## 작업 중 발견해 함께 수정한 기존 버그

- `test/integration/test_appeal_decision_flow_graph.py`의 `TestSuccessBranch` 테스트 1개가 이번 세션 이전(베이스 커밋 `0e7f746`)부터 이미 실패 상태였다. 이전 PR #244 커밋이 `next_actions` 문구를 "재호출 시 정확한 판정 가능"에서 "다시 질문해주세요"로 바꾸면서 이 통합 테스트를 갱신하지 않은 게 원인. `git stash`로 베이스 커밋에서도 동일하게 실패함을 확인 후, 새 문구에 맞게 어서션을 수정했다.
- 위 "부수 발견" 항목의 dev 머지로 인한 프런트엔드 빌드 깨짐(닫는 중괄호 누락)도 이번에 함께 해소됐다.

## 테스트 결과 (최종, revert 이후)

- `test/unit/test_fine_notice_evaluator.py` + `test/unit/test_appeal_decision_flow_nodes.py` + `test/test_agent_node_service.py` + `test/integration/test_appeal_decision_flow_graph.py` + `test/test_consultation_v2_contract.py` + `test/test_privacy_boundaries.py` + `test/test_pii_masking.py`: **242 passed**
- 프런트엔드: `vite build` 성공 (revert 이후 재확인, 병합으로 깨졌던 함수도 함께 해소)

## PR #244 리뷰 코멘트 요구사항 대조

리뷰(hi20260204-maker, 2026-07-20T05:42:04Z, PR #244)가 요구한 5가지 항목을 현재 커밋(`8525619`) 기준으로 대조하면 다음과 같다.

| 리뷰 요구사항 | 현재 상태 |
|---|---|
| OCR 결과(금액·기한·처분번호) 확인/수정 UI·API 계약 | ❌ 미반영 — 구현했다가 되돌림. 같은 리뷰어가 작성한 별도 작업분담 문서(`docs/architecture/프롬프트.txt`, 이후 삭제됨)에서 이건 본인("서버 게이트") 담당으로 명시돼 있어 철회함 |
| 확인 전 법령 검색·이의신청 생성 진행을 막는 서버 측 게이트 | ❌ 미반영 — 애초부터 서버 게이트 담당자 영역으로 범위 제외 |
| 확인 후에만 재개하는 상태 전이 + E2E 테스트 | ❌ 미반영 — 위 두 항목에 종속, 서버 게이트 없이는 만들 수 없음 |
| 저신뢰도/누락 필드의 재촬영·직접 입력 흐름 및 테스트 | ❌ 미반영 — 직접 입력 UI는 되돌린 프런트엔드 패널에 있었음 |
| 법령 최신성을 고정 연도가 아닌 데이터 기준일·마지막 검증일 기반으로 표시 | ✅ 반영됨 — `law_reference_verified_at`(`law_chunks.created_at` 기반)이 disclaimer에 조건부로 노출 |

**결론**: 5개 중 1개(법령 최신성)만 이번 작업으로 실제 반영됐다. 나머지 4개(확인 UI/API/게이트/재개 로직)는 리뷰어 본인이 작성한 작업분담 문서에서 "서버 게이트 담당자(리뷰어 자신) 몫"으로 명시한 항목이라 이번 커밋에는 의도적으로 빠져 있다. 마스터 체크리스트 D-1("중요 필드 사용자 확인 단계")은 여전히 미완료이며, Agent 쪽은 필요한 데이터(`requires_confirmation`/`unconfirmed_fields`)를 정확히 흘려보내고 있으므로 리뷰어가 자기 몫의 API/UI/게이트를 만들 때 위 "서버 게이트 담당자에게 필요한 계약" 절의 값을 바로 소비하면 된다.

## 체크리스트 반영 제안

`docs/ops/project-readiness-master-checklist.md`의 아래 항목은 **완료(`[x]`)가 아니라 부분 구현(`[~]`)으로 표기**하는 것을 제안한다. 실제 체크리스트 파일 수정은 하지 않았다.

- B, 85행(제출기한 강조) / 86행(판단 불가 안내 표준화): 이미 완료(이전 커밋).
- C-2, 107행(기준일·최신성 제한사항 표시): `[~]` — 날짜는 노출하지만 조건부 강조는 없음.
- D-1, 120행(중요 필드 사용자 확인 단계): `[~]` — Agent 내부에서 값은 정확히 흘려보내지만(위 "서버 게이트 담당자에게 필요한 계약" 참고), 실제 확인 UI/API와 "판단 로직으로 넘어가기 전" 차단은 서버 게이트 담당자 몫으로 남아 있다.
