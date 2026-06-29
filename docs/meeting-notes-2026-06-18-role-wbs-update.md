# 2026-06-18 회의록 및 WBS 변경 기록

## 1. 기록 위치

오늘 회의 내용은 WBS, 담당자, GitHub Issue 구조 변경이 중심이므로 `docs-wbs-owner-deliverable-plan` 브랜치에 기록하는 것이 가장 적합하다.

브랜치별 권장 역할은 다음과 같다.

| 브랜치 | 사용 목적 |
|---|---|
| `docs-wbs-owner-deliverable-plan` | 오늘 회의록, WBS, Issue parent/child 구조, 담당자별 산출물, 일정 기준 |
| `docs-project-scope-and-role-matrix` | 역할 매트릭스와 프로젝트 범위 공식 문서 |
| `docs-mvp-screen-and-process-flows` | 홈, 로그인, 챗봇, Supervisor, 화면 흐름 |
| `docs-requirement-gap-and-risk-log` | 기존 요구사항과 회의 변경사항의 충돌/리스크 |

GitHub Issue comment는 특정 Git 브랜치에 속하지 않는다. 따라서 회의록 원문은 문서 브랜치에 저장하고, GitHub Issue에는 해당 문서와 결정 요약을 comment로 연결한다.

## 2. 일정 기준

| 기준일 | 의미 |
|---|---|
| 2026-07-14 | 중간 발표 MVP |
| 2026-08-04 | 최종 마무리 |

## 3. 최신 역할 기준

| 이름 | GitHub 계정 | 담당 |
|---|---|---|
| 요청자/문서·QA | `hi20260204-maker` | WBS/문서, Supervisor 통합 답변 구조, 홈·로그인·챗봇 진입 흐름, 이의신청서 생성 노드, 통합 QA |
| 재강 | `leejaegang27` | 경위서/OCR 결과 처리, 텍스트 ML, 과실비율 판례, 유튜브 자막 사례, 과실비율심의사례 데이터, 판례 Agent |
| 주희 | `ohjuheecode` | 차량 사고 이미지·영상 데이터셋, Vision/DL 분석, 영상·이미지 Agent, DL 결과 구조화 |
| 동혁 | `techshin31` | 법률 데이터 수집, 전처리, DB 적재, 법률 원문/조문/근거 metadata |
| 필주 | `workzion2` | 고지서 OCR, 과태료·범칙금·벌칙 분석용 룰/매핑 데이터, 과태료·범칙금 분석 흐름 |

## 4. 핵심 결정

- 최종 답변은 개별 Agent가 아니라 Supervisor가 각 Agent 결과 스키마를 통합해 생성한다.
- 필주는 고지서 OCR을 포함해서 과태료·범칙금·벌칙 분석 흐름을 담당한다.
- 동혁은 판례가 아니라 법률 데이터 수집, 전처리, DB 적재만 담당한다.
- 재강은 경위서/OCR 결과, 텍스트 ML, 과실비율 판례, 유튜브 자막 사례, 과실비율심의사례 데이터를 담당한다.
- 주희는 차량 사고 이미지·영상, Vision/DL 흐름을 담당한다.
- 이의신청서 생성은 요청자 담당으로 고정한다.
- 보험 약관과 합의금 기능은 후순위다.
- 합의금 관련 GitHub Issue `#6`, `#34`, `#35`는 삭제하지 않고 scope-out으로 닫아 추적성을 남긴다.

## 5. Parent/Child Issue 구조

| Parent issue | Child issue |
|---|---|
| `#2 epic-planning-wbs-scope` | `#10`, `#11`, `#12`, `#13` |
| `#3 epic-common-architecture-data-pipeline` | `#14`, `#15`, `#16`, `#17`, `#18`, `#19`, `#22`, `#29` |
| `#4 epic-fine-ocr-penalty-analysis` | `#23`, `#24`, `#25`, `#26`, `#27`, `#28` |
| `#5 epic-fault-ratio-precedent-vision-flow` | `#30`, `#31`, `#32`, `#33` |
| `#6 epic-settlement-helper-mvp` | `#34`, `#35` |
| `#7 epic-vision-accident-image-video-agent` | `#36`, `#37`, `#38`, `#39` |
| `#8 epic-integration-qa-final-demo` | `#40`, `#41`, `#42`, `#43` |
| `#9 epic-legal-precedent-data-ingestion-and-rag` | `#1`, `#20`, `#21` |

## 6. GitHub Project 권한 정정

이전에 `write:project`라고 표현한 것은 부정확하다.

- classic personal access token 기준:
  - 읽기: `read:project`
  - 전체 제어: `project`
- fine-grained token 기준:
  - repository 또는 organization Projects 권한을 `Read and write`로 설정해야 한다.

현재 저장된 토큰 scope는 `gist, repo, workflow`만 확인되므로 GitHub Project 보드 연결은 할 수 없다. Issue, label, milestone, assignee, sub-issue는 현재 권한으로 처리 가능하다.

## 7. Issue comment 작성 원칙

새 Issue 또는 변경 Issue에는 단순 제목/한 줄 설명만 남기지 않는다. 최소한 아래 항목을 comment 또는 본문에 포함한다.

- 회의 반영 배경
- 담당자와 책임 범위
- 입력 데이터
- 상세 작업 범위
- 제외 범위
- 산출물
- 완료 기준
- 연결되는 parent/child issue
- 중간 기준일과 최종 기준일
- Supervisor 통합 시 사용될 결과 스키마
