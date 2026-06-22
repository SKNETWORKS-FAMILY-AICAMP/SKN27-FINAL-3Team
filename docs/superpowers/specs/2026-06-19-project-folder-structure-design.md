# 프로젝트 폴더 구조 설계

작성일: 2026-06-19
기준 이슈: `#3`, `#16`, `#17`, `#18`, `#22`, `#29`, `#40`, `#41`
기준 문서: `docs/wbs-owner-deliverable-plan.md`, `docs/superpowers/specs/2026-06-19-agent-result-schema-design.md`, `docs/issues/40-cross-mvp-integration-scenarios.md`

## 1. 목적

현재 저장소의 기존 루트 폴더인 `app/`, `ai/`, `etl/`, `storage/`, `test/`, `docs/`를 유지하면서, 중간 발표 MVP 구현자가 책임 경계를 추측하지 않도록 하위 폴더 기준을 정의한다.

이 설계는 실제 구현 코드, 모델 선택, API 최종 명세, DB 최종 스키마를 확정하지 않는다. 폴더 구조와 파일 배치 원칙만 정의한다.

## 2. 설계 원칙

1. 기존 루트 폴더를 최대한 유지한다.
2. 새 루트 폴더는 명확한 문서 근거 없이는 만들지 않는다.
3. 도메인별 구현은 담당 이슈와 같은 책임 경계를 갖는다.
4. 공통 계약은 한 곳에 두고, 도메인 폴더가 임의로 복제하지 않는다.
5. 생성물과 임시 작업물은 소스 구조와 분리한다.
6. 개인정보 또는 원본 민감 데이터는 기본 커밋 대상에서 제외한다.

## 3. 현재 루트 폴더 해석

| 폴더 | 유지 목적 | 주요 연결 이슈 |
|---|---|---|
| `app/` | 사용자 화면, API entrypoint, application service | `#12`, `#14`, `#25`, `#27`, `#29`, `#40` |
| `ai/` | Supervisor, Agent, AI 결과 schema, 모델 검증 보조 | `#22`, `#29`, `#30`, `#36`, `#38` |
| `etl/` | 데이터 수집, 전처리, 적재 준비 파이프라인 | `#1`, `#16`, `#17`, `#20`, `#21`, `#24`, `#37` |
| `storage/` | DB, RAG, Docker, migration, 저장소 계약 | `#16`, `#17`, `#18`, `#20`, `#22` |
| `test/` | 단위, 통합, E2E, 수동 시나리오, fixture | `#28`, `#39`, `#40`, `#41` |
| `docs/` | 구현 source of truth, 설계, 이슈별 기준, 리스크 | `#2`, `#10`, `#11`, `#12`, `#13`, `#19`, `#42` |
| `output/` | 문서/PDF/엑셀 등 생성 산출물 보관 | 문서 산출물 |
| `tmp/` | PDF 생성, GitHub 동기화 등 임시 작업 스크립트 | 작업 보조 |

`output/`과 `tmp/`는 이미 존재하므로 삭제하지 않는다. 다만 신규 기능 구현의 기본 소스 위치로 사용하지 않는다.

## 4. 권장 폴더 구조

```text
app/
  web/
  api/
  services/
  schemas/

ai/
  supervisor/
  agents/
    fine_notice_analysis/
    law_ground_search/
    text_ml_case_search/
    vision_media_analysis/
    objection_report_generation/
  schemas/
  evaluation/

etl/
  common/
  legal/
  fine_rules/
  fault_cases/
  vision_manifest/

storage/
  docker/
  schemas/
  migrations/
  rag/
  samples/

test/
  unit/
  integration/
  e2e/
  fixtures/
  manual_scenarios/

docs/
  architecture/
  api/
  issues/
  risks/
  assets/
  superpowers/specs/
```

## 5. 폴더별 책임

### 5.1 `app/`

`app/`는 사용자-facing 흐름과 API 경계를 담당한다. AI 모델 내부 구현이나 데이터 수집 로직을 직접 포함하지 않는다.

| 하위 폴더 | 책임 |
|---|---|
| `web/` | 홈, 로그인, 챗봇, 결과/리포트 화면 |
| `api/` | 요청/응답 entrypoint, 라우터, controller |
| `services/` | 화면/API와 `ai/`, `storage/` 계약을 연결하는 application service |
| `schemas/` | API request/response DTO, 화면 표시용 schema |

`app/services/`는 비즈니스 흐름을 조합하되, Agent 내부 판단 로직을 직접 구현하지 않는다.

### 5.2 `ai/`

`ai/`는 Supervisor와 Agent 결과 계약을 담당한다. 문서 기준 최종 자연어 답변은 개별 Agent가 아니라 Supervisor가 통합한다.

| 하위 폴더 | 책임 | 연결 이슈 |
|---|---|---|
| `supervisor/` | 입력 분류, 라우팅, Agent 결과 병합 | `#29` |
| `agents/fine_notice_analysis/` | 고지서 OCR, 과태료·범칙금 분석 결과 | `#23`, `#24`, `#25`, `#28` |
| `agents/law_ground_search/` | 법률 근거 검색 결과 | `#20`, `#26` |
| `agents/text_ml_case_search/` | 사고 설명, 판례, 자막, 심의사례 검색 결과 | `#1`, `#21`, `#30`, `#31`, `#32`, `#33` |
| `agents/vision_media_analysis/` | 이미지/영상 분석 결과 | `#36`, `#37`, `#38`, `#39` |
| `agents/objection_report_generation/` | 이의신청서 초안/리포트 결과 | `#27` |
| `schemas/` | 공통 Agent result envelope, evidence metadata | `#22` |
| `evaluation/` | 모델 후보 비교와 샘플 검증 보조 | `#28`, `#39`, `#40` |

Agent 폴더명은 `docs/superpowers/specs/2026-06-19-agent-result-schema-design.md`의 코드 식별값 후보와 맞춘다.

### 5.3 `etl/`

`etl/`은 외부 또는 원천 데이터를 수집하고 정제해 저장소에 넣을 수 있는 형태로 만드는 책임을 가진다. API 응답이나 UI 화면 로직을 포함하지 않는다.

| 하위 폴더 | 책임 | 연결 이슈 |
|---|---|---|
| `common/` | source registry, ingestion run tracking 공통 처리 | `#16`, `#17` |
| `legal/` | 법령, 시행령, 시행규칙, 고시, 행정 기준 수집/전처리 | `#20` |
| `fine_rules/` | 과태료·범칙금·벌칙 분석용 룰/매핑 데이터 준비 | `#24` |
| `fault_cases/` | 판례, 유튜브 자막, 과실비율심의사례 수집/전처리 | `#1`, `#21`, `#30` |
| `vision_manifest/` | 이미지/영상 dataset manifest와 metadata 준비 | `#37` |

동혁의 법률 원문 DB와 필주의 분석용 룰/매핑 데이터는 서로 다른 하위 폴더에 둔다.

### 5.4 `storage/`

`storage/`는 데이터 저장소와 RAG 관련 계약을 담당한다. 도메인별 수집 코드는 `etl/`에 두고, 저장소 구조와 migration은 `storage/`에 둔다.

| 하위 폴더 | 책임 |
|---|---|
| `docker/` | 개발용 DB, vector store, 검색 엔진 실행 환경 |
| `schemas/` | DB table, document store, registry schema 문서 또는 schema 파일 |
| `migrations/` | DB 변경 이력 |
| `rag/` | chunk, embedding, evidence metadata 계약 |
| `samples/` | 비식별화된 샘플 manifest와 작은 fixture |

원본 고지서, 원본 블랙박스 영상, 개인정보 포함 파일은 `storage/samples/`에 직접 커밋하지 않는다.

### 5.5 `test/`

`test/`는 검증 범위를 명확히 분리한다. 현재 문서 기준 자동 E2E는 아직 확정되지 않았으므로 수동 시나리오도 별도 위치를 둔다.

| 하위 폴더 | 책임 |
|---|---|
| `unit/` | 함수, schema, parser 단위 테스트 |
| `integration/` | Agent, ETL, storage 계약 간 통합 테스트 |
| `e2e/` | 화면/API/Agent를 연결한 자동 E2E 테스트 |
| `fixtures/` | 비식별화된 테스트 입력 |
| `manual_scenarios/` | `#40` 기반 수동 검증 시나리오 |

`#28`, `#39`, `#40`, `#41`의 검증 결과는 테스트 코드 또는 수동 기록으로 남긴다.

### 5.6 `docs/`

`docs/`는 구현 source of truth 역할을 한다. 구현 전 확정되지 않은 항목은 문서에서 `검증 필요` 또는 `보류`로 분리한다.

| 하위 폴더 | 책임 |
|---|---|
| `architecture/` | 폴더 구조, 시스템 경계, 데이터 흐름 |
| `api/` | API 후보와 request/response 계약 |
| `issues/` | 이슈별 상세 기준 |
| `risks/` | 요구사항 gap, 리스크, guardrail |
| `assets/` | 문서용 이미지와 화면설계 자료 |
| `superpowers/specs/` | 승인된 설계 문서 |

## 6. 의존 방향

의존 방향은 아래 흐름을 기본으로 한다.

```text
app
→ ai
→ storage

etl
→ storage

test
→ app, ai, etl, storage

docs
→ 모든 구현 판단의 기준 문서
```

금지할 의존 방향은 아래와 같다.

| 금지 방향 | 이유 |
|---|---|
| `ai/`가 `app/web/`에 의존 | Agent는 화면 구현과 분리되어야 함 |
| `etl/`이 `app/api/`에 의존 | 수집/전처리는 서비스 API와 독립 실행 가능해야 함 |
| 도메인 Agent가 다른 도메인 내부 구현을 직접 import | Supervisor를 통한 병합 구조가 깨짐 |
| `storage/`가 특정 Agent 내부 로직에 의존 | 저장소 계약은 도메인 구현보다 안정적이어야 함 |

## 7. dev 반영 기준

폴더 구조를 `dev`에 반영하기 전 아래 조건을 만족해야 한다.

1. 이 설계 문서가 승인되어야 한다.
2. 변경은 `#3` 하위 작업으로 기록한다.
3. 실제 폴더 생성은 빈 디렉터리만 만들지 않고, 각 폴더의 책임을 설명하는 `README.md` 또는 `.gitkeep` 정책 중 하나를 정해 진행한다.
4. `output/`과 `tmp/` 산출물 전체를 폴더 구조 작업과 함께 병합하지 않는다.
5. 기존 미추적 문서와 새 폴더 구조 작업을 한 커밋에 섞지 않는다.

## 8. 검증 기준

| 검증 항목 | 방법 | 통과 기준 |
|---|---|---|
| 기존 루트 유지 | 루트 목록 확인 | `app/`, `ai/`, `etl/`, `storage/`, `test/`, `docs/` 유지 |
| 이슈 매핑 | 이슈 번호와 폴더 책임 대조 | 주요 구현 이슈가 최소 하나의 책임 폴더에 매핑됨 |
| 도메인 분리 | 하위 폴더명 검토 | fine, legal, fault, vision, supervisor 책임이 섞이지 않음 |
| 생성물 분리 | `output/`, `tmp/` 확인 | 신규 구현 소스가 생성물 폴더에 들어가지 않음 |
| 민감 데이터 방지 | sample/fixture 정책 확인 | 원본 민감 파일 커밋 금지 기준 존재 |

## 9. 남은 리스크

| 리스크 | 영향 | 처리 기준 |
|---|---|---|
| 실제 프레임워크 미확정 | `app/` 내부 세부 구조가 바뀔 수 있음 | 현재는 책임 경계만 고정 |
| API endpoint 미확정 | `app/api/` 파일명 확정 불가 | `docs/api/`에서 후보 계약 먼저 정리 |
| DB 종류와 RAG 구현 미확정 | `storage/` 하위 파일 형식 변경 가능 | schema와 metadata 계약부터 둠 |
| 모델 최종 선택 미확정 | `ai/evaluation/` 산출물 변경 가능 | 모델 후보 비교 기록으로 제한 |
| 샘플 데이터 미확보 | 테스트 fixture 구성이 지연됨 | 비식별 fixture 확보 전 원본 커밋 금지 |

## 10. 승인 후 다음 단계

이 설계가 승인되면 별도 구현 계획에서 아래 작업을 순서대로 진행한다.

1. 폴더 생성 대상과 README 작성 대상을 확정한다.
2. 기존 README 인코딩 깨짐 여부를 확인하고 필요한 경우 UTF-8 문서로 교체한다.
3. `#3` 또는 `#18` 기준 브랜치에서 폴더 구조 커밋을 분리한다.
4. `dev` 반영 전 `git diff --stat origin/dev...HEAD`로 문서 산출물과 구조 작업이 섞이지 않았는지 확인한다.
