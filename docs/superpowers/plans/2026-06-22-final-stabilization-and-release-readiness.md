# Final Stabilization And Release Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `#43 chore-final-stabilization-and-release-readiness`에서 표준 운영 준비형 기준의 배포 준비성 문서, 운영 절차 문서, 정적 산출물 검증 테스트를 만든다.

**Architecture:** 기능 구현을 새로 확정하지 않고, 현재 저장소의 문서와 정적 HTML 산출물을 운영 배포 관점에서 검토한다. 운영 문서는 `docs/ops/`에 책임별로 분리하고, 배포 준비성 검토 보고서는 `docs/deployment-readiness-review-2026-06-22.md`에 둔다. 검증은 Python 표준 라이브러리 기반 pytest로 문서 존재, 필수 섹션, 정적 HTML 인코딩, 비밀정보 노출 패턴을 확인한다.

**Tech Stack:** Markdown, HTML, Python stdlib, pytest, GitHub Issues.

---

## Decision Constraints

- 선택된 방향은 **B. 표준 운영 준비형**이다.
- 최소 운영형이나 고신뢰 운영형을 구현 방향으로 섞지 않는다.
- 실제 Google 로그인, Agent, RAG, API endpoint, 모델 선택은 확정하지 않는다.
- 팀원 schema 없이 `#22`, `#27`, `#29`, `#40`, `#41`을 완료 처리하지 않는다.
- close 후보는 검증 결과 기준으로만 판정한다.

## File Structure

| 파일 | 책임 |
|---|---|
| `docs/deployment-readiness-review-2026-06-22.md` | 첨부 지침 형식에 맞춘 프로젝트 배포 준비성 검토 보고서 |
| `docs/ops/release-checklist.md` | 운영 배포 승인 전 확인 절차 |
| `docs/ops/rollback-plan.md` | 잘못된 배포를 되돌리는 절차와 검증 기준 |
| `docs/ops/incident-response.md` | 장애와 보안 사고 대응 절차 |
| `docs/ops/secret-management.md` | 비밀정보 관리, 교체, 로그 노출 방지 기준 |
| `docs/ops/backup-and-recovery.md` | 백업, 복구, RTO/RPO, 복구 테스트 기준 |
| `docs/README.md` | 새 운영 문서 목록 연결 |
| `test/test_deployment_readiness_artifacts.py` | 배포 준비성 산출물 정적 검증 테스트 |
| `memory.md` | 선택 B와 작업 제약 기록 |

---

### Task 1: Record The Selected Decision

**Files:**
- Modify: `memory.md`

- [ ] **Step 1: Open current memory**

Run:

```powershell
Get-Content -Encoding UTF8 -LiteralPath .\memory.md -Tail 80
```

Expected: 최근 작업 기록을 확인한다.

- [ ] **Step 2: Append decision record**

Add this section near the end of `memory.md`:

```markdown
## 2026-06-22 Decision: #43 표준 운영 준비형

### Options

| 선택 | 방향 | 판정 |
|---|---|---|
| A | 문서·이슈 close 정리형 | 선택하지 않음 |
| B | 표준 운영 준비형 | 선택됨 |
| C | 정적 프론트 MVP 강화형 | 선택하지 않음 |
| D | Agent 계약 골격형 | 선택하지 않음 |

### Decision

사용자는 `B. 표준 운영 준비형`을 선택했다. 작업 대상 이슈는 `#43 chore-final-stabilization-and-release-readiness`이며, 작업 브랜치는 `chore-final-stabilization-and-release-readiness`다.

### Constraints

- 표준 운영 준비형 기준으로 배포 준비성 검토, 운영 절차, 정적 검증 테스트를 먼저 만든다.
- 실제 Google 로그인, Agent, RAG, API endpoint, 모델 선택은 구현하지 않는다.
- 팀원 schema 없이 `#22`, `#27`, `#29`, `#40`, `#41`을 완료 처리하지 않는다.
- close 가능성은 검증 결과와 사용자 승인 후에만 판정한다.
```

- [ ] **Step 3: Verify decision text exists**

Run:

```powershell
Select-String -Path .\memory.md -Pattern "2026-06-22 Decision: #43 표준 운영 준비형","B. 표준 운영 준비형","chore-final-stabilization-and-release-readiness"
```

Expected: 3개 pattern 모두 출력된다.

---

### Task 2: Write Deployment Readiness Review Report

**Files:**
- Create: `docs/deployment-readiness-review-2026-06-22.md`

- [ ] **Step 1: Create the report**

Create `docs/deployment-readiness-review-2026-06-22.md` with this content:

```markdown
# 교통분쟁 AI 서비스 배포 준비성 검토

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-22 |
| 기준 이슈 | `#43 chore-final-stabilization-and-release-readiness` |
| 기준 브랜치 | `chore-final-stabilization-and-release-readiness` |
| 검토 기준 | 범용 시스템·프로그램 배포 준비성 검토 지침 |
| 최종 판단 기준 | 문제가 발생했을 때 이를 발견하고, 피해를 제한하며, 정상 상태로 복구하고, 원인과 책임을 추적할 수 있을 때 운영 배포가 가능하다. |

## 1. 프로젝트 요약

| 항목 | 내용 |
|---|---|
| 시스템 목적 | 교통사고, 과실비율, 과태료·범칙금, 법령 근거, 이의신청서 초안 생성을 지원하는 AI 상담 서비스 |
| 사용자 | 일반 교통분쟁 상담 사용자, 프로젝트 시연 사용자, 운영자 |
| 데이터 민감도 | 개인정보와 사고 자료가 포함될 가능성이 높음 |
| 외부 공개 여부 | 확인 필요 |
| 예상 위험도 | 높음 |
| 현재 운영 준비 수준 | 문서와 정적 HTML 중심이며 운영 배포 준비는 미충족 |

## 2. 최종 판정

**배포 불가**

현재 저장소는 정적 HTML과 문서 산출물 중심이다. 실제 인증, 서버 측 권한 검사, 운영 데이터 보호, 백업·복구, 모니터링, 롤백, 배포 절차가 검증되지 않았으므로 운영 사용자 대상 배포는 불가하다.

## 3. 핵심 판정 근거

- 개인정보와 법률성 판단이 포함될 수 있으나 개인정보 보관·삭제·마스킹 운영 기준이 완성되지 않았다.
- 실제 인증, 서버 측 권한 검사, 관리자 권한 분리 구현이 확인되지 않았다.
- 백업과 복구 절차가 문서화 전이며 복구 테스트도 수행되지 않았다.
- 운영 배포 절차, 롤백 절차, 장애 대응 절차가 아직 저장소에 분리 문서로 존재하지 않았다.
- 자동 테스트는 정적 산출물 검증 수준부터 추가해야 하며, 핵심 기능 테스트는 아직 확인되지 않았다.

## 4. 즉시 배포 차단 항목

| 우선순위 | 차단 항목 | 위험 | 필수 조치 | 검증 방법 |
|---|---|---|---|---|
| P0 | 서버 측 인증·권한 검사 미확인 | 사용자 데이터 무단 접근 | 인증·권한 설계와 테스트 추가 | 권한별 접근 테스트 |
| P0 | 개인정보 처리 기준 미완성 | 개인정보 노출 또는 보관 위반 | 수집·보관·삭제·마스킹 정책 작성 | 개인정보 항목별 점검표 |
| P0 | 백업·복구 절차 미검증 | 데이터 손실 시 복구 불가 | 백업 정책과 복구 테스트 절차 작성 | 복구 테스트 기록 |
| P0 | 롤백 절차 미문서화 | 잘못된 배포 후 정상화 지연 | 앱/문서/DB 변경 롤백 절차 작성 | 롤백 리허설 기록 |
| P1 | 장애 알림과 운영 책임 체계 미확인 | 장애 발견 지연 | 담당자, 연락 경로, 대체 담당자 정의 | 운영 책임표 확인 |

## 5. 배포 전 필수 작업

| 우선순위 | 작업 | 담당 역할 | 완료 기준 | 미완료 시 영향 |
|---|---|---|---|---|
| P0 | 운영 책임자와 대체 담당자 지정 | PM | 담당자, 연락 경로, 승인권자가 문서화됨 | 장애 대응 지연 |
| P0 | 비밀정보 관리 기준 작성 | PM/Backend | 비밀정보가 코드에 없고 교체 절차가 있음 | 토큰·키 노출 |
| P0 | 백업·복구 절차 작성 | Backend/Infra | 백업 대상, 주기, 보관 위치, 복구 방법이 문서화됨 | 데이터 손실 |
| P0 | 롤백 계획 작성 | PM/Infra | 이전 정상 버전 식별과 복구 절차가 있음 | 장애 장기화 |
| P1 | 정적 산출물 검증 테스트 추가 | PM | HTML, 운영 문서, 비밀정보 패턴 테스트 통과 | 산출물 누락 |
| P1 | guardrail 체크리스트 작성 | PM/AI 담당 | 법률 단정, 성공 보장, 과실비율 수치 단정 금지 기준 있음 | 법률·품질 리스크 |

## 6. 영역별 검토 결과

| 검토 영역 | 판정 | 현재 상태 | 문제 | 개선 방법 | 검증 방법 |
|---|---|---|---|---|---|
| 운영 책임 체계 | 확인 불가 | 담당자 이슈 배정은 있으나 장애 담당 체계는 없음 | 장애 대응 주체 불명확 | 운영 책임표 작성 | 책임자/대체자 확인 |
| 소스 코드 및 버전 관리 | 부분 충족 | GitHub 저장소와 이슈가 있음 | 운영 태그와 릴리즈 기준 미정 | 브랜치/태그/릴리즈 절차 작성 | git tag와 릴리즈 문서 확인 |
| 재현 가능한 빌드 및 배포 | 미충족 | 정적 HTML 중심 | 배포 절차와 의존성 고정 없음 | release checklist 작성 | 체크리스트 기반 배포 리허설 |
| 개발·테스트·운영 환경 분리 | 확인 불가 | 환경 구분 문서 없음 | 운영 데이터 보호 불명확 | 환경 분리 정책 작성 | 설정 파일과 배포 환경 점검 |
| 인증 및 권한 관리 | 미충족 | 실제 인증 구현 확인 안 됨 | 사용자 데이터 접근 통제 없음 | 서버 측 권한 검사 설계 | 권한별 테스트 |
| 비밀정보 관리 | 확인 불가 | 코드 내 비밀정보 검증 자동화 없음 | 토큰 노출 가능성 | secret management 문서와 검사 추가 | 정적 패턴 검사 |
| 사용자 입력 및 파일 처리 | 확인 불가 | 고지서/영상 업로드 예정 | 크기·형식·악성 파일 통제 미정 | 파일 검증 정책 작성 | 업로드 검증 테스트 |
| 데이터베이스 및 데이터 무결성 | 확인 불가 | DB 구현 확인 전 | migration/transaction 기준 없음 | DB 변경 절차 작성 | migration dry-run |
| 오류 처리 | 확인 불가 | 실제 서버 오류 처리 없음 | 내부 정보 노출 위험 | 오류 응답 정책 작성 | 실패 케이스 테스트 |
| 로그 및 감사 기록 | 확인 불가 | 로그 정책 없음 | 추적성 부족 | audit log 기준 작성 | 로그 샘플 검토 |
| 모니터링 및 알림 | 미충족 | 모니터링 구성 없음 | 장애 탐지 불가 | 헬스체크와 알림 기준 작성 | 장애 알림 리허설 |
| 백업 및 복구 | 미충족 | 백업 문서 없음 | 데이터 손실 | backup-and-recovery 문서 작성 | 복구 테스트 |
| 롤백 | 미충족 | 롤백 문서 없음 | 잘못된 배포 복구 지연 | rollback-plan 작성 | 롤백 리허설 |
| 외부 서비스 및 API 장애 대응 | 확인 불가 | 외부 API 후보만 있음 | 타임아웃/재시도 정책 없음 | 외부 API 장애 처리 기준 작성 | 장애 mock 테스트 |
| 트래픽 및 악용 방지 | 미충족 | rate limit 기준 없음 | 비용과 장애 확산 | 요청량 제한 정책 작성 | 부하·남용 테스트 |
| 패키지 및 외부 의존성 | 확인 불가 | 의존성 파일 확인 전 | 취약점 관리 불명확 | dependency inventory 작성 | 취약점 검사 |
| 테스트 | 부분 충족 | 정적 검증 테스트 추가 예정 | 핵심 기능 테스트 없음 | smoke/e2e 계획 작성 | pytest와 수동 점검 |
| 개인정보 및 데이터 관리 | 미충족 | 개인정보 가능성 높음 | 보관·삭제 기준 미완성 | data governance 문서 보강 | 개인정보 점검표 |
| 성능 및 용량 | 확인 불가 | 사용자 수와 트래픽 미정 | 용량 계획 없음 | 예상 트래픽 기준 정의 | 부하 테스트 |
| 비용 통제 | 확인 불가 | 외부 API/인프라 비용 미정 | 비용 급증 위험 | 비용 알림 기준 작성 | 비용 알림 확인 |
| 운영 문서 | 부분 충족 | 일부 기획 문서 있음 | 운영 절차 문서 부족 | `docs/ops/` 문서 작성 | 문서 링크 검증 |

## 7. 운영 방안 비교

### 방안 01: 최소 운영형

- 특징: 소수 내부 사용자와 낮은 민감도 데이터에 맞춘 빠른 운영 방식
- 장점: 구축이 빠르고 비용이 낮음
- 단점: 개인정보와 법률성 판단 리스크를 감당하기 어렵다.
- 필요한 추가 작업: 기본 인증, 로그, 백업, 수동 롤백
- 실무적 관점의 제언: 이 프로젝트에는 권장하지 않는다.

### 방안 02: 표준 운영형

- 특징: 실제 사용자와 개인정보 가능성이 있는 서비스의 기본 운영 방식
- 장점: 보안, 복구, 변경 추적, 장애 탐지를 현실적인 비용으로 확보한다.
- 단점: 운영 문서, 테스트, 모니터링, 승인 절차를 추가해야 한다.
- 필요한 추가 작업: 운영 문서, 자동 테스트, 비밀정보 검사, 백업·복구, 롤백, 장애 대응
- 실무적 관점의 제언: 현재 프로젝트의 1순위 선택이다.

### 방안 03: 고신뢰 운영형

- 특징: 결제, 금융, 의료, 공공, 대규모 개인정보 시스템 수준의 운영 방식
- 장점: 장애와 보안 사고 피해를 크게 낮춘다.
- 단점: 비용과 복잡도가 높고 현재 MVP 단계에는 과하다.
- 필요한 추가 작업: 이중화, 재해복구, 침투 테스트, RTO/RPO, 변경 이중 승인
- 실무적 관점의 제언: 대규모 외부 공개 또는 민감정보 확대 시 재검토한다.

## 8. 최종 추천

- 1순위: 표준 운영형
- 추천 이유: 개인정보 가능성, 법률성 판단, 파일 업로드, 외부 API 가능성이 있어 최소 운영형으로는 위험하다.
- 적용 조건: 운영 책임, 비밀정보, 테스트, 백업, 롤백, 장애 대응 문서를 먼저 갖춘다.
- 예상 리스크: 실제 백엔드와 데이터베이스가 생기면 권한, 로그, 복구 테스트를 추가로 검증해야 한다.
- 2순위: 고신뢰 운영형
- 2순위를 선택할 수 있는 조건: 외부 공개, 대규모 사용자, 공공/금융 수준 책임, 대량 개인정보 처리로 범위가 확대되는 경우

## 9. 권장 배포 흐름

소스 코드 변경
→ 코드 검토
→ 자동 테스트
→ 보안 및 비밀정보 검사
→ 테스트 환경 배포
→ 핵심 기능 점검
→ 운영 배포 승인
→ 운영 배포
→ 상태 확인
→ 오류·성능 모니터링
→ 문제 발생 시 롤백

현재 저장소에는 실제 배포 대상 서버와 운영 환경이 확인되지 않았으므로 테스트 환경 배포 이후 단계는 `확인 필요`로 둔다.

## 10. 최종 배포 승인 체크리스트

- [ ] 운영 책임자가 지정되어 있다.
- [ ] 운영 중인 코드 버전을 확인할 수 있다.
- [ ] 비밀정보가 코드와 클라이언트에 포함되어 있지 않다.
- [ ] 사용자와 관리자 권한이 서버에서 검증된다.
- [ ] 개발·테스트·운영 환경이 구분되어 있다.
- [ ] 핵심 기능 테스트가 완료되었다.
- [ ] 오류와 중요 작업이 로그에 기록된다.
- [ ] 장애 알림을 받을 수 있다.
- [ ] 데이터 백업이 존재한다.
- [ ] 실제 복구 테스트를 완료했다.
- [ ] 이전 버전으로 롤백할 수 있다.
- [ ] 외부 API 장애와 타임아웃을 처리한다.
- [ ] 과도한 요청과 비용 증가를 제한한다.
- [ ] 개인정보의 수집·보관·삭제 기준이 정의되어 있다.
- [ ] 배포 및 장애 대응 절차가 문서화되어 있다.
```

- [ ] **Step 2: Verify required report sections**

Run:

```powershell
Select-String -Path .\docs\deployment-readiness-review-2026-06-22.md -Pattern "프로젝트 요약","최종 판정","즉시 배포 차단 항목","영역별 검토 결과","최종 추천","최종 배포 승인 체크리스트"
```

Expected: all 6 section names are printed.

---

### Task 3: Create Operations Documents

**Files:**
- Create: `docs/ops/release-checklist.md`
- Create: `docs/ops/rollback-plan.md`
- Create: `docs/ops/incident-response.md`
- Create: `docs/ops/secret-management.md`
- Create: `docs/ops/backup-and-recovery.md`

- [ ] **Step 1: Create `docs/ops/release-checklist.md`**

```markdown
# 운영 배포 체크리스트

| 항목 | 내용 |
|---|---|
| 기준 이슈 | `#43 chore-final-stabilization-and-release-readiness` |
| 적용 범위 | 표준 운영형 배포 준비 |
| 승인 원칙 | 문제가 발생했을 때 탐지, 피해 제한, 복구, 추적이 가능해야 한다. |

## 1. 배포 전 P0 확인

- [ ] 운영 책임자와 대체 담당자가 지정되어 있다.
- [ ] 배포 대상 브랜치, commit, tag를 식별할 수 있다.
- [ ] 비밀정보가 코드와 클라이언트에 포함되어 있지 않다.
- [ ] 사용자 인증과 서버 측 권한 검사 기준이 문서화되어 있다.
- [ ] 개인정보 수집, 보관, 삭제, 마스킹 기준이 문서화되어 있다.
- [ ] 백업 대상과 복구 절차가 문서화되어 있다.
- [ ] 롤백 절차가 문서화되어 있다.

## 2. 배포 전 P1 확인

- [ ] 자동 테스트가 통과했다.
- [ ] 정적 HTML 산출물이 UTF-8로 저장되어 있다.
- [ ] 운영 문서가 `docs/ops/`에 존재한다.
- [ ] 장애 대응 절차가 문서화되어 있다.
- [ ] 외부 API 장애 시 사용자 안내와 timeout 기준이 문서화되어 있다.
- [ ] 과도한 요청과 비용 증가를 제한하는 계획이 있다.

## 3. 배포 승인 기록

| 항목 | 기록 |
|---|---|
| 배포 요청자 | 확인 필요 |
| 검토자 | 확인 필요 |
| 승인자 | 확인 필요 |
| 배포 commit | 확인 필요 |
| 배포 시간 | 확인 필요 |
| 롤백 기준 버전 | 확인 필요 |

## 4. 배포 후 smoke 점검

- [ ] 진입 화면이 열린다.
- [ ] 챗봇 화면 영역이 표시된다.
- [ ] 과태료·범칙금 결과 영역이 표시된다.
- [ ] 과실비율 결과 영역이 표시된다.
- [ ] 마이페이지 또는 내 사건 영역이 표시된다.
- [ ] 오류가 사용자에게 내부 stack trace로 노출되지 않는다.
```

- [ ] **Step 2: Create `docs/ops/rollback-plan.md`**

```markdown
# 롤백 계획

| 항목 | 내용 |
|---|---|
| 기준 이슈 | `#43 chore-final-stabilization-and-release-readiness` |
| 목적 | 잘못된 배포 후 이전 정상 상태로 되돌리는 절차를 정의한다. |

## 1. 롤백 트리거

- 배포 후 진입 화면이 열리지 않는다.
- 핵심 정적 산출물이 누락된다.
- 비밀정보가 화면, 로그, 저장소에 노출된다.
- 개인정보가 마스킹 없이 사용자 화면에 노출된다.
- 데이터 삭제 또는 데이터 손상이 의심된다.
- 장애 담당자가 문제를 30분 안에 제한하지 못한다.

## 2. 앱 롤백 절차

1. 현재 배포 commit을 기록한다.
2. 이전 정상 commit 또는 tag를 확인한다.
3. 신규 배포를 중지한다.
4. 이전 정상 commit 또는 tag로 재배포한다.
5. smoke 점검을 수행한다.
6. 장애 이슈에 원인, 영향 범위, 복구 시간을 기록한다.

## 3. 문서 롤백 절차

1. 잘못된 문서 변경 파일을 확인한다.
2. 이전 정상 commit의 문서 내용을 비교한다.
3. `git revert` 또는 별도 수정 commit으로 복구한다.
4. 변경 이력을 남긴다.

## 4. 데이터베이스 롤백 기준

현재 저장소에서 운영 데이터베이스와 migration 절차는 확인되지 않았다. DB가 추가되면 아래 항목을 반드시 보강한다.

- migration ID
- forward migration 절차
- backward migration 절차
- rollback 불가 migration 식별
- 데이터 손실 가능성
- 백업 복구 절차

## 5. 롤백 검증

- [ ] 이전 정상 버전 식별 가능
- [ ] smoke 점검 완료
- [ ] 장애 이슈 기록 완료
- [ ] 사용자 영향 범위 기록 완료
```

- [ ] **Step 3: Create `docs/ops/incident-response.md`**

```markdown
# 장애 및 보안 사고 대응 절차

| 항목 | 내용 |
|---|---|
| 기준 이슈 | `#43 chore-final-stabilization-and-release-readiness` |
| 목적 | 장애와 보안 사고 발생 시 탐지, 제한, 복구, 추적 절차를 정의한다. |

## 1. 사고 등급

| 등급 | 기준 | 대응 시간 |
|---|---|---|
| SEV-1 | 개인정보 노출, 인증 우회, 데이터 손상, 전체 장애 | 즉시 |
| SEV-2 | 핵심 기능 장애, 외부 API 장애, 일부 사용자 영향 | 1시간 이내 |
| SEV-3 | 문서 오류, 일부 화면 오류, 비핵심 기능 문제 | 영업일 기준 1일 이내 |

## 2. 최초 대응

1. 사고 발견 시간을 기록한다.
2. 영향 범위를 확인한다.
3. 신규 배포 또는 위험 작업을 중지한다.
4. 담당자와 대체 담당자에게 알린다.
5. 사용자 영향이 있으면 임시 안내 문구를 준비한다.

## 3. 피해 제한

- 비밀정보 노출 시 해당 키를 즉시 폐기하고 재발급한다.
- 개인정보 노출 시 노출 범위와 대상 데이터를 기록한다.
- 외부 API 장애 시 timeout과 사용자 안내를 우선 적용한다.
- 잘못된 배포로 판단되면 롤백 절차를 실행한다.

## 4. 복구 후 기록

| 항목 | 기록 내용 |
|---|---|
| 사고 시작 시간 | 확인 필요 |
| 탐지 경로 | 확인 필요 |
| 영향 범위 | 확인 필요 |
| 원인 | 확인 필요 |
| 복구 조치 | 확인 필요 |
| 재발 방지 | 확인 필요 |

## 5. 금지 사항

- 원인을 확인하지 않고 완료 처리하지 않는다.
- 사용자에게 내부 stack trace, 서버 경로, token, SQL 문장을 노출하지 않는다.
- 개인정보 노출 가능성을 축소 보고하지 않는다.
```

- [ ] **Step 4: Create `docs/ops/secret-management.md`**

```markdown
# 비밀정보 관리 기준

| 항목 | 내용 |
|---|---|
| 기준 이슈 | `#43 chore-final-stabilization-and-release-readiness` |
| 대상 | API key, DB password, token, OAuth secret, 인증서 |

## 1. 저장 원칙

- 비밀정보는 소스 코드, Markdown, HTML, 클라이언트 JavaScript에 저장하지 않는다.
- 로컬 개발은 환경변수 또는 로컬 전용 `.env`를 사용한다.
- `.env` 파일은 Git 추적 대상에 포함하지 않는다.
- 배포 환경에서는 환경별 secret store 또는 배포 플랫폼 secret 기능을 사용한다.

## 2. 로그 원칙

- 요청 header의 `Authorization`, `Cookie`, token 값은 로그에 남기지 않는다.
- 오류 메시지에는 비밀정보, 서버 경로, DB 주소를 포함하지 않는다.
- 사용자에게는 일반 오류 메시지를 제공하고 상세 오류는 내부 로그에만 기록한다.

## 3. 교체 절차

1. 노출 또는 교체 대상 secret을 식별한다.
2. 기존 secret을 폐기한다.
3. 새 secret을 발급한다.
4. 배포 환경에 새 secret을 등록한다.
5. smoke 점검을 수행한다.
6. 교체 시간을 사고 기록 또는 변경 기록에 남긴다.

## 4. 금지 패턴

- `password = "..."` 형태의 실제 비밀번호
- `api_key = "..."` 형태의 실제 API 키
- `token = "..."` 형태의 실제 token
- 클라이언트 HTML/JS에 포함된 OAuth secret

## 5. 검증

- [ ] 저장소 정적 검사에서 secret 패턴이 발견되지 않는다.
- [ ] 배포 환경 secret은 코드와 분리되어 있다.
- [ ] secret 교체 절차가 문서화되어 있다.
```

- [ ] **Step 5: Create `docs/ops/backup-and-recovery.md`**

```markdown
# 백업 및 복구 기준

| 항목 | 내용 |
|---|---|
| 기준 이슈 | `#43 chore-final-stabilization-and-release-readiness` |
| 목적 | 중요 데이터 손실 시 복구 가능한 상태를 만든다. |

## 1. 백업 대상

현재 저장소 기준 실제 운영 데이터베이스는 확인되지 않았다. 운영 데이터베이스와 파일 저장소가 추가되면 아래 대상을 백업한다.

- 사용자 계정 데이터
- 상담 세션과 메시지
- 업로드 파일 metadata
- 리포트와 이의신청서 초안
- 감사 로그
- 운영 설정

## 2. 백업 정책

| 항목 | 기준 |
|---|---|
| 주기 | 운영 전 결정 필요 |
| 보관 기간 | 운영 전 결정 필요 |
| 보관 위치 | 운영 시스템과 분리 |
| 접근 권한 | 운영 담당자와 대체 담당자로 제한 |
| 암호화 | 개인정보 포함 시 필수 |

## 3. 복구 절차

1. 장애 또는 데이터 손상 범위를 확인한다.
2. 복구 기준 시점을 선택한다.
3. 백업 파일의 무결성을 확인한다.
4. 테스트 환경에서 먼저 복구한다.
5. smoke 점검을 수행한다.
6. 운영 복구를 승인받는다.
7. 운영에 복구한다.
8. 복구 결과와 데이터 손실 범위를 기록한다.

## 4. RTO/RPO

| 항목 | 현재 기준 |
|---|---|
| RTO | 운영 전 결정 필요 |
| RPO | 운영 전 결정 필요 |

RTO/RPO가 정의되지 않은 상태에서는 운영 배포를 승인하지 않는다.

## 5. 검증

- [ ] 백업 파일이 생성된다.
- [ ] 백업 파일 접근 권한이 제한되어 있다.
- [ ] 테스트 환경 복구가 성공한다.
- [ ] 복구 후 smoke 점검이 통과한다.
```

- [ ] **Step 6: Verify operations documents**

Run:

```powershell
Test-Path .\docs\ops\release-checklist.md
Test-Path .\docs\ops\rollback-plan.md
Test-Path .\docs\ops\incident-response.md
Test-Path .\docs\ops\secret-management.md
Test-Path .\docs\ops\backup-and-recovery.md
```

Expected: five `True` lines.

---

### Task 4: Update Docs Index

**Files:**
- Modify: `docs/README.md`

- [ ] **Step 1: Replace docs README content**

Replace `docs/README.md` with:

```markdown
# 문서 공간

이 폴더는 프로젝트 기획, 운영, QA, 배포 준비성 문서를 관리한다.

## 핵심 문서

| 문서 | 목적 |
|---|---|
| `wbs-owner-deliverable-plan.md` | WBS, 이슈, 담당자 재배정 기준 |
| `screen-design-specification.md` | 화면설계서 |
| `screen-design-ui-ux-flow-guide.md` | UI/UX 흐름 설명 |
| `deployment-readiness-review-2026-06-22.md` | 배포 준비성 검토 보고서 |
| `hi20260204-maker-solo-execution-close-check-2026-06-22.md` | PM 단독 처리와 close 가능성 점검 |
| `hi20260204-maker-collaboration-dependencies-2026-06-22.md` | 협업 의존성 상세 보고서 |

## 운영 문서

| 문서 | 목적 |
|---|---|
| `ops/release-checklist.md` | 운영 배포 전 승인 체크리스트 |
| `ops/rollback-plan.md` | 롤백 기준과 절차 |
| `ops/incident-response.md` | 장애와 보안 사고 대응 |
| `ops/secret-management.md` | 비밀정보 관리 기준 |
| `ops/backup-and-recovery.md` | 백업과 복구 기준 |

## 작성 원칙

- 확인되지 않은 기능, 모델, API는 확정처럼 기록하지 않는다.
- 개인정보, 법률 판단, 과실비율 단정, 제출 성공 보장 표현은 금지한다.
- 운영 배포 가능 여부는 실행 여부가 아니라 탐지, 피해 제한, 복구, 추적 가능성으로 판단한다.
```

- [ ] **Step 2: Verify docs README links**

Run:

```powershell
Select-String -Path .\docs\README.md -Pattern "deployment-readiness-review-2026-06-22.md","ops/release-checklist.md","ops/rollback-plan.md","ops/incident-response.md","ops/secret-management.md","ops/backup-and-recovery.md"
```

Expected: all 6 document paths are printed.

---

### Task 5: Add Static Readiness Tests

**Files:**
- Create: `test/test_deployment_readiness_artifacts.py`

- [ ] **Step 1: Create static tests**

Create `test/test_deployment_readiness_artifacts.py`:

```python
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


REQUIRED_DOCS = [
    ROOT / "docs" / "deployment-readiness-review-2026-06-22.md",
    ROOT / "docs" / "ops" / "release-checklist.md",
    ROOT / "docs" / "ops" / "rollback-plan.md",
    ROOT / "docs" / "ops" / "incident-response.md",
    ROOT / "docs" / "ops" / "secret-management.md",
    ROOT / "docs" / "ops" / "backup-and-recovery.md",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_required_operations_documents_exist():
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_DOCS if not path.exists()]
    assert missing == []


def test_deployment_readiness_review_has_required_sections():
    content = read_text(ROOT / "docs" / "deployment-readiness-review-2026-06-22.md")
    required_sections = [
        "## 1. 프로젝트 요약",
        "## 2. 최종 판정",
        "## 4. 즉시 배포 차단 항목",
        "## 6. 영역별 검토 결과",
        "## 8. 최종 추천",
        "## 10. 최종 배포 승인 체크리스트",
    ]
    missing = [section for section in required_sections if section not in content]
    assert missing == []


def test_release_readiness_recommends_standard_operations():
    content = read_text(ROOT / "docs" / "deployment-readiness-review-2026-06-22.md")
    assert "**배포 불가**" in content
    assert "1순위: 표준 운영형" in content
    assert "최소 운영형" in content
    assert "고신뢰 운영형" in content


def test_static_mvp_html_is_utf8_korean_service_screen():
    html = read_text(ROOT / "app" / "screen-design-mvp-flow.html")
    assert '<meta charset="UTF-8">' in html
    assert 'lang="ko"' in html
    assert "교통분쟁 AI" in html


def test_secret_management_document_defines_rotation_and_logging_rules():
    content = read_text(ROOT / "docs" / "ops" / "secret-management.md")
    assert "## 2. 로그 원칙" in content
    assert "## 3. 교체 절차" in content
    assert "Authorization" in content
    assert "Cookie" in content


def test_repository_text_files_do_not_contain_obvious_secret_assignments():
    scanned_suffixes = {".md", ".py", ".html", ".txt", ".yml", ".yaml", ".json"}
    excluded_parts = {".git", ".venv", ".pytest_cache", ".worktrees", "assets"}
    secret_pattern = re.compile(
        r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"\n]{8,}['\"]"
    )

    matches = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in scanned_suffixes:
            continue
        if any(part in excluded_parts for part in path.parts):
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for match in secret_pattern.finditer(content):
            matches.append(f"{path.relative_to(ROOT)}:{match.group(1)}")

    assert matches == []
```

- [ ] **Step 2: Run static readiness tests**

Run:

```powershell
C:\Python314\python.exe -m pytest test\test_deployment_readiness_artifacts.py -v
```

Expected: 6 tests pass.

---

### Task 6: Update GitHub Issue Comments

**Files:**
- No repository file changes.

- [ ] **Step 1: Add completion comment to `#43`**

Post this comment to `#43`:

```markdown
<!-- pm-standard-ops-readiness-implemented-2026-06-22 -->
### 표준 운영 준비형 산출물 업데이트

- 작업 브랜치: `chore-final-stabilization-and-release-readiness`
- 추가 산출물:
  - `docs/deployment-readiness-review-2026-06-22.md`
  - `docs/ops/release-checklist.md`
  - `docs/ops/rollback-plan.md`
  - `docs/ops/incident-response.md`
  - `docs/ops/secret-management.md`
  - `docs/ops/backup-and-recovery.md`
  - `test/test_deployment_readiness_artifacts.py`
- 판정: 현재 운영 배포는 불가. 표준 운영형을 1순위로 추천.
- close 상태: 문서와 정적 검증 산출물은 진행되었지만 실제 운영 배포 준비 전체 완료는 아니므로 close는 사용자 승인 전 보류.
```

- [ ] **Step 2: Add linked comment to `#13`**

Post this comment to `#13`:

```markdown
<!-- pm-standard-ops-risk-linked-2026-06-22 -->
### 표준 운영 준비형 리스크 연결

`#43`에서 배포 준비성 검토를 진행하며 아래 항목을 운영 리스크로 연결한다.

- 인증·권한 검사 미확인
- 개인정보 처리 기준 미완성
- 백업·복구 절차 미검증
- 롤백 절차 미문서화
- 장애 알림과 운영 책임 체계 미확인

위 항목은 운영 배포 전 P0/P1로 추적한다.
```

- [ ] **Step 3: Verify issue comments**

Run:

```powershell
$headers = @{ Accept = 'application/vnd.github+json'; Authorization = "Bearer $env:GH_TOKEN"; 'X-GitHub-Api-Version' = '2022-11-28' }
$repo = 'SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team'
$checks = @(
  @{ issue = 43; marker = 'pm-standard-ops-readiness-implemented-2026-06-22' },
  @{ issue = 13; marker = 'pm-standard-ops-risk-linked-2026-06-22' }
)
foreach ($check in $checks) {
  $response = Invoke-WebRequest -UseBasicParsing -Uri "https://api.github.com/repos/$repo/issues/$($check.issue)/comments?per_page=100" -Headers $headers
  [pscustomobject]@{
    issue = $check.issue
    marker = $check.marker
    count = ([regex]::Matches([string]$response.Content, [regex]::Escape($check.marker))).Count
  }
}
```

Expected: each marker count is `1`.

---

### Task 7: Final Verification And Close Decision

**Files:**
- Read-only verification.

- [ ] **Step 1: Check working tree**

Run:

```powershell
git status --short --branch
```

Expected: branch is `chore-final-stabilization-and-release-readiness`; only intended files are modified or added.

- [ ] **Step 2: Run all current pytest checks relevant to this work**

Run:

```powershell
C:\Python314\python.exe -m pytest test\test_deployment_readiness_artifacts.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Prepare close recommendation**

Use this close decision:

| 이슈 | 판정 | 이유 |
|---|---|---|
| `#43` | close 보류 | 표준 운영 준비 산출물은 작성되지만 실제 운영 배포 준비 전체가 완료된 것은 아님 |
| `#12` | 조건부 close 가능 | 화면 흐름 문서와 정적 HTML 산출물 범위라면 완료로 볼 수 있음 |
| `#13` | close 보류 | 운영 리스크 추적이 계속 필요 |
| `#40` | close 불가 | 샘플 기반 통합 실행 검증 전 |
| `#41` | close 불가 | 실제 Agent/Supervisor 출력 guardrail 검증 전 |

- [ ] **Step 4: Commit**

Run:

```powershell
git add memory.md docs/README.md docs/deployment-readiness-review-2026-06-22.md docs/ops/release-checklist.md docs/ops/rollback-plan.md docs/ops/incident-response.md docs/ops/secret-management.md docs/ops/backup-and-recovery.md test/test_deployment_readiness_artifacts.py docs/hi20260204-maker-solo-execution-close-check-2026-06-22.md docs/hi20260204-maker-collaboration-dependencies-2026-06-22.md docs/superpowers/plans/2026-06-22-final-stabilization-and-release-readiness.md
git commit -m "docs: add release readiness baseline"
```

Expected: commit succeeds.

---

## Self-Review

- Spec coverage: B안의 배포 준비성 검토, 운영 문서, 정적 검증 테스트, 이슈 comment, close 재판정이 모두 task로 포함되어 있다.
- Placeholder scan: 계획에는 `TBD`, `TODO`, `나중에 구현`, `적절한 처리`가 없다. 운영 전 결정해야 하는 값은 `확인 필요` 또는 `운영 전 결정 필요`로 명시되어 확정값으로 쓰지 않는다.
- Type consistency: 테스트 파일 경로는 `test/test_deployment_readiness_artifacts.py`로 일관된다. 운영 문서 경로는 `docs/ops/` 하위 5개 파일로 일관된다.
- Scope control: 실제 인증, Agent, RAG, API 구현은 제외되어 있다.
