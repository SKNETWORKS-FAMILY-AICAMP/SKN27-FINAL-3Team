# #294 채팅 첨부 분류와 실제 Agent handoff 연결 설계

## 목적과 범위

채팅에서 이미지, PDF, 영상을 드래그앤드롭으로 업로드하고, 스캔이 완료된 자료만 실제 Agent에 전달한다. 영상은 기존 Vision 파이프라인을 실제 Worker adapter로 연결하고, 이미지와 PDF는 기존 고지서 OCR로 분류한다. 분류 결과와 사용자 맥락에 따라 과태료/범칙금 절차 또는 과실 관련 사례·법령 검색으로 이어간다.

이번 이슈는 새 Vision 모델·공급자·학습·정확도 개선을 포함하지 않는다. 이미지용 새 Vision 모델도 추가하지 않는다. OCR 결과 입력 UI의 상세 편집 화면은 E4 후속 범위이며, 이 이슈는 그 화면이 사용할 `requires_confirmation` 상태와 다음 단계 차단을 보존한다.

## 설계 검토 기록

### 1차: 이슈 의도 일치

- #294의 실제 Agent handoff, 안전한 실패 이유, 첨부 분기, 실행 추적 요구를 충족한다.
- 기존 Vision 구현을 사용하므로 모델 성능 개선 작업으로 범위가 넓어지지 않는다.
- 데이터 자동 적재와 전체 E 화면 개편은 제외한다.

### 2차: 기존 구현 충돌과 대응

| 확인 사항 | 현재 상태 | 대응 |
| --- | --- | --- |
| Vision 실행 | `ai/vision/run_to_supervisor.py`는 CLI/파일 산출물 중심이며 Worker adapter가 없다. | 서비스 호출용 wrapper와 안정된 결과 envelope를 만든다. |
| Mock 경로 | `vision_media_analysis`가 `DL_MOCK_NODE_CODES`에 있어 항상 mock 실행된다. | 실제 adapter 등록 후 해당 노드의 mock 강제를 제거한다. |
| 라우팅 | `supervisor_routing_policy.v1.json`에 사고 정밀 분석 계획이 없다. | scan-ready 영상만 `accident_evidence_analysis` 전용 intent로 라우팅하고, `vision_media_analysis → text_ml_case_search → law_ground_search → agent_result_validation → final_response_merge` 계획을 추가한다. 기존 `accident_initial_consultation`의 사실확인·사건 승격 보류 흐름은 유지한다. |
| 프론트 | 파일 선택만 가능하고 `accept`에 영상과 DnD handler가 없다. | 채팅 입력 영역 DnD, 영상 MIME 허용, 업로드 상태를 추가한다. |
| 동시 실행 | Vision 산출물 경로가 파일명과 공용 디렉터리에 의존한다. | `job_id`와 `execution_id`별 작업 경로를 사용한다. |
| 개인정보·운영 로그 | `AgentResult.raw_output`에 전체 실행 결과가 저장될 수 있다. | 저장 전 원본·OCR 원문·경로·예외 원문을 제거한다. |

## 구성과 책임

1. **프론트 첨부 UX**
   - 채팅 입력 전체를 drop zone으로 만들고 이미지, PDF, MP4 등 허용 형식을 업로드 API로 보낸다.
   - 파일 선택과 DnD는 같은 업로드 함수를 사용한다.
   - 사용자가 고른 자료 목적은 힌트일 뿐이며 최종 분류 근거가 아니다.
   - 업로드, 검사 대기, 검사 차단, 분석 대기 상태를 명확히 보여 준다.

2. **첨부 보안 경계**
   - 기존 canonical scan gate를 통과한 `scan_ready` 자료만 Worker 실행 payload에 남긴다.
   - 차단, 미확인, 형식 불일치 자료는 Agent에 전달하지 않는다.

3. **분류와 Supervisor 계획**
   - 영상(`video/*`, `blackbox_video`)은 실제 Vision adapter를 우선 호출한다.
   - scan-ready 영상은 일반 `accident_initial_consultation`과 분리한 `accident_evidence_analysis` intent로만 계획을 생성한다. 이 계획은 `input_context_validation → vision_media_analysis → text_ml_case_search → law_ground_search → agent_result_validation → final_response_merge` 순서이며, 결과 상태는 항상 증거 분석의 `partial`이다.
   - `accident_evidence_analysis`는 영상에서 식별한 사실·검색 근거만 제공한다. 과실비율, 법적 책임, 최종 사고유형, 이의신청·보고서 생성은 이 경로에서 결정하거나 실행하지 않는다. 텍스트·이미지 기반의 기존 초동상담은 사실 확인과 사건 승격 보류 절차를 계속 따른다.
   - 이미지와 PDF는 기존 `fine_notice_analysis` OCR로 고지서 여부와 과태료/범칙금을 확인한다.
   - 고지서 OCR이 성공하면 핵심 필드 사용자 확인 전에는 이의신청·법령 후속 단계를 실행하지 않는다.
   - 고지서가 아니고 사고 맥락이 확인되면 `text_ml_case_search`와 `law_ground_search`로 보낸다.
   - 자료 목적, MIME, OCR 결과, 사용자 맥락이 충돌하거나 부족하면 임의로 과실/과태료를 확정하지 않고 추가 질문을 반환한다.

4. **Vision 실제 adapter**
   - scan-ready object storage 자료를 Worker 전용 임시 경로에 준비한다.
   - 기존 `ai/vision/run_to_supervisor.py`의 VideoMAE → YOLO → Qwen → Supervisor handoff 흐름을 호출한다.
   - 파일 경로가 아니라 정규화된 Agent output을 반환하고, Vision handoff의 필요한 요약·증거 참조·한계만 `text_ml_case_search`와 `law_ground_search`에 upstream 결과로 전달한다.
   - Vision은 과실비율, 법적 책임, 최종 사고유형을 결정하지 않는다.

5. **실행 추적과 영속화 정제**
   - `AnalysisJob`, `AgentWorkItem`, `AgentResult`의 기존 식별자를 사용하고 모든 실행 trace에 `job_id`, `execution_id`, `attachment_id`, node code, 결과 상태, 소요 시간, 실패 코드만 기록한다.
   - DB에 보관하는 output과 이벤트에서는 파일 바이트, OCR 원문, 사용자 전체 문장, storage/local path, 비밀값, 예외 원문을 제거한다.

## 흐름

```text
Drag & Drop / 파일 선택
  → 업로드
  → 파일 검사 완료 여부 확인
  → AnalysisJob / AgentWorkItem
      ├─ 영상: `accident_evidence_analysis`
      │        → Vision 실제 adapter → text_ml_case_search → law_ground_search
      │        → agent_result_validation → final_response_merge (항상 partial, 보고서·과실판정 없음)
      └─ 이미지·PDF: 고지서 OCR
               ├─ 고지서: OCR 핵심 필드 확인 대기 → 법령/이의신청
               ├─ 사고 맥락: 과실 사례 검색 → 법령 검색
               └─ 불명확·충돌: 추가 질문
```

## 실패 처리

| 실패 코드 | 처리 |
| --- | --- |
| `attachment_not_scan_ready` | 분석을 시작하지 않고 검사 완료 또는 재업로드를 안내한다. |
| `unsupported_media_type` | 지원 형식 안내와 함께 차단한다. |
| `purpose_result_conflict` | 자료 목적을 확정하지 않고 추가 질문을 반환한다. |
| `vision_runtime_unavailable` | Vision 실행환경을 확인하되 사용자에게 내부 환경을 노출하지 않는다. |
| `vision_checkpoint_missing` | 체크포인트 미준비 상태로 실패하며 운영 trace에만 남긴다. |
| `vision_dependency_missing` | 배포 의존성 누락 상태로 실패하며 운영 trace에만 남긴다. |
| `vision_media_decode_failed` | 손상·미지원 영상으로 처리하고 재업로드를 안내한다. |
| `vision_execution_failed` | 안전한 일반 실패 응답과 재시도 경로를 제공한다. |

부분 성공 결과는 근거 부족 상태로 전달한다. Vision 실패·부분 성공 모두 과실비율, 법적 책임, 법령 위반을 확정하는 응답으로 변환하지 않는다.

## 검증 기준

1. DnD와 파일 선택 모두 이미지, PDF, MP4를 업로드하며 검사 전 자료는 실행 payload에 없다.
2. MP4가 mock이 아닌 실제 `vision_media_analysis` adapter를 호출하고, `accident_evidence_analysis`의 고정된 증거 분석 계획을 따라 검색 근거의 upstream 결과가 남는다. 이 응답에는 과실비율, 법적 결론, 보고서 생성 결과가 없다.
3. 체크포인트, 의존성, 해독 실패가 각각 안정된 실패 코드와 안전한 trace로 남는다.
4. 이미지·PDF 고지서는 기존 OCR이 분류하며 핵심 필드 확인 전에는 이의신청 흐름을 진행하지 않는다.
5. 목적과 MIME/OCR 결과가 불일치하거나 불명확하면 추가 질문으로 종료한다.
6. 영속화된 실행 결과와 로그에 원본 바이트, OCR 원문, 저장 경로, 비밀값, 예외 원문이 없는지 회귀 테스트한다.
7. CI는 Vision 호출을 대체한 계약 테스트를 실행하고, 실제 체크포인트와 실행환경이 준비된 곳에서만 단일 영상 smoke test를 별도로 실행한다.

## 완료 조건

- `vision_media_analysis`가 `mock`이 아닌 실제 adapter로 실행된다.
- scan-ready 영상은 `accident_evidence_analysis`의 증거 분석 계획으로만 실행되고 `partial` 결과를 반환한다. 기존 초동상담의 사실확인·사건 승격 보류 경로는 변경하지 않는다.
- 영상 성공, Vision 실행 불가, 고지서 OCR, 사고 자료, 목적 불일치, 검사 차단의 대표 흐름이 검증된다.
- 사용자 응답과 DB 저장 결과에 내부 경로·개인정보·비밀값이 노출되지 않는다.
- Vision 담당 변경사항과 #294 adapter 변경사항이 별도 요구사항 문서로 추적된다.
