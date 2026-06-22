# ai

Supervisor, Agent, 공통 AI 결과 schema, 모델 검증 보조 자산을 관리하는 공간이다.

## 하위 폴더 역할

| 폴더 | 역할 |
|---|---|
| `supervisor/` | 사용자 입력 분류, Agent routing, Agent 결과 병합 흐름을 둔다. |
| `agents/` | 도메인별 Agent 구현을 둔다. |
| `agents/fine_notice_analysis/` | 고지서 OCR, 과태료·범칙금 분석 결과 생성을 담당한다. |
| `agents/law_ground_search/` | 법령, 시행령, 시행규칙, 행정 기준 근거 검색을 담당한다. |
| `agents/text_ml_case_search/` | 사고 설명, 판례, 자막, 과실비율심의사례 검색과 텍스트 ML 결과를 담당한다. |
| `agents/vision_media_analysis/` | 이미지와 영상 분석 결과를 담당한다. |
| `agents/objection_report_generation/` | 이의신청서 초안과 리포트 생성 결과를 담당한다. |
| `schemas/` | 공통 Agent result envelope, evidence metadata, 상태값 계약을 둔다. |
| `evaluation/` | 모델 후보 비교, 샘플 검증, Agent 출력 품질 확인 보조 자산을 둔다. |

## 배치 원칙

- 최종 자연어 답변은 개별 Agent가 아니라 `supervisor/`에서 통합한다.
- 도메인 Agent는 다른 도메인 Agent의 내부 구현에 직접 의존하지 않는다.
- 공통 결과 구조는 `schemas/`에 두고 도메인별로 복제하지 않는다.
- UI 표현 로직은 `app/`에 둔다.
