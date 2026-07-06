# PR #99 머지 컨펌 검토 메모

- 대상 PR: https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/pull/99
- PR 제목: `Feat/fine notice ocr intake flow2`
- 기준 브랜치: `dev`
- 헤드 브랜치: `feat/fine-notice-ocr-intake-flow2`
- 검토일: 2026-06-30
- 검토 결론: 조건부 머지 가능. 단, 머지 직후 후속 수정이 필요하다.

## 한 줄 결론

PR #99는 과태료/범칙금 고지서 OCR Agent의 방향성과 코드 분리는 괜찮지만, 의존성 선언, 테스트 안정성, 예외 처리, 기존 서비스 흐름 연결이 부족하다. 그래서 `dev` 안정성을 최우선으로 보면 머지 전 수정이 맞고, 구현 속도와 팀 작업 공유를 우선하면 머지 후 즉시 follow-up 수정으로 처리해도 된다.

## 머지해도 된다고 본 이유

1. GitHub PR 상태상 `mergeable=true`로 확인되었다.
2. 변경 범위가 기존 Django API나 DB migration을 직접 깨뜨리는 형태가 아니라, 새 `ai/agents/fine_notice_analysis/` 패키지를 추가하는 방식이다.
3. 코드 구조가 `agent.py`, `evaluator.py`, `graph.py`, `masking.py`, `prompts.py`, `state.py`, `utils.py`, `verification.py`로 분리되어 있어 후속 수정하기 쉽다.
4. 과태료와 범칙금을 분류하고, 범칙금은 이의신청 불가로 분기하는 방향이 프로젝트 도메인 요구와 맞다.
5. `agent_results.fine_notice_analysis` envelope를 반환하려는 구조가 기존 Supervisor/Agent 결과 설계와 크게 충돌하지 않는다.
6. 이 PR은 완성된 운영 기능이라기보다 OCR Agent 구현 기반을 먼저 올리는 성격이 강하므로, 팀이 같은 기준선에서 후속 통합 작업을 진행하기에 유용하다.

## 바로 머지하면 위험한 이유

### 1. 의존성 선언이 빠져 있다

새 코드에서 다음 라이브러리를 import한다.

- `fitz`, 즉 PyMuPDF
- `openai`
- `langgraph`
- `dotenv`, 즉 python-dotenv
- `typing_extensions`

그런데 PR diff에는 requirements 또는 lockfile 변경이 보이지 않았다. 따라서 새 환경에서 `pytest`를 실행하거나 Agent를 import하면 `ModuleNotFoundError`가 날 수 있다.

특히 `test/test_fine_notice_ocr.py`는 테스트 skip 조건을 두고 있지만, 그 전에 `from ai.agents.fine_notice_analysis.graph import graph`를 import한다. 즉 `OPENAI_API_KEY`가 없어 테스트가 skip될 상황이어도, 의존성이 없으면 수집 단계에서 먼저 실패할 수 있다.

### 2. 테스트 입력 파일 정책이 불안정하다

PR은 `.gitignore`에 `서식문서/`를 추가한다. 그런데 새 테스트는 `서식문서` 폴더의 PDF 파일들을 읽는다.

즉, 로컬 작성자 환경에는 PDF가 있어서 테스트가 통과할 수 있지만, 저장소를 새로 clone한 환경이나 CI에는 해당 파일이 없을 가능성이 높다. `OPENAI_API_KEY`가 설정된 환경에서는 파일 누락으로 테스트 실패가 날 수 있다.

### 3. 테스트가 실제 GPT 호출에 의존한다

`test/test_fine_notice_ocr.py`는 실제 GPT-4o Vision 호출을 전제로 한다. 이 방식은 통합 테스트로는 의미가 있지만, 기본 회귀 테스트로는 불안정하다.

문제점은 다음과 같다.

- API 키가 필요하다.
- 네트워크와 외부 API 상태에 영향을 받는다.
- 모델 출력이 매번 완전히 동일하다고 보장하기 어렵다.
- 비용이 발생할 수 있다.
- CI에서 재현성이 낮다.

따라서 기본 테스트에는 mock 기반 단위 테스트가 필요하고, 실제 GPT 호출 테스트는 별도 opt-in 테스트로 분리하는 편이 안전하다.

### 4. 입력 예외 처리가 부족하다

`ocr_node`에서 `base64.b64decode(notice_image)`를 바로 실행한다. 잘못된 base64 문자열이 들어오면 현재는 `failed` envelope를 반환하지 못하고 예외로 터질 수 있다.

PDF도 마찬가지로 `fitz.open(...)` 과정에서 손상된 PDF가 들어오면 `ValueError` 외 예외가 발생할 수 있다. 업로드 OCR 경계에서는 사용자가 깨진 파일을 올릴 수 있으므로, 이런 입력은 서버 예외가 아니라 `ocr_status=failed`와 재업로드 안내로 처리되어야 한다.

### 5. 기존 서비스 흐름에 아직 연결되지 않았다

PR은 `ai/agents/fine_notice_analysis` 패키지를 추가하지만, 기존 Django 분석 job 흐름이나 `app/services/agent_node_service.py`의 mock 실행 경로와 직접 연결하는 변경은 보이지 않는다.

따라서 머지 직후 사용자 화면에서 이 OCR Agent가 실제로 호출된다고 보기는 어렵다. 현재 상태는 독립 Agent prototype 또는 기반 코드에 가깝다.

## 권장 판단

### dev 안정성을 최우선으로 볼 때

머지 전 수정 요청이 맞다.

필수 수정은 다음 네 가지다.

1. requirements 또는 lockfile에 필요한 의존성을 추가한다.
2. `test/test_fine_notice_ocr.py`의 import/skip 구조를 고쳐 의존성 누락이나 API 키 미설정 시 테스트 수집이 깨지지 않게 한다.
3. `서식문서/` fixture 정책을 정리한다. 테스트에 필요한 샘플은 저장소에 포함하거나, 테스트를 명확히 opt-in으로 분리한다.
4. invalid base64, 손상 PDF, OpenAI 응답 오류를 `failed` envelope로 안정 처리한다.

### 팀 속도를 우선할 때

머지 후 바로 수정해도 된다.

이 경우 조건은 명확하다.

- 머지 후 방치하지 않는다.
- 바로 follow-up 브랜치를 열어 테스트/의존성/예외 처리부터 정리한다.
- 이 PR을 완성 기능이 아니라 OCR Agent 기반 코드로 간주한다.

## 머지 후 바로 해야 할 수정 순서

1. 의존성 선언 정리
   - PyMuPDF
   - openai
   - langgraph
   - python-dotenv
   - typing_extensions

2. 테스트 안정화
   - `OPENAI_API_KEY` skip 전에 heavy import가 실행되지 않게 수정한다.
   - GPT 호출 테스트는 opt-in 또는 integration marker로 분리한다.
   - `_classify_fine_type`, `evaluate_ocr`, `confidence_verification_node`, missing image 경로는 mock 기반 단위 테스트로 추가한다.

3. 입력 예외 처리
   - invalid base64
   - 손상 PDF
   - 10페이지 초과 PDF
   - GPT JSON 파싱 실패
   - OpenAI API 호출 실패

4. 기존 분석 흐름 연결 여부 결정
   - `app/services/agent_node_service.py`의 `fine_notice_analysis` mock 결과를 새 Agent로 대체할지 결정한다.
   - 바로 대체하지 않을 거면 experimental Agent임을 README나 docs에 명시한다.

5. 보안/개인정보 처리 강화
   - 차량번호 외 전화번호, 계좌번호, 주소 등 추가 마스킹 필요 여부를 확인한다.
   - GPT raw 응답 저장 금지 원칙을 명확히 한다.

## 추천 코멘트 예시

```md
검토했습니다. 이 PR은 `fine_notice_analysis` OCR Agent의 기반 코드로는 방향이 좋고, 과태료/범칙금 분기와 Agent envelope 구조도 기존 설계와 맞습니다. 그래서 팀 작업 공유를 위해 머지 자체는 가능하다고 봅니다.

다만 현재 상태는 운영 기능 완료라기보다는 prototype/base 구현에 가깝습니다. 머지 후 바로 후속 수정이 필요합니다.

확인된 후속 작업:
- `fitz/PyMuPDF`, `openai`, `langgraph`, `python-dotenv`, `typing_extensions` 의존성 선언 필요
- `test/test_fine_notice_ocr.py`가 skip 전에 Agent를 import해서 의존성 누락 시 테스트 수집이 깨질 수 있음
- 테스트가 `.gitignore` 처리된 `서식문서/` PDF에 의존하므로 fresh clone/CI에서 불안정함
- 실제 GPT 호출 테스트는 opt-in integration test로 분리하고, 핵심 분류/검증 로직은 mock 단위 테스트 필요
- invalid base64, 손상 PDF 입력을 `failed` envelope로 처리하는 예외 처리가 필요
- 기존 analysis job/Supervisor 실행 흐름과 실제 연결 여부를 후속 PR에서 결정해야 함

결론: 머지 가능하나, 머지 직후 follow-up으로 테스트/의존성/예외 처리부터 정리하는 조건부 승인 의견입니다.
```

## 최종 결론

PR #99는 머지를 절대 막아야 하는 수준의 위험은 아니다. 다만 `dev`를 항상 테스트 통과 상태로 유지해야 한다면 머지 전 수정이 맞다. 팀 속도를 우선하고 후속 수정을 바로 할 수 있다면, 조건부로 머지해도 괜찮다.
