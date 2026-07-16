# 비-Supervisor Agent 구현 이슈 기록

작성일: 2026-07-16

검토 브랜치: `feat-agent-flow-security-review`

처리 원칙: 이번 단계에서는 Supervisor와 내부 제어 노드만 수정한다. 아래 업무 Agent는
코드를 추가로 수정하지 않고 코드 리뷰 후 각 담당 영역에서 처리한다.

## 1. 담당과 구현 이력 판정 기준

- 업무 담당: `docs/wbs-owner-deliverable-plan.md`
- 실제 구현 이력: `origin/dev`의 경로별 Git 작성자 집계
- Supervisor 통합 코드는 업무 Agent 구현과 분리한다.
- 현재 작업 트리에 이미 존재하던 미커밋 변경은 작성자를 Git으로 확정할 수 없으므로 이 문서에서
  담당자 변경 근거로 사용하지 않는다.

## 2. Agent별 보류 이슈

| Agent/기능 | WBS 담당 | Git 이력상 주요 구현자 | 확인된 문제 | 이번 단계 처리 | 권장 우선순위 |
|---|---|---|---|---|---|
| `fine_notice_analysis` | 필주 `workzion2` | kama42kanne, LeeHyerim, 일부 LeeJaekang | 첨부가 없는 절차 질문과 실제 고지서 OCR 분석의 입력 조건이 Agent 내부 계약에서 완전히 분리되지 않음. OCR 근거에 첨부 ID·저장소 참조·원본 해시가 일관되게 남는지 추가 확인 필요 | Supervisor가 고지서 첨부가 있을 때만 분석 플랜에 넣도록 라우팅을 분리. Agent 코드는 보류 | P1 |
| `law_ground_search` | 동혁 `techshin31` | LeeHyerim, techshin31 | `matched_laws`/과거 별칭, 검색 품질, 시행일·출처 URL의 모든 실행 경로 일관성 검토 필요. 검색 결과가 없을 때 `partial/failed`로 닫히는지 실제 백엔드별 검증 필요 | 이번 단계 추가 수정 없음. Supervisor 결과 검증에서 근거 없는 성공 결과를 거절 | P1 |
| `appeal_decision_flow` | 필주 `workzion2` | kama42kanne 중심, LeeHyerim, 일부 LeeJaekang | 유효한 고지서·사용자 이의 사유·충분한 법령 근거·기한 정보가 모두 없을 때 `input_required/blocked`로 닫히는지 도메인 테스트 부족. 일반 테스트가 adapter mock 위주라 실제 그래프 연결이 오해될 수 있음 | 이번 단계 추가 수정 없음. Supervisor report gate가 검증 실패 시 보고서 호출을 차단 | P1 |
| `text_ml_case_search` | 재강 `leejaegang27` | `ai/agents` wrapper는 LeeHyerim 중심, ETL은 LeeHyerim·LeeJaekang | 불완전한 대화 문장 대신 확정된 사고 사실 버전을 입력받는 계약 필요. 유사사례 저장소가 비어 있을 때 사례 생성 금지, 단일 비율 대신 범위·변동요인 출력 검토 필요 | 이번 단계 추가 수정 없음. Supervisor fact reducer와 case gate까지만 구현 | P1 |
| 교통사고 사실확인원 OCR | 재강 `leejaegang27` 영역 | OCR 구현 LeeJaekang, 마스킹 통합 LeeHyerim | ETL 구현은 있으나 `NODE_REGISTRY`, 운영 adapter, 첨부 목적 기반 실행 플랜에 미등록. 공통 `ocr_evidence` 변환 계약 없음 | 코드 연결 보류 | P1 |
| `vision_media_analysis` | 주희 `ohjuheecode` | 현재 Agent 경로에는 LeeHyerim의 registry/stub 이력만 확인 | registry 상태가 `mock_contract_only`이며 실제 모델·adapter 구현이 없음. capability가 사용자에게 운영 기능처럼 노출되지 않는지 확인 필요 | 신규 구현 보류. Supervisor 사고 초기 상담에서는 호출하지 않음 | P1 |
| `objection_report_generation` | 요청자/QA `hi20260204-maker` | LeeHyerim 중심 | Agent 자체에서도 `document_readiness`, `missing_fields`, `ready_for_docx`를 일관되게 반환하는지 검토 필요. 과태료/사고 보고서 템플릿 경계 확인 필요 | Agent 수정 없이 Supervisor가 명시적 문서 작성 요청 + 검증의 `report_ready=true`일 때만 호출하도록 차단 | P0 계약 리뷰, 구현 P1 |

## 3. 생성형 Agent 연결·테스트 설계 이슈

확인된 상태는 “Agent 연결 실패”가 아니라 “테스트가 실제 연결을 충분히 증명하지 못함”이다.

- non-DL Agent는 실제 sync adapter로 연결돼 있다.
- `execute_mock_*`라는 레거시 이름이 남아 연결 상태를 오해하게 만든다.
- `_run_sync_adapter`를 mock하는 테스트는 배선과 envelope만 검증하며 실제 LangGraph/RAG 진입을
  증명하지 않는다.
- 외부 LLM live 테스트는 API key와 `--run-live`가 모두 필요해 일반 pytest에서 skip된다.

코드 리뷰 후 각 Agent 담당 범위에서 다음 계층을 분리한다.

1. contract unit: provider/저장소 port를 대체하고 분기와 스키마 검증
2. local adapter integration: adapter를 mock하지 않고 실제 graph와 로컬 port 진입 검증
3. live smoke: secret이 있는 별도 CI에서만 실행

## 4. 후속 구현 수용 기준

각 업무 Agent 수정 PR은 최소한 다음을 포함해야 한다.

- 입력 필수조건과 `input_required/blocked` 반환 테스트
- 성공·부분 성공·실패 출력 envelope 테스트
- 근거가 없을 때 결과를 생성하지 않는 fail-closed 테스트
- Supervisor adapter를 mock하지 않는 로컬 통합 테스트 최소 1개
- 모델명, timeout, index, credential, 저장소 주소의 코드 내 임의 기본값 제거
- 담당 Agent 외 공통 Supervisor·보안·DB 코드는 별도 커밋 또는 별도 PR로 분리

## 5. 이번 Supervisor 변경과의 경계

이번 단계에서 구현한 것은 다음 공통 제어 기능뿐이다.

- 일반 절차 질문과 고지서 첨부 분석 라우팅 분리
- 사고 후속 답변을 사실 상태로 병합하고 충돌·누락 계산
- 사건 전환 조건을 판단하되 자동으로 Case를 생성하지 않는 gate
- 업무 Agent 결과의 근거·상태·보고서 준비도 검증
- 검증에서 승인한 결과만 최종 사용자 응답으로 병합
- `report_ready=false`이면 보고서 Agent 호출 차단

따라서 이 문서의 업무 Agent 이슈는 해결 완료로 표시하지 않는다.
