# 문서 공간

이 폴더는 프로젝트 기획, 구현 기준, API 초안, 이슈별 상세 기준, 리스크, 운영, QA, 배포 준비성 문서를 관리한다.

## 하위 폴더 역할

| 폴더 | 역할 |
|---|---|
| `architecture/` | 폴더 구조, 시스템 경계, 데이터 흐름 문서를 둔다. |
| `api/` | API 후보, request/response 계약, endpoint 초안을 둔다. |
| `issues/` | GitHub Issue별 구현 기준과 검증 기준을 둔다. |
| `risks/` | 요구사항 gap, 리스크, guardrail, 보류 항목을 둔다. |
| `assets/` | 문서용 이미지, 화면설계 자료, 설명용 정적 자산을 둔다. |

## 핵심 문서

| 문서 | 목적 |
|---|---|
| `wbs-owner-deliverable-plan.md` | WBS, 이슈, 담당자 재배정 기준 |
| `2026-06-25-meeting-action-summary.md` | 2026-06-25 회의 후속 액션과 챗봇/RAG/리포트 누락 금지 흐름 |
| `pm-api-json-schema-spec-2026-06-23.md` | Agent/Supervisor/API JSON schema 초안과 화면 표시 계약 |
| `api/openapi-v0.yaml` | OpenAPI 3.2.0 ver0 API 계약 원본 |
| `api/openapi-v0-distribution-guide.md` | 팀원별 OpenAPI v0 확인 순서와 구현 금지 항목 |
| `api/openapi-v0-notes.md` | PDF, 마크다운, 현재 구현 차이와 확정/검토 기준 |
| `api/openapi-persona-hi20260204-maker-2026-06-29.md` | `hi20260204-maker` persona 기준 confirmed-only 1차 실행 범위 |
| `architecture/auth-session-policy-2026-06-28.md` | 로그인, 비회원, auth session, 채팅 session 분리 정책 |
| `architecture/history-event-design-2026-06-28.md` | 히스토리 이벤트 저장, 민감도, 애프터서비스 설계 초안 |
| `schema-ready-implementation-checklist-2026-06-24.md` | schema 수신 직후 mock data, 화면 상태, 검증 착수 기준 |
| `screen-design-specification.md` | 화면설계서 |
| `screen-design-ui-ux-flow-guide.md` | UI/UX 흐름 설명 |
| `deployment-readiness-review-2026-06-22.md` | 배포 준비성 검토 보고서 |
| `hi20260204-maker-solo-execution-close-check-2026-06-22.md` | PM 단독 처리와 close 가능성 점검 |
| `hi20260204-maker-collaboration-dependencies-2026-06-22.md` | 협업 의존성 상세 보고서 |

## 흐름도 자산

| 경로 | 목적 |
|---|---|
| `assets/flowcharts/project-overall-flow-2026-06-25.svg` | 프로젝트 전체 흐름도 원문 |
| `assets/flowcharts/user-screen-flow-2026-06-25.svg` | 사용자 화면 흐름도 원문 |
| `assets/flowcharts/internal-processing-flow-2026-06-25.svg` | 내부 처리 흐름도 원문 |

## 운영 문서

| 문서 | 목적 |
|---|---|
| `ops/release-checklist.md` | 운영 배포 전 승인 체크리스트 |
| `ops/rollback-plan.md` | 롤백 기준과 절차 |
| `ops/incident-response.md` | 장애와 보안 사고 대응 |
| `ops/secret-management.md` | 비밀정보 관리 기준 |
| `ops/backup-and-recovery.md` | 백업과 복구 기준 |

## 작성 원칙

- 구현자는 문서에 확정된 범위만 구현한다.
- 확정되지 않은 항목은 `검증 필요` 또는 `보류`로 분리한다.
- 생성 PDF, 엑셀, 임시 산출물은 기본 소스 문서와 구분한다.
- 이슈와 문서의 책임 범위가 충돌하면 구현 전에 확인한다.
- 확인되지 않은 기능, 모델, API는 확정처럼 기록하지 않는다.
- 개인정보, 법률 판단, 과실비율 단정, 제출 성공 보장 표현은 금지한다.
- 운영 배포 가능 여부는 실행 여부가 아니라 탐지, 피해 제한, 복구, 추적 가능성으로 판단한다.
