# 운영 로그 개인정보 노출 회귀 방지 구현 계획

**목표:** Supervisor 런타임 스모크 결과, 채팅, 파일 스캔, 이의신청 문서 생성 Agent, Worker 처리 경계에서 개인정보, 스토리지 경로, 비밀값 원문이 운영 로그나 반환 DTO에 남지 않도록 고정한다.

**구현 방향:** 기존 Logger와 Worker의 응답 계약은 유지한다. Supervisor 스모크의 `reason`만 허용 목록 기반 코드로 정규화하고, 나머지 경계는 실제 Logger 캡처와 DB에 저장된 Worker 실패 상태를 검사하는 회귀 테스트로 현재의 비노출 동작을 고정한다. 전역 로그 필터, CloudWatch 설정, 외부 Provider 호출은 추가하지 않는다.

**기술 요소:** Python 3.13, Django `TestCase`, 표준 라이브러리 로그 캡처, `unittest.mock`, pytest, Django test runner

## 공통 제약

- OCR, 법령 검색, RAG 등 다른 담당 영역의 도메인 규칙은 수정하지 않는다.
- 전역 `LOGGING`, CloudWatch, 보존 정책, 객체 스토리지, Provider 설정을 추가하거나 변경하지 않는다.
- 테스트는 가짜 클라이언트, 패치, 테스트 DB만 이용하며 Provider, S3, 유료 서비스, 운영 데이터에 연결하지 않는다.
- 민감 예외에는 이름, 전화번호, 주민등록번호, 주소, 차량번호, 원본 파일명, Windows 경로, S3 URI, 비밀 토큰을 함께 넣는다.
- 관측 가능한 값은 고정된 상태/사유 코드, 예외 클래스명, 고정 실패 문구, 분류/개수 메타데이터, 불투명 ID로 제한한다.
- 스모크 `reason` 허용값은 `ok`, `disabled`, `missing_config`, `provider_unavailable`, `invalid_contract`뿐이다. 그 외 값은 모두 `unspecified`으로 변환한다.

---

## 작업 A: Supervisor 런타임 스모크 사유 코드 정규화

**수정 파일**

- `backend/chatbot/management/commands/smoke_supervisor_conversation_runtime.py:174-177`
- `backend/chatbot/test_supervisor_conversation_runtime_smoke.py:18-34`

**계약**

`supervisor_state["llm"]`에는 `status`, `reason`, `provider`, `model`이 들어올 수 있다. 공개 스모크 DTO에는 `status`와 안전한 사유 코드만 남기고 `provider`, `model`, 임의 원문 사유는 노출하지 않는다.

- [x] A-1. `_safe_llm()`에 원문 민감값이 담긴 `reason`을 전달했을 때 `{"status": "failed", "reason": "unspecified"}`만 반환하는 실패 테스트를 먼저 작성한다.
- [x] A-2. 그 단일 테스트가 현재 코드에서 원문 `reason`을 반환해 실패하는지 확인한다.
- [x] A-3. 아래처럼 허용값 집합과 `_safe_llm_reason()`을 추가한다. `status == "disabled"`이면 원본 사유와 무관하게 `disabled`로 반환한다.

  ```python
  SAFE_LLM_REASON_CODES = frozenset(
      {"ok", "disabled", "missing_config", "provider_unavailable", "invalid_contract"}
  )


  def _safe_llm_reason(status: object, reason: object) -> str:
      if str(status or "").strip().lower() == "disabled":
          return "disabled"
      normalized_reason = str(reason or "").strip().lower()
      if normalized_reason in SAFE_LLM_REASON_CODES:
          return normalized_reason
      return "unspecified"
  ```

- [x] A-4. `_safe_llm()`은 다음 두 필드만 반환하도록 최소 변경한다.

  ```python
  def _safe_llm(supervisor_state) -> dict:
      llm = supervisor_state.get("llm") if isinstance(supervisor_state, dict) else {}
      llm = llm if isinstance(llm, dict) else {}
      status = str(llm.get("status") or "")
      return {"status": status, "reason": _safe_llm_reason(status, llm.get("reason"))}
  ```

- [x] A-5. 원문 사유 차단, 허용 코드(`missing_config`) 유지, 비활성 상태(`disabled`) 변환을 각각 검사하고 스모크 테스트 모듈 전체를 실행한다.

  ```powershell
  & 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend\manage.py test chatbot.test_supervisor_conversation_runtime_smoke -v 1
  ```

- [x] A-6. 테스트와 최소 구현을 `fix: sanitize supervisor smoke reason` 커밋으로 분리한다.

## 작업 B: 운영 출력의 개인정보 비노출 회귀 테스트

**신규 파일**

- `backend/chatbot/test_operational_log_privacy.py`

**검증 경계**

- 채팅 분석 예약 실패: `chatbot.views.analysis_jobs(request)`
- 첨부파일 스캔 실패: `chatbot.file_scan_service.scan_uploaded_file(uploaded_file)`
- 이의신청 문서 Agent Provider 실패: `objection_report_generation.agent._draft_petition_text(...)`
- Worker 실패 영속화: `chatbot.repositories._fail_agent_work_item(...)`

**공통 테스트 값**

```python
SENSITIVE_MARKERS = (
    "Kim Hye-rim",
    "010-1234-5678",
    "900101-1234567",
    "123 Test-ro",
    "12A3456",
    "fine-notice.png",
    "C:\\private\\fine-notice.png",
    "s3://private-bucket/fine-notice.png",
    "sk-private-token",
)


def _private_exception() -> RuntimeError:
    return RuntimeError(" | ".join(SENSITIVE_MARKERS))
```

- [x] B-1. `OperationalLogPrivacyTests`에 `assert_no_raw_markers()`를 만들고, 위 민감값을 파일명과 URI로 사용하는 테스트용 `UploadedFile`을 만든다. 파일은 `uploaded`/`not_started` 상태의 테스트 DB 레코드만 사용한다.
- [x] B-2. 분석 예약에서 `reserve_analysis_job_request`가 민감 예외를 내도록 패치하고 `chatbot.views` Logger를 캡처한다. 응답은 `503`, 로그에는 `analysis job reservation failed error_type=RuntimeError`만 포함되고 모든 민감값은 없어야 한다.
- [x] B-3. 파일 스캔은 `_source_snapshot_for_scan`을 `b""`으로 패치하고 `build_file_scan_result`에서 민감 예외를 발생시킨다. `chatbot.file_scan_service` Logger에는 `file scan failed error_type=RuntimeError`만 남아야 한다.
- [x] B-4. 이의신청 문서 Agent의 `_openai_client`를 민감 예외를 내는 가짜 클라이언트로 패치한다. Logger에는 `objection petition drafting failed; error_class=RuntimeError`만 남고 프롬프트/예외 원문은 없어야 한다.
- [x] B-5. 위 세 테스트를 먼저 실행한다. 이들은 기존 안전 동작을 특성화하는 테스트이므로, 코드 변경 전부터 외부 호출 없이 통과해야 한다.

  ```powershell
  & 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend\manage.py test chatbot.test_operational_log_privacy.OperationalLogPrivacyTests.test_analysis_job_reservation_failure_logs_only_error_type chatbot.test_operational_log_privacy.OperationalLogPrivacyTests.test_file_scan_failure_log_excludes_uploaded_file_identifiers chatbot.test_operational_log_privacy.OperationalLogPrivacyTests.test_objection_draft_provider_failure_log_excludes_prompt_and_exception_text -v 1
  ```

- [x] B-6. 활성 `ChatSession`, 실행 중인 `AnalysisJob`, 시도 횟수가 제한에 도달한 `AgentWorkItem`을 만든다. `write_analysis_job_progress`와 `write_chat_session_state`만 패치하고 `_fail_agent_work_item()`에 민감 예외를 준다.
- [x] B-7. 반환값, `work_item.result`, `job.progress_message`, 마지막 `AnalysisJobEvent.metadata`에서 모든 민감값이 없는지 검사한다. `error_code == "RuntimeError"`, Worker 메시지와 진행 메시지는 기존의 고정 문구인지도 함께 검사한다.
- [x] B-8. 신규 테스트 모듈 전체를 실행하고 `test: cover operational log pii boundaries` 커밋으로 분리한다.

  ```powershell
  & 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend\manage.py test chatbot.test_operational_log_privacy -v 1
  ```

## 작업 C: 체크리스트와 회귀 검증

**수정 파일**

- `docs/ops/project-readiness-master-checklist.md:57`

- [x] C-1. 운영 로그 개인정보 노출 회귀 테스트 행만 `[~]`로 바꾸고 `#249`를 추가한다. PR 병합과 필수 CI 통과 전에는 `[x]`로 바꾸지 않는다.
- [x] C-2. 개인정보 계약과 Supervisor 스모크를 함께 실행한다.

  ```powershell
  & 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' backend\manage.py test chatbot.test_operational_log_privacy chatbot.test_supervisor_conversation_runtime_smoke -v 1
  & 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q test/test_chat_input_privacy.py test/test_ocr_privacy_contract.py --timeout=30
  ```

- [x] C-3. 전체 pytest, 공백 오류, 변경 범위를 확인한다. 이 작업으로 Provider, S3, 유료 서비스가 호출되면 안 된다.

  ```powershell
  & 'D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe' -m pytest -q --timeout=30
  git diff --check origin/dev...HEAD
  git status -sb
  ```

- [x] C-4. 체크리스트 변경을 `docs: track operational log pii regression` 커밋으로 분리한다.
