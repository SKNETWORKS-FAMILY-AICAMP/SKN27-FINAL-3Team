# 공식 이의신청서 최종 확인 게이트 설계

## 목표

일반 분석 리포트는 화면에서만 열람·저장하고, 제출 목적의 공식 이의신청서 DOCX만 사용자가 네 가지 필수 항목을 최종 확인한 뒤 다운로드할 수 있게 한다.

## 범위와 정책

- 대상은 `fine_notice`와 `traffic_accident`의 공식 이의신청서(`objection_form`)이다.
- 일반 분석 리포트는 화면 열람과 저장만 지원한다. 사용자 대상 `download_report` 동작 및 분석 리포트 DOCX 버튼은 제공하지 않는다.
- 이의신청 가능 여부가 `denied`, `not_applicable`, 또는 기한 경과로 차단되면 확인과 공식 DOCX 다운로드를 모두 거절한다.
- 기존 리포트 상세·목록 응답의 기존 필드는 유지하고, 확인 상태는 선택 필드로만 추가한다.

## API 설계

### 공식 문서 최종 확인

`POST /api/reports/{report_id}/document-confirmation/`를 추가한다.

요청 본문은 다음 네 Boolean 값만 받는다.

```json
{
  "facts_confirmed": true,
  "agency_confirmed": true,
  "deadline_confirmed": true,
  "attachments_confirmed": true
}
```

인증된 보고서 소유자만 호출할 수 있고, 네 값 중 하나라도 `true`가 아니면 `422 validation_error`를 반환한다. 보고서가 없으면 `404 report_not_found`, 소유자가 아니면 기존 `object_access_denied` 규칙을 따른다. 이의신청 게이트가 차단되어 있으면 `409 appeal_gate_blocked`를 반환한다.

성공 응답은 `201`이며, 리포트 상세에서 쓰는 안전한 확인 상태를 반환한다. 이 엔드포인트는 원문 사실관계나 DOCX 내용을 요청 본문으로 받지 않는다.

### DOCX 다운로드

기존 `GET /api/reports/{report_id}/download/`는 `document_type=objection_form`으로 정규화되는 공식 이의신청서만 제공한다. `report`와 빈 값 등 일반 리포트 다운로드 요청은 `409 document_download_not_available`를 반환한다.

공식 이의신청서 다운로드 순서는 다음과 같다.

1. 인증·소유권·리포트 준비 상태를 확인한다.
2. appeal gate를 확인하고 차단이면 `409 appeal_gate_blocked`를 반환한다.
3. 현재 문서 입력의 지문과 저장된 최종 확인 지문을 비교한다.
4. 확인이 없거나 지문이 다르면 `409 document_confirmation_required`를 반환한다.
5. 조건을 모두 통과하면 DOCX를 렌더링한다.

## 상태 저장과 개인정보 보호

확인 기록은 리포트의 `metadata.document_confirmation`에 저장한다. 이는 문서 본문이 아니라 사용자 행위 메타데이터이므로 `content.reporting_payload`와 분리한다.

저장 값은 다음으로 한정한다.

```json
{
  "schema_version": "document_confirmation.v1",
  "document_type": "objection_form",
  "input_fingerprint": "sha256 hex digest",
  "confirmed_at": "ISO-8601 UTC timestamp",
  "confirmed_by_user_id": "internal owner id",
  "items": {
    "facts_confirmed": true,
    "agency_confirmed": true,
    "deadline_confirmed": true,
    "attachments_confirmed": true
  }
}
```

지문은 현재 공식 문서에 실제 반영되는 `document_variant`, `form_data`, `sections`, `petition_purpose`, `petition_reason`을 정규화한 뒤 SHA-256으로 계산한다. 원문 개인정보는 새로운 저장소나 API 응답에 복제하지 않는다. 현재 지문이 저장 지문과 다르면 확인은 자동으로 stale 상태가 되어 재확인이 필요하다.

리포트 상세 응답의 `reporting_payload.document_confirmation`에는 다음의 공개 상태만 추가한다.

```json
{
  "required": true,
  "confirmed": false,
  "stale": false,
  "confirmed_at": null
}
```

내부 사용자 식별자와 지문은 공개 응답에 포함하지 않는다.

## UI 설계

- 일반 분석 리포트 DOCX 버튼은 `ReportReadyNotice`, `ReportActionPanel`, 분석 작업대의 상태·다운로드 패널에서 제거한다.
- 공식 이의신청서가 제공되는 화면에는 사실관계·관할기관·기한·첨부자료의 네 체크 항목과 확인 버튼을 표시한다.
- 네 항목이 모두 선택되기 전에는 확인 요청을 보내지 않는다.
- 확인 성공 후 리포트 상세를 다시 불러와 공식 DOCX 버튼을 활성화한다.
- 이의신청 게이트가 차단되면 확인 UI와 다운로드 버튼을 모두 비활성화하고 기존 차단 사유를 표시한다.
- 입력이 바뀌어 stale 상태가 되면 재확인 안내와 함께 다운로드를 막는다.

## 테스트와 완료 기준

- 일반 리포트 다운로드 요청이 거절되고, 화면 어디에도 일반 리포트 DOCX 버튼이 남지 않는다.
- 소유자만 네 항목을 모두 확인해 확인 기록을 만들 수 있다.
- 확인 전·변경 후·stale 상태의 공식 DOCX 요청은 `409 document_confirmation_required`를 반환한다.
- appeal gate 차단 상태는 확인과 공식 DOCX 다운로드 모두 `409 appeal_gate_blocked`를 반환한다.
- fine_notice와 traffic_accident의 확인 완료 공식 DOCX 다운로드는 유지된다.
- 응답 DTO·OpenAPI 경로·프런트엔드 API 클라이언트 계약 테스트와 전체 테스트 스위트가 통과한다.
- 준비도 체크리스트에서 #238 완료 두 항목은 `[x]`, 최종 확인 항목은 `[~] — #241`로 기록한다.
