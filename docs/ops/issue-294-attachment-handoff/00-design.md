# 첨부 OCR 분류와 사고 증거 Handoff 설계

## 목적

채팅창에서 업로드한 이미지와 PDF를 scan-ready 경계 뒤 실제 OCR·첨부 분류 Agent로 처리하고, 사용자가 분류 결과를 확인한 뒤에만 고지서 또는 사고 증거의 기존 분석 흐름으로 전달한다.

## 범위

- 이미지와 PDF는 `fine_notice`, `accident_evidence`, `unknown`으로 분류한다.
- 동영상은 기존 `vision_media_analysis` 경로를 유지한다.
- 고지서는 기존 고지서 OCR 확인, 법령 검색, 이의신청 흐름을 유지한다.
- 사고 증거는 기존 사실관계 확인을 유지하고, 확인 후에만 판례·법령 검색을 시작한다.
- 분류 실행·확인·handoff의 안전한 metadata와 운영 trace를 남긴다.

## 범위 밖

- 영상 모델의 품질 개선 또는 새 모델·공급자 도입
- 자동 과실률·법적 결론 생성
- pgvector·Neo4j 자동 적재 구현
- 실제 checkpoint 또는 비밀값이 없는 환경에서의 성공 주장

## 사용자 흐름

```text
이미지/PDF 업로드
  -> 파일 스캔 clean 및 canonical attachment 확인
  -> attachment_document_classification 실행
  -> 분류 결과 확인 카드
       -> fine_notice: fine_notice_analysis OCR 확인 카드
                         -> 사용자 OCR 확인
                         -> law_ground_search, appeal_decision_flow
       -> accident_evidence: 사고 사실관계 확인
                         -> text_ml_case_search, law_ground_search
       -> unknown: 검색 차단 및 목적 수정·재업로드 안내

동영상 업로드
  -> 기존 vision_media_analysis
  -> text_ml_case_search, law_ground_search
```

## 컴포넌트와 책임

### 1. OCR·첨부 분류 Agent

새 `attachment_document_classification` node는 canonical scan-ready 이미지 또는 PDF만 읽는다. 기존 고지서 OCR과 같은 현재 승인 provider 경계만 이용하며, 새 공급자를 도입하지 않는다. 결과는 다음의 좁은 계약으로 제한한다.

```json
{
  "classification": "fine_notice | accident_evidence | unknown",
  "confidence_band": "high | medium | low",
  "requires_confirmation": true,
  "error_code": "optional_safe_code",
  "next_action": "confirm_classification | retry_upload | change_purpose"
}
```

OCR 원문, 파일 바이트, 실제 저장소 URI, 개인식별정보는 이 결과·응답·운영 metadata에 넣지 않는다.

### 2. 서버 신뢰 경계와 확인

클라이언트의 `purpose`는 업로드 의도를 나타낼 뿐 최종 분류 권한이 아니다. 서버는 scan-ready `attachment_id`에 결합한 분류 결과와 확인 상태를 저장하고, 후속 요청은 attachment ID·분류·확인값이 서버 기록과 일치할 때만 통과시킨다.

분류 확인은 고지서의 `ocr_confirmation`과 별개다. 고지서 흐름은 분류 확인 뒤에도 기존 OCR 필드 확인이 필요하다. 사고 증거 흐름은 분류 확인 뒤에도 기존 사고 사실관계 확인이 필요하다.

### 3. 라우팅 규칙

- 이미지/PDF는 먼저 `attachment_document_classification` intent로 라우팅한다.
- 확정 `fine_notice`만 `fine_notice_analysis`로 전달한다.
- 확정 `accident_evidence`는 사고 상담 상태에 첨부 근거로 연결하되, `text_ml_case_search`와 `law_ground_search`는 사실 확인 뒤에만 계획한다.
- `unknown`, low-confidence, adapter failure, scan-not-ready는 downstream Agent를 실행하지 않는다.
- 동영상은 이미지 분류 Agent로 보내지 않고 기존 `accident_evidence_analysis`와 Vision adapter를 사용한다.

### 4. 저장·로그·재시도

분류 결과에는 attachment ID, scan revision 또는 안전한 파일 식별자, 실행 ID, 결과 분류, confidence band, 상태, 오류 코드, 다음 행동, 시간만 저장한다. 같은 scan-ready 파일의 같은 revision은 결과를 재사용하며, 사용자의 명시적 재분류 요청만 새 실행을 만든다.

운영 trace는 수신·scan gate·분류 시작/완료/실패·확인·downstream handoff를 연결한다. 원문 OCR, 파일 경로, 파일 바이트, 개인정보, API secret은 로그와 persistence에서 제외한다.

## 실패 처리

| 상황 | 사용자 응답 | Agent 처리 |
|---|---|---|
| 스캔 미완료·거절 | 스캔 완료 대기 또는 재업로드 안내 | 분류와 검색을 실행하지 않음 |
| 지원하지 않는 형식 | JPEG/PNG/WebP/PDF 또는 MP4/MOV 안내 | 등록 단계에서 차단 |
| OCR·분류 adapter 실패 | 재시도 또는 목적 수정 안내 | 안전한 오류 코드만 반환 |
| 분류 불명·낮은 신뢰도 | 고지서/사고 증거 목적 확인 또는 더 선명한 자료 요청 | 법령·판례·이의신청을 실행하지 않음 |
| 사고 사실 미확인 | 필요한 사실과 이유를 질문 | 검색·과실 분석을 실행하지 않음 |

## 검증 기준

1. PDF 고지서: 분류 확인 후 기존 OCR 확인이 없으면 법령·이의신청이 실행되지 않는다.
2. 사고 사진: 분류 확인 후 사고 사실 확인 전에는 검색이 실행되지 않고, 확인 뒤 `text_ml_case_search`와 `law_ground_search`가 계획된다.
3. 블랙박스 영상: 기존 Vision adapter 또는 안전한 실패가 실제 plan·trace에 나타난다.
4. 지원하지 않는 파일과 분류 불명 파일: downstream 실행 없이 재시도 안내를 반환한다.
5. 분류 결과·Agent trace·저장 metadata에 OCR 원문, 파일 바이트, 저장 URI, 개인정보, secret이 없다.
6. 기존 고지서 OCR, 교통사고 사실확인원 OCR, Vision, 이의신청 및 보고서 생성 회귀 테스트가 모두 통과한다.

## 충돌 방지 결정

- `fine_notice_analysis`를 일반 이미지 분류기로 재사용하지 않는다. 해당 Agent는 고지서 전용 추출·거절 규칙을 가진다.
- 이미지에서 과실률이나 법적 결론을 만들지 않는다.
- 클라이언트가 전송한 분류 확인만으로 라우팅을 열지 않는다. 서버가 기록한 scan-ready 분류 결과가 필요하다.
- `attachment_document_classification`은 보고서 생성 node를 포함하지 않는다.
