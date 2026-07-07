# 리포팅 구현 정렬 설계서

| 항목 | 내용 |
|---|---|
| 문서 목적 | 기존 기획/화면설계의 리포팅 2종과 현재 구현 사이의 차이를 정리하고, 다음 구현 계약을 고정한다. |
| 기준일 | 2026-07-07 |
| 기준 브랜치 | `origin/dev` (`d4deb71`, PR #149 merge 기준) |
| 기준 문서 | `docs/screen-design-specification.md`, `docs/issues/68-mvp-demo-checklist-2026-07-06.md`, `backend/README.md`, `docs/database-storage-design-2026-07-06.md` |
| 관련 코드 | `app/services/chatbot_mock_service.py`, `app/web/FrontendAppShell.jsx`, `backend/chatbot/urls.py`, `backend/chatbot/repositories.py` |

---

## 1. 현재 판단

현재 MVP는 `상담 -> 분석 job -> report 저장 -> 다운로드 -> 내 사건/이력 재조회`의 뼈대는 구현되어 있다.

하지만 기획/화면설계에서 기대한 완성형 리포팅 경험과는 아직 차이가 있다.

| 영역 | 설계 기대 | 현재 구현 | 판단 |
|---|---|---|---|
| 리포트 종류 | 과태료·범칙금 대응 리포트, 사고 과실비율 분석 리포트 2종 | `fine_notice`, `fault_ratio` 제목은 존재 | 부분 충족 |
| 과태료 리포트 | OCR, 처분, 이의가능성, 증거, 법령·판례, 예상 결과, 이의신청서 초안 | `fine_notice` 전용 섹션 구현 | 대체로 충족 |
| 과실비율 리포트 | 사고 개요, 제출 자료, AI 분석, 판단 근거, 핵심 쟁점, 유사 판례·사례, 후속 조치 | `fault_ratio`가 generic 섹션으로 fallback | 미충족 |
| 리포트 작업대 | 리포트 목록/미리보기/근거·작업 패널/다운로드 | 프론트 화면은 존재하나 현재 상담 1건 중심 | 부분 충족 |
| 리포트 목록/상세 API | `GET /api/reports/`, `GET /api/reports/{id}/`, `GET /api/reports/{id}/related-cases/` | `POST /api/reports/`, `GET /api/reports/{id}/download/` 중심 | 미충족 |
| 다운로드 문서 | 리포트 타입별 문서 본문 | 텍스트 metadata + reporting payload summary | 부분 충족 |
| PDF/DOCX 문서 | 제출 가능한 PDF 또는 이의신청서 초안 파일 | 텍스트 다운로드 중심 | 후순위 미충족 |

---

## 2. 리포트 타입 계약

리포트 타입은 화면설계 기준 2종을 1차 구현 범위로 고정한다.

| 시나리오 | 리포트 타입 | 화면 ID | 제목 | 목적 |
|---|---|---|---|---|
| `fine_notice` | `fine_notice_objection` | `UI-REPORT-FINE-001` | 과태료·범칙금 대응 리포트 | 고지서 OCR, 처분 정보, 이의제기 가능성, 이의신청서 초안 제공 |
| `fault_ratio` | `fault_ratio_analysis` | `UI-REPORT-FAULT-001` | 사고 과실비율 분석 리포트 | 사고 상황, 과실비율 쟁점, 판단 근거, 유사 판례·사례, 후속 조치 제공 |

추가 리포트는 1차 구현 후 확장한다.

| 후보 | 처리 |
|---|---|
| `law_question` 교통 법령 근거 리포트 | 리포트 작업대의 보조 문서로 유지하되 1차 상세 리포트 범위에서는 제외 |
| `report_redownload` | 리포트 타입이 아니라 저장 리포트 재조회/재다운로드 intent로 처리 |
| 범용 Supervisor 상담 분석 리포트 | fallback으로 유지하되 사용자-facing 기본 리포트가 되지 않도록 한다 |

---

## 3. Reporting Payload 공통 계약

현재 `reporting_payload.v1`은 유지하되, 리포트 타입별 표시와 다운로드를 안정화하기 위해 다음 필드를 명시한다.

```json
{
  "contract_version": "reporting_payload.v1",
  "scenario": "fine_notice | fault_ratio | law_question | report_redownload",
  "report_type": "fine_notice_objection | fault_ratio_analysis | generic_supervisor",
  "screen_id": "UI-REPORT-FINE-001 | UI-REPORT-FAULT-001",
  "stage": "slot_filling | agent_execution_ready | partial | success",
  "title": "문서 제목",
  "summary": "사용자가 이해할 수 있는 한 문단 요약",
  "quality": {
    "partial_report": false,
    "review_required": true,
    "confidence_label": "검토 가능 | 추가 자료 필요 | 낮음"
  },
  "sections": []
}
```

필수 규칙:

- `sections[].title`은 화면설계의 영역명을 그대로 사용한다.
- `sections[].items[]`는 `{ "label": "...", "value": "...", "field": "..." }` 형태를 기본으로 한다.
- 실제 확정 판단처럼 보이는 문구는 금지한다.
- RAG/Agent 결과가 없으면 빈 값을 숨기지 말고 `확인 필요`, `추가 자료 필요`, `RAG 연결 전 최신성 확인 필요`처럼 제한을 표시한다.

---

## 4. 과태료·범칙금 대응 리포트 계약

현재 구현된 `fine_notice` 전용 섹션을 1차 기준으로 유지하되, 화면설계와 용어를 더 맞춘다.

| 순서 | 섹션 | 필수 표시 |
|---:|---|---|
| 1 | 고지서 OCR 결과 | 위반 유형, 고지 번호, 위반 일시, 장소, 금액, 납부 기한 |
| 2 | 처분 결과 | 과태료/범칙금 구분, 벌점, 납부 상태, 의견제출 기한 |
| 3 | 이의제기 가능성 | 가능/검토 필요/낮음, 판단 사유, missing field |
| 4 | 필요 증거 | 블랙박스, 사진, 현장 상황, 운전자 진술, 고지서 원본 |
| 5 | 관련 법령·판례 | 법령 조항, 시행규칙, 판례 또는 행정심판 사례 |
| 6 | 예상 결과 | 수용 가능성, 감경 가능성, 기각 가능성, 리스크 |
| 7 | 이의신청서 초안 | 제목, 제출 대상, 사실관계, 주장, 첨부 자료, 마무리 문구 |
| 8 | 제출 가이드라인 | 고지서 확인, 증거 첨부, 문구 검토, 제출 방법 확인 |

현재 차이:

- `고지 번호`, `납부 기한`, `벌점`, `납부 상태`는 placeholder 또는 누락 가능성이 있다.
- 법령·판례는 실제 RAG 결과가 아닌 검색 쿼리/한계 문구 중심이다.
- PDF/DOCX 문서 생성은 아직 없다.

---

## 5. 사고 과실비율 분석 리포트 계약

`fault_ratio`는 현재 generic fallback이므로 전용 섹션을 새로 구현해야 한다.

| 순서 | 섹션 | 필수 표시 |
|---:|---|---|
| 1 | 사고 개요 | 사고 일시, 장소, 사고 유형, 차량 A/B, 핵심 상황 |
| 2 | 제출 자료 | 사고 사진, 블랙박스, 진술서, 보험사 자료, 자료 상태 |
| 3 | AI 분석 결과 | 예상 과실비율 후보, 책임 방향, 신뢰도, 주의 문구 |
| 4 | 판단 근거 | 도로교통법, 과실비율 인정기준, 보험사 기준, 적용 한계 |
| 5 | 핵심 쟁점 | 신호, 차선, 우선권, 속도, 회피 가능성, 증거 부족 지점 |
| 6 | 유사 판례·사례 | 사건번호, 사고 유형, 주요 내용, 과실비율, 결정 요지 |
| 7 | 후속 조치 | 추가 증거 요청, 보험사 대응, 이의제기 가능성, 리포트 다운로드 |

구현 입력 후보:

| 데이터 | 현재 위치 | 사용 방식 |
|---|---|---|
| 사용자 사고 설명 | `facts.raw_conversation`, `facts.user_facts` | 사고 개요와 핵심 상황 |
| 첨부 목적/상태 | `attachments`, `analysis_plan.input_summary.attachment_purposes` | 제출 자료 |
| 과실비율 후보 | `structured_result.ratio_range_label` | AI 분석 결과 |
| 유사 사례 | `structured_result.similar_cases` | 유사 판례·사례 |
| 권장 증거 | `structured_result.recommended_evidence` | 후속 조치, 제출 자료 |
| 제한 사항 | `limitations`, `report_quality.limitations` | 주의 문구, partial report |
| Agent 상태 | `agent_input_packages`, `node_results` | 판단 근거, 근거·작업 패널 |

표시 정책:

- 과실비율은 확정 수치가 아니라 `예상 범위`, `후보`, `쟁점`으로 표시한다.
- 유사 사례는 `참고 근거`로만 표시하고 법률 판단처럼 쓰지 않는다.
- 자료가 부족하면 `partial_report`와 추가 필요 자료를 상단에 노출한다.

---

## 6. 리포트 작업대 UI 계약

현재 프론트의 `ReportWorkbenchScreen`은 좋은 뼈대가 있으나, 다음이 부족하다.

| 영역 | 현재 | 목표 |
|---|---|---|
| 리포트 목록 | 현재 상담의 리포트 1건 중심 | 저장 리포트 목록 API 기반 다건 표시 |
| 리포트 미리보기 | `sections` 공통 나열 | 리포트 타입별 문서 레이아웃 |
| 근거·작업 패널 | Supervisor/Agent 상태와 일부 fault insight | 제출 자료, 관련 기준, 후속 행동, 다운로드 조건 명확화 |
| 액션 | 저장/다운로드/근거 보기 버튼 | 타입별 PDF/DOCX 조건, 근거 상세, 재생성 |

1차 UI 구현 범위:

- `reportingPayload.report_type` 또는 `scenario`로 리포트 타입 배지를 표시한다.
- `fine_notice`와 `fault_ratio`의 섹션 순서를 고정한다.
- generic fallback은 개발/진단용으로만 보이게 한다.
- `ReportActionPanel`의 영어 문구(`Ready analysis report`, `Review required before final submission`)를 사용자-facing 한국어로 교체한다.

2차 UI 구현 범위:

- 저장 리포트 목록 API와 연결한다.
- 리포트 상세 API와 연결한다.
- 관련 사례/근거 상세 drawer 또는 panel을 추가한다.

---

## 7. API 계약

현재 존재:

| Method | Path | 상태 |
|---|---|---|
| `POST` | `/api/reports/` | 구현됨. report metadata 저장 및 object storage mock write |
| `GET` | `/api/reports/{report_id}/download/` | 구현됨. 소유권 확인 후 텍스트 다운로드 |

추가 필요:

| Method | Path | 목적 | 우선순위 |
|---|---|---|---|
| `GET` | `/api/reports/` | 세션/사용자 기준 리포트 목록 | 높음 |
| `GET` | `/api/reports/{report_id}/` | 리포트 상세, reporting payload, report_quality, linked job | 높음 |
| `GET` | `/api/reports/{report_id}/related-cases/` | 과실비율 유사 사례 또는 법령/판례 근거 | 보통 |
| `POST` | `/api/reports/{report_id}/regenerate/` | 추가 자료 반영 후 재생성 | 낮음 |

목록 응답 초안:

```json
{
  "api_surface": "canonical_mock",
  "reports": [
    {
      "report_id": "rep_...",
      "report_type": "fault_ratio_analysis",
      "title": "사고 과실비율 분석 리포트",
      "status": "ready",
      "session_id": "ses_...",
      "job_id": "job_...",
      "created_at": "...",
      "updated_at": "...",
      "summary": "...",
      "download_url": "/api/reports/rep_.../download/",
      "partial_report": false
    }
  ]
}
```

상세 응답 초안:

```json
{
  "api_surface": "canonical_mock",
  "report": {
    "report_id": "rep_...",
    "report_type": "fine_notice_objection",
    "title": "과태료·범칙금 대응 리포트",
    "status": "ready",
    "content_summary": "...",
    "content": {
      "reporting_payload": {}
    },
    "metadata": {
      "report_quality": {}
    },
    "job": {},
    "display_result": {}
  }
}
```

---

## 8. 다운로드 문서 계약

1차 다운로드는 텍스트 파일을 유지한다. 단, 타입별 섹션은 반드시 포함한다.

| 리포트 타입 | 다운로드 본문 필수 포함 |
|---|---|
| `fine_notice_objection` | `고지서 OCR 결과`, `이의신청서 초안`, `제출 가이드라인` |
| `fault_ratio_analysis` | `사고 개요`, `AI 분석 결과`, `판단 근거`, `유사 판례·사례`, `후속 조치` |

2차 다운로드는 PDF 생성으로 확장한다.

| 단계 | 산출물 |
|---|---|
| 1차 | `.txt` metadata + section body |
| 2차 | 리포트 PDF |
| 3차 | 과태료 이의신청서 DOCX/PDF 초안 |

---

## 9. 테스트 계약

1차 구현에서 추가해야 할 테스트:

| 테스트 | 목적 |
|---|---|
| `test_fault_ratio_reporting_payload_uses_report_sections` | `fault_ratio`가 generic fallback이 아니라 전용 섹션을 반환하는지 검증 |
| `test_fault_ratio_report_download_includes_required_sections` | 다운로드 본문에 과실비율 필수 섹션 포함 검증 |
| `test_fine_notice_reporting_payload_keeps_required_sections` | 과태료 리포트 섹션 회귀 방지 |
| `test_frontend_report_workbench_uses_report_type_contract` | 프론트가 report type/section contract를 사용하도록 정적 계약 고정 |
| `test_reports_list_and_detail_contract` | 목록/상세 API 추가 시 응답 필드 고정 |

기존 유지 테스트:

- `test_chatbot_mock_service.py`
- `test_frontend_auth_session_contract.py`
- `backend/manage.py test chatbot.tests.ChatbotMockApiTests...report...`
- `npm --prefix app/web run build`

---

## 10. 구현 순서

### Phase 1. 리포팅 payload 정렬

1. `fault_ratio` 전용 `_fault_ratio_report_sections()` 추가
2. `_report_sections()`가 `fault_ratio`를 generic fallback으로 보내지 않도록 변경
3. `report_type`, `screen_id`, `quality` 필드 추가
4. 과태료 리포트 기존 섹션 회귀 테스트 유지
5. 과실비율 리포트 전용 섹션 테스트 추가

### Phase 2. 프론트 표시 정렬

1. `ReportWorkbenchScreen`에서 report type badge와 section order 표시
2. `ReportingPreviewPanel`이 리포트 타입별 제목/요약/섹션을 명확히 표시
3. 사용자-facing 문구를 한국어로 정리
4. generic fallback은 개발용 또는 partial 상태로 표시

### Phase 3. 리포트 API 확장

1. `GET /api/reports/` 추가
2. `GET /api/reports/{report_id}/` 추가
3. MyPage/History/ReportWorkbench가 저장 리포트 목록과 상세를 같은 계약으로 사용

### Phase 4. 문서 산출 확장

1. 타입별 `.txt` 본문 강화
2. PDF 생성 adapter 추가
3. 이의신청서 초안 DOCX/PDF 생성은 별도 phase로 분리

---

## 11. 이번 설계의 결론

현재 프로젝트는 MVP spine은 구현되어 있지만, 리포팅은 아직 "상담 결과를 저장하고 다운로드하는 기능"에 가깝다.

다음 구현의 목표는 리포팅을 "기획/화면설계에 적힌 2종 문서형 리포트"로 올리는 것이다.

가장 먼저 해야 할 일은 `fault_ratio` 전용 리포트 payload를 만드는 것이다. 이 작업이 끝나야 프론트 작업대, 다운로드 문서, 목록/상세 API가 같은 계약을 바라볼 수 있다.
