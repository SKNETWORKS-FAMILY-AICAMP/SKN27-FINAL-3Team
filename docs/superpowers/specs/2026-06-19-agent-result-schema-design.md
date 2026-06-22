# Agent 결과 Schema 및 RAG 계약 설계

## 1. 설계 목적

`#22 feat-agent-result-schema-and-rag-contract`의 목적은 모든 분석 노드가 Supervisor에 전달할 결과 구조를 통일하는 것이다.

다음 주 구현자는 각 노드의 내부 구현을 추측하지 않고, 이 문서의 공통 결과 envelope과 노드별 `structured_result` 기준에 맞춰 개발을 시작한다.

## 2. 적용 범위

| 포함 | 제외 |
|---|---|
| 공통 결과 envelope | 실제 Agent 구현 코드 |
| evidence/RAG metadata 계약 | 실제 RAG index 구축 |
| 노드별 input/output 설계 | 실제 OCR, ML, DL 모델 확정 |
| 상태값과 실패 처리 기준 | API endpoint 최종 확정 |
| Supervisor 병합 기준 | UI 상세 구현 |

## 3. 정식 노드 명칭

임의 약칭을 쓰지 않는다. 문서와 회의에서는 아래 정식 명칭을 사용한다.

| 정식 명칭 | 코드 식별값 후보 | 담당 |
|---|---|---|
| 고지서 OCR·과태료/범칙금 분석 노드 | `fine_notice_analysis` | 필주 |
| 법률 근거 검색 노드 | `law_ground_search` | 동혁 |
| 텍스트 ML/판례·사례 검색 노드 | `text_ml_case_search` | 재강 |
| 영상·이미지 분석 노드 | `vision_media_analysis` | 주희 |
| 이의신청서 생성/리포트 노드 | `objection_report_generation` | 요청자 |

코드 식별값은 오늘 회의에서 최종 결정해야 한다. 기존 문서의 `fine`, `law`, `text_ml`, `vision`, `objection` 값은 짧지만 의미가 모호할 수 있으므로 구현 전 팀 합의가 필요하다.

## 4. 공통 결과 Envelope

모든 노드는 아래 구조를 반환한다. 최종 자연어 답변은 개별 노드가 아니라 Supervisor가 생성한다.

```json
{
  "node_name": "고지서 OCR·과태료/범칙금 분석 노드",
  "node_code": "fine_notice_analysis",
  "status": "success",
  "summary": "사용자에게 보여줄 수 있는 짧은 요약",
  "structured_result": {},
  "evidence": [],
  "next_actions": [],
  "limitations": []
}
```

## 5. 공통 필드 정의

| 필드 | 타입 | 필수 | 설명 | 검증 기준 |
|---|---|---:|---|---|
| `node_name` | string | 예 | 사람이 읽는 정식 노드명 | 정식 명칭 표와 일치 |
| `node_code` | string | 예 | API와 Supervisor가 사용하는 식별값 | 팀 합의 후 enum 고정 |
| `status` | string | 예 | 처리 상태 | `success`, `partial`, `failed` 중 하나 |
| `summary` | string | 예 | Supervisor가 최종 답변에 병합할 요약 | 법률 단정, 성공 보장, 과실비율 수치 확정 금지 |
| `structured_result` | object | 예 | 노드별 구조화 결과 | 노드별 schema 적용 |
| `evidence` | array | 예 | 근거 목록 | 근거가 없으면 빈 배열과 `limitations` 사유를 같이 반환 |
| `next_actions` | array | 예 | 사용자 후속 행동 | 추가 질문, 추가 업로드, 문서 생성, 리포트 확인 등 |
| `limitations` | array | 예 | 한계와 검증 필요 사항 | 입력 부족, 근거 부족, 모델 미확정, confidence 낮음 등 |

## 6. Evidence 계약

```json
{
  "source_type": "law",
  "title": "도로교통법 관련 조항",
  "source_reference": "원문 URL 또는 내부 문서 ID",
  "metadata": {},
  "confidence": 0.82
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `source_type` | string | 예 | 근거 출처 유형 |
| `title` | string | 예 | 사용자가 이해할 수 있는 근거 제목 |
| `source_reference` | string | 조건부 | 원문 URL, 내부 문서 ID, 업로드 파일 ID |
| `metadata` | object | 예 | 출처별 상세 metadata |
| `confidence` | number 또는 null | 조건부 | 모델 또는 검색 confidence. 산출 불가 시 null |

### 6.1 source_type 후보

| source_type | 설명 | 담당 연결 |
|---|---|---|
| `law` | 법령, 시행령, 시행규칙, 행정 기준, 고시 | 동혁 |
| `precedent` | 판례 | 재강 |
| `caption_case` | 유튜브 자막 기반 사고 사례 | 재강 |
| `review_case` | 과실비율심의사례 | 재강 |
| `fine_rule` | 과태료·범칙금·벌칙 분석용 룰/매핑 데이터 | 필주 |
| `vision_result` | 영상·이미지 분석 결과 | 주희 |
| `user_uploaded_file` | 사용자 업로드 고지서, 사진, 영상, 문서 | 관련 노드 |

### 6.2 metadata 권장 필드

| source_type | metadata 권장 필드 |
|---|---|
| `law` | `law_name`, `article`, `paragraph`, `item`, `effective_date`, `retrieved_at`, `jurisdiction` |
| `precedent` | `case_id`, `court`, `decision_date`, `issue_tags`, `similarity_score` |
| `caption_case` | `video_id`, `channel`, `timestamp_range`, `accident_type_candidate` |
| `review_case` | `case_source`, `case_type`, `ratio_label`, `issue_tags` |
| `fine_rule` | `violation_type`, `notice_type`, `fine_amount`, `penalty_point`, `rule_version` |
| `vision_result` | `file_id`, `frame_range`, `detected_objects`, `scene_label`, `confidence_label` |
| `user_uploaded_file` | `file_id`, `file_type`, `ocr_status`, `uploaded_at` |

## 7. 노드별 structured_result 설계

### 7.1 고지서 OCR·과태료/범칙금 분석 노드

| 구분 | 필드 |
|---|---|
| Input | `notice_image_id`, `ocr_text`, `notice_type`, `violation_datetime`, `violation_location`, `violation_type`, `notice_date`, `payment_deadline`, `agency`, `payment_status`, `user_context` |
| structured_result | `notice_fields`, `ocr_status`, `ocr_confidence`, `missing_fields`, `disposition_stage`, `objection_possibility_label`, `required_documents`, `required_evidence` |
| evidence | `user_uploaded_file`, `fine_rule`, 필요 시 `law` |
| next_actions | `법률 근거 확인`, `누락 필드 보완`, `이의신청서 초안 생성`, `추가 증거 업로드` |
| limitations | OCR 신뢰도 낮음, 납부기한 불명확, 관할 기관 불명확, 법률 근거 미확인 |

### 7.2 법률 근거 검색 노드

| 구분 | 필드 |
|---|---|
| Input | `query`, `violation_type`, `law_scope`, `jurisdiction`, `effective_date`, `related_notice_fields` |
| structured_result | `matched_laws`, `applicable_conditions`, `exceptions`, `unmatched_terms`, `retrieval_quality` |
| evidence | `law` |
| next_actions | `고지서 OCR·과태료/범칙금 분석 결과와 병합`, `추가 법령 범위 확인`, `법률 근거 부족 안내` |
| limitations | 판례 아님, 법률 원문 업데이트 여부 검증 필요, 조문 적용 여부는 최종 법률 판단 아님 |

### 7.3 텍스트 ML/판례·사례 검색 노드

| 구분 | 필드 |
|---|---|
| Input | `accident_description`, `statement_ocr_text`, `issue_tags`, `uploaded_text_files`, `search_scope` |
| structured_result | `normalized_description`, `accident_type_candidates`, `issue_tags`, `evidence_tags`, `similar_cases`, `summary_for_rag` |
| evidence | `precedent`, `caption_case`, `review_case`, 필요 시 `law` |
| next_actions | `추가 질문`, `사진/영상 업로드 요청`, `리포트 생성`, `법률 근거 병합` |
| limitations | 과실비율 수치 확정 금지, 판례 유사도는 참고값, 학습/검색 데이터 범위 검증 필요 |

### 7.4 영상·이미지 분석 노드

| 구분 | 필드 |
|---|---|
| Input | `image_ids`, `video_ids`, `frame_metadata`, `user_description`, `analysis_goal` |
| structured_result | `key_frames`, `scene_summary`, `detected_objects`, `accident_scene_candidates`, `confidence_label`, `quality_issues` |
| evidence | `vision_result`, `user_uploaded_file` |
| next_actions | `선명한 원본 재업로드`, `사고 설명 보완`, `텍스트 ML/판례·사례 검색 노드 병합`, `리포트 근거 반영` |
| limitations | 영상 품질 낮음, 프레임 누락, 객체 탐지 실패, 사고 책임 확정 불가 |

### 7.5 이의신청서 생성/리포트 노드

| 구분 | 필드 |
|---|---|
| Input | `notice_analysis_result`, `law_ground_result`, `user_facts`, `additional_explanation`, `attachments` |
| structured_result | `recipient_agency`, `document_title`, `case_summary`, `violation_summary`, `objection_purpose`, `grounds`, `attachment_list`, `disclaimer` |
| evidence | `law`, `fine_rule`, `user_uploaded_file` |
| next_actions | `사용자 사실관계 검토`, `첨부 증거 추가`, `초안 복사`, `문서 다운로드` |
| limitations | 제출 가능성 보장 금지, 사용자 사실관계 부족, 관할 기관 양식 차이 가능 |

## 8. 상태값 처리

| status | 사용 조건 | Supervisor 처리 |
|---|---|---|
| `success` | 필수 입력과 근거가 충분하고 구조화 결과가 생성됨 | 최종 답변에 요약과 근거 포함 |
| `partial` | 일부 필드 누락, 근거 부족, 신뢰도 낮음, 추가 질문 필요 | 한계와 다음 행동을 우선 표시 |
| `failed` | 실행 실패, 입력 형식 오류, 필수 데이터 없음 | 재업로드, 재입력, 다른 흐름 안내 |

## 9. Supervisor 병합 규칙

1. `failed` 결과는 최종 판단 근거로 쓰지 않는다.
2. `partial` 결과는 `limitations`와 함께만 표시한다.
3. 법률 근거가 없는 이의제기 가능성 판단은 확정 표현으로 쓰지 않는다.
4. 과실비율 결과는 수치가 아니라 정성 라벨, 쟁점, 유사 사례로 표시한다.
5. evidence가 없는 summary는 사용자에게 단정적으로 표시하지 않는다.
6. 이의신청서 생성/리포트 노드는 고지서 OCR·과태료/범칙금 분석 결과, 법률 근거, 사용자 사실관계가 있을 때만 호출한다.

## 10. 검증 기준

| 검증 항목 | 방법 | 통과 기준 |
|---|---|---|
| 공통 필드 존재 | 샘플 JSON 검토 | 모든 노드 결과에 7개 공통 필드 존재 |
| 정식 명칭 사용 | 문서 검색 | 임의 약칭 없음 |
| evidence metadata | source_type별 샘플 검토 | 필수 metadata 누락 없음 |
| limitations 처리 | partial/failed 샘플 검토 | 한계와 다음 행동이 함께 제공 |
| 단정 표현 방지 | summary 문구 검토 | 법률 판단, 성공 보장, 과실비율 수치 확정 표현 없음 |

## 11. 회의에서 결정할 항목

| 항목 | 현재 설계안 | 결정 필요 |
|---|---|---|
| 코드 식별값 | 긴 설명형 코드값 사용 | 팀 합의 필요 |
| 공통 필드 | 7개 필드 사용 | 팀 합의 필요 |
| status | `success`, `partial`, `failed` | 팀 합의 필요 |
| evidence source_type | 7개 후보 사용 | 담당자별 추가 필요 여부 확인 |
| API 응답 envelope | Agent 결과 envelope과 유사하게 구성 | Backend 설계와 연결 필요 |

## 12. 다음 단계

이 설계가 승인되면 `docs/issues/22-agent-result-schema-and-rag-contract.md`를 정식 명칭 기준으로 정리하고, `#29` Supervisor 라우팅 문서가 이 계약을 참조하도록 연결한다.
