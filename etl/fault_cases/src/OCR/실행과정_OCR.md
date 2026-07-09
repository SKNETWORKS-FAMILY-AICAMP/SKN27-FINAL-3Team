# 교통사고사실확인원 OCR 구현 진행 기록

## 진행 범위

이번 단계에서는 계획서 기준 1번부터 3번까지 진행했다.

1. OCR 구현 폴더 생성
2. `state.py` 작성
3. `utils.py` 작성

실제 OCR 실행, OpenAI API 호출, LangGraph 실행, 이미지 테스트는 아직 진행하지 않았다.

## 생성한 폴더

```text
etl/fault_cases/src/OCR/traffic_accident_confirmation_ocr/
```

### 이유

현재 단계에서는 PM 확인 전이므로 `ai/agents` 아래로 바로 올리지 않고, OCR 실험/구현 위치인 `etl/fault_cases/src/OCR` 아래에서 먼저 안정화한다.

## 생성한 파일

```text
etl/fault_cases/src/OCR/traffic_accident_confirmation_ocr/__init__.py
etl/fault_cases/src/OCR/traffic_accident_confirmation_ocr/state.py
etl/fault_cases/src/OCR/traffic_accident_confirmation_ocr/utils.py
etl/fault_cases/src/OCR/실행과정_OCR.md
```

## `state.py` 작성 내용

`TrafficAccidentConfirmationOCRState`를 정의했다.

주요 상태값은 다음과 같다.

```text
document_image
document_mime_type
source_filename
ocr_status
document_type
failure_reason
raw_text_redacted
extracted_fields
document_check
page_info
scene_diagram
quality
privacy
missing_fields
limitations
format_errors
agent_results
```

### 이유와 근거

LangGraph 노드들이 같은 key를 사용해야 이후 `agent.py`, `verification.py`, `graph.py` 구현이 흔들리지 않는다.
또한 `success`, `partial`, `failed` 상태와 `failure_reason` 값을 타입으로 제한하면 에러 코드가 코드 전체에서 일관되게 유지된다.

## `utils.py` 작성 내용

아래 유틸 함수를 작성했다.

```text
make_envelope
update_agent_results
save_ocr_output
```

### 이유와 근거

Supervisor는 여러 Agent 결과를 `agent_results[node_code]` 형태로 받는 구조가 필요하다.
따라서 OCR 결과도 동일한 envelope 형태로 정리한다.

또한 OCR 결과 JSON은 아래 경로에 저장하도록 했다.

```text
etl/fault_cases/artifacts/OCR_output/
```

저장 시 원본 이미지 base64가 남지 않도록 `document_image` key는 제거한다.

## 하드코딩 방지 기준

이번 코드에서는 다음 값을 상수 또는 함수 인자로 분리했다.

```text
NODE_NAME
NODE_CODE
DEFAULT_OUTPUT_DIR
SENSITIVE_OUTPUT_KEYS
```

`save_ocr_output`은 `output_dir` 인자를 받을 수 있으므로 테스트나 운영 환경에서 저장 위치를 바꿀 수 있다.

## 아직 실행하지 않은 것

아래 작업은 아직 실행하지 않았다.

```text
OpenAI API 호출
실제 OCR
LangGraph 실행
raw/1page 이미지 테스트
gpt-5.4-mini / gpt-4o 비교
```

## 나중에 실행할 수 있는 확인 명령

PowerShell에서 파일 생성 여부만 확인하려면 아래 명령을 실행한다.

```powershell
Get-ChildItem -LiteralPath "etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr" -Force
```

예상 결과:

```text
__init__.py
state.py
utils.py
```

Python 문법 오류만 확인하려면 아래 명령을 실행한다.

```powershell
python -m py_compile `
  etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr\state.py `
  etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr\utils.py
```

예상 결과:

```text
아무 출력이 없으면 문법 오류 없음
```

`save_ocr_output` 저장 동작을 수동 확인하려면 아래처럼 실행할 수 있다.

```powershell
python -c "from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.utils import save_ocr_output; print(save_ocr_output({'status':'success','document_image':'base64_should_not_be_saved'}, 'sample.png'))"
```

예상 결과:

```text
etl\fault_cases\artifacts\OCR_output\YYYYMMDD_HHMMSS_SSS_sample_success_XXXXXXXX.json
```

저장된 JSON에는 `document_image`가 없어야 한다.

## 다음 단계

다음에 진행할 작업은 아래 순서다.

1. `agent.py` 작성
2. `verification.py` 작성
3. `graph.py` 작성
4. mock 테스트 작성
5. 실제 이미지 smoke test

## 4~6번 진행 내용

이번 단계에서는 계획 기준 4번부터 6번까지 작성했다.

4. `prompts.py` 작성
5. `masking.py` 작성
6. `evaluator.py` 작성
7. `constants.py` 작성 및 상태/실패사유 문자열 공통 상수화

아직 실제 OCR 실행, OpenAI API 호출, LangGraph 실행, 이미지 smoke test는 진행하지 않았다.

### `prompts.py`

GPT Vision/OCR 모델에 전달할 교통사고사실확인원 전용 프롬프트를 작성했다.

반영한 규칙은 다음과 같다.

```text
JSON만 반환
없는 값은 null
추측 금지
개인정보 추출 금지
사고 장소는 추출
사고현장약도/2page 분석 제외
```

모델명은 코드에 고정하지 않고 `.env`의 `OCR_MODEL_NAME`에서 읽도록 `get_ocr_model_name()` 함수를 만들었다.

예상 사용 값:

```text
OCR_MODEL_NAME = gpt-5.4-mini
```

### `masking.py`

모델이 실수로 자유 텍스트 안에 개인정보를 포함해도 저장 전에 마스킹할 수 있도록 후처리 함수를 작성했다.

필요 함수:

```text
mask_sensitive_text
mask_sensitive_fields
```

마스킹 대상 예시는 다음과 같다.

```text
주민등록번호
전화번호
운전면허번호
차량번호
이름/소유자명 같은 민감 key
거주지 주소/소유자 주소 같은 민감 key
```

단, `accident_location`은 사고 판단에 필요한 필드이므로 필드 자체를 제거하지 않는다.
다만 사고내용 같은 자유 텍스트 안에 `12가3456` 같은 차량번호 패턴이 섞이면 `[MASKED]`로 바뀐다.

### `evaluator.py`

OCR 결과가 서비스에서 사용할 수 있는지 `success / partial / failed`로 판정하는 로직을 작성했다.

critical 필드는 다음과 같다.

```text
accident_datetime
accident_location
accident_type.value
accident_description
```

important 필드는 다음과 같다.

```text
receipt_number
issue_number
police_station
accident_cause
damage.raw_text
usage
```

판정 기준:

```text
문서가 교통사고사실확인원이 아니면 failed
JSON 파싱/형식 오류가 있으면 failed
critical 필드가 하나라도 비면 partial
critical은 다 있지만 important 필드가 비면 partial
critical과 important가 모두 있으면 success
```

### `constants.py`

`success`, `partial`, `failed`와 `failure_reason` 값을 공통 상수로 분리했다.

작성한 대표 상수:

```text
STATUS_SUCCESS
STATUS_PARTIAL
STATUS_FAILED
OUTPUT_STATUS_UNKNOWN
FAILURE_REASON_UNSUPPORTED_FILE_TYPE
FAILURE_REASON_INVALID_IMAGE_PAYLOAD
FAILURE_REASON_NOT_TARGET_DOCUMENT
FAILURE_REASON_PAGE_1_NOT_FOUND
FAILURE_REASON_LOW_IMAGE_QUALITY
FAILURE_REASON_OCR_FAILED
FAILURE_REASON_PRIVACY_FILTER_FAILED
```

### 이유와 근거

상태값과 실패사유는 `agent.py`, `evaluator.py`, `graph.py`, `verification.py`에서 반복해서 쓰일 가능성이 높다.

문자열을 파일마다 직접 쓰면 `"sucess"`, `"faild"`, `"ocr_faild"` 같은 오타가 생겨도 실행 전에는 발견하기 어렵다.

따라서 `constants.py`를 기준 파일로 두고, 다른 파일에서는 상수를 import해서 사용하도록 정리했다.

## 4~6번 작성 후 실행 가능한 확인 명령

PowerShell에서 파일 생성 여부를 확인하려면 아래 명령어를 실행한다.

```powershell
Get-ChildItem -LiteralPath "etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr" -Force
```

예상 결과:

```text
__init__.py
constants.py
state.py
utils.py
prompts.py
masking.py
evaluator.py
```

Python 문법 오류만 확인하려면 아래 명령어를 실행한다.

```powershell
python -m py_compile `
  etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr\constants.py `
  etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr\state.py `
  etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr\utils.py `
  etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr\prompts.py `
  etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr\masking.py `
  etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr\evaluator.py
```

예상 결과:

```text
아무 출력 없이 종료되면 문법 오류 없음
```

`OCR_MODEL_NAME`이 잘 읽히는지 확인하려면 아래 명령어를 실행한다.

```powershell
python -c "from dotenv import load_dotenv; load_dotenv(); from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.prompts import get_ocr_model_name; print(get_ocr_model_name())"
```

예상 결과:

```text
gpt-5.4-mini
```

개인정보 마스킹 함수만 확인하려면 아래 명령어를 실행한다.

```powershell
python -c "from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.masking import mask_sensitive_text; print(mask_sensitive_text('사고내용에 12가3456 차량과 010-1234-5678 연락처가 포함됨'))"
```

예상 결과:

```text
사고내용에 [MASKED] 차량과 [MASKED] 연락처가 포함됨
```

판정 로직을 확인하려면 아래 명령어를 실행한다.

```powershell
python -c "from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.evaluator import evaluate_ocr_result; print(evaluate_ocr_result({'accident_datetime':'2024-01-01 10:00','accident_location':'서울시 노원구','accident_type':{'value':'차대차'},'accident_description':'교차로 충돌','receipt_number':'1','issue_number':'2','police_station':'서울노원경찰서','accident_cause':'안전운전의무위반','damage':{'raw_text':'부상 1명'},'usage':'보험사 제출'}, {'is_target_document': True}))"
```

예상 결과:

```text
{'status': 'success', 'failure_reason': None, 'missing_fields': [], 'limitations': []}
```

critical 필드가 빠진 경우를 확인하려면 아래 명령어를 실행한다.

```powershell
python -c "from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.evaluator import evaluate_ocr_result; print(evaluate_ocr_result({'accident_datetime':None,'accident_location':'서울시 노원구','accident_type':{'value':None},'accident_description':'교차로 충돌'}, {'is_target_document': True}))"
```

예상 결과:

```text
status가 partial이고 missing_fields에 accident_datetime, accident_type.value가 포함됨
```

## 다음 단계 업데이트

다음에 진행할 작업은 7번 `agent.py` 작성이다.

`agent.py`에서는 아래 흐름을 연결한다.

```text
MIME 확인
base64 검증
OCR_MODEL_NAME 기반 모델명 로딩
GPT Vision/OCR 호출
JSON 파싱
masking.py 호출
evaluator.py 호출
utils.py로 output JSON 저장
Supervisor envelope 생성
```

## 7~9번 진행 내용

이번 단계에서는 계획 기준 7번부터 9번까지 작성했다.

7. `agent.py` 작성
8. `verification.py` 작성
9. `graph.py` 작성

### `agent.py`

실제 OCR 노드의 기본 흐름을 작성했다.

처리 흐름:

```text
MIME 확인
base64 검증
OCR_MODEL_NAME 기반 GPT Vision/OCR 호출
JSON 파싱
개인정보 마스킹
필드 정규화
evaluator 호출
output JSON 저장
Supervisor envelope 생성
```

지원 MIME은 MVP 기준대로 아래 두 개만 허용한다.

```text
image/jpeg
image/png
```

원본 이미지와 base64는 결과에 저장하지 않고, `document_image`는 반환 시 `None`으로 제거한다.

### `verification.py`

교통사고사실확인원 문서 판정/검증 노드를 작성했다.

검증 기준:

```text
제목: 교통사고사실확인원
사고 핵심 라벨: 발생일시, 발생장소, 사고유형, 사고원인, 피해내용, 사고내용
경찰 발급 문서 구조: 교통사고 접수번호, 발급번호, 경찰서, 용도, 담당자, 경찰서장
```

점수 기준:

```text
제목 일치: +1
사고 핵심 라벨 4개 이상: +1
발급 구조 라벨 2개 이상: +1
총 3점 중 2점 이상이면 교통사고사실확인원으로 판단
```

제목이 없는데 다른 기준만 충족한 경우에는 문서가 잘렸거나 제목 인식이 실패했을 수 있으므로 `partial`로 유지한다.

### `graph.py`

LangGraph 연결 파일을 작성했다.

흐름:

```text
ocr_node
-> document_verification_node
-> END
```

단, `ocr_node`가 `failed`를 반환하면 바로 `END`로 종료한다.

LangGraph가 설치되지 않은 환경에서도 구조 확인이 가능하도록 fallback graph를 넣었다.

## 7~9번 작성 후 실행 가능한 확인 명령

파일 생성 여부를 확인하려면 아래 명령어를 실행한다.

```powershell
Get-ChildItem -LiteralPath "etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr" -Force
```

예상 결과:

```text
__init__.py
constants.py
state.py
utils.py
prompts.py
masking.py
evaluator.py
agent.py
verification.py
graph.py
```

API 호출 없이 import 가능 여부만 확인하려면 아래 명령어를 실행한다.

```powershell
python -B -c "from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr import agent, verification, graph; print('ocr_nodes_import_ok')"
```

예상 결과:

```text
ocr_nodes_import_ok
```

문서 검증 점수 계산만 확인하려면 아래 명령어를 실행한다.

```powershell
python -B -c "from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.verification import verify_document; print(verify_document('교통사고사실확인원', ['발생일시','발생장소','사고유형','사고원인'], ['발급번호','경찰서']))"
```

예상 결과:

```text
is_target_document이 True이고 verification_score가 3
```

실제 OCR 호출은 아래 단계에서 진행한다.

```text
10. mock 테스트
11. 실제 이미지 3개 smoke test
12. 모델 비교
```

## 7~9번 검증 기록

실제 OpenAI API 호출 없이 import 가능 여부를 확인했다.

실행한 명령:

```powershell
python -B -c "from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr import agent, verification, graph; print('ocr_nodes_import_ok')"
```

결과:

```text
ocr_nodes_import_ok
```

추가로 아래 경고가 출력되었다.

```text
Core Pydantic V1 functionality isn't compatible with Python 3.14 or greater.
```

이 경고는 `graph.py` import 과정에서 설치된 `langgraph/langchain_core` 쪽에서 나온 Python 3.14 호환성 경고다.
현재 확인 범위에서는 import 실패가 아니므로 7~9번 코드 작성 자체를 막는 오류는 아니다.

## Python 런타임 버전 정리

현재 로컬 실행 환경에서는 Python 3.14가 사용되어 `langchain_core`의 Pydantic V1 호환성 경고가 발생했다.

서비스 배포 기준은 repo의 `Dockerfile`이므로, 기존 `python:3.13-slim`을 `python:3.12-slim`으로 변경했다.

변경 이유:

```text
LangChain/LangGraph/Pydantic 계열은 Python 3.14보다 Python 3.12 환경에서 더 안정적으로 검증된 경우가 많다.
Django 6.0.6은 Python 3.12 이상에서 사용할 수 있으므로 현재 requirements와도 맞는다.
서비스 컨테이너 기준 Python 버전을 3.12로 고정하면 로컬 3.14 경고와 배포 환경 차이를 줄일 수 있다.
```

변경 파일:

```text
Dockerfile
```

변경 내용:

```dockerfile
FROM python:3.12-slim
```

로컬에서 같은 버전으로 실행하려면 Python 3.12를 설치한 뒤 아래처럼 확인한다.

```powershell
py -3.12 --version
```

예상 결과:

```text
Python 3.12.x
```

서비스 컨테이너를 다시 빌드하려면 아래 명령어를 실행한다.

```powershell
docker compose build backend
```

예상 결과:

```text
backend 이미지가 python:3.12-slim 기반으로 다시 빌드된다.
```

문서 검증 점수 계산도 확인했다.

실행한 명령:

```powershell
python -B -c "from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.verification import verify_document; print(verify_document('교통사고사실확인원', ['발생일시','발생장소','사고유형','사고원인'], ['발급번호','경찰서']))"
```

결과:

```text
{
  'is_target_document': True,
  'document_name': '교통사고사실확인원',
  'reason': '제목 일치: True, 사고 라벨 일치 수: 4, 발급 구조 라벨 일치 수: 2, 총점: 3/3',
  'verification_score': 3,
  'verification_criteria': {
    'title_matched': True,
    'accident_labels_matched_count': 4,
    'issuer_structure_matched_count': 2
  }
}
```

의미:

```text
제목 + 사고 핵심 라벨 + 경찰 발급 구조 기준이 모두 충족되면 verification_score 3점으로 계산된다.
```

## 상태/실패사유 상수화 후 검증 기록

상태값과 실패사유를 `constants.py`로 분리한 뒤 문법 확인을 시도했다.

처음 실행한 명령:

```powershell
python -m py_compile etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr\constants.py etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr\state.py etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr\utils.py etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr\prompts.py etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr\masking.py etl\fault_cases\src\OCR\traffic_accident_confirmation_ocr\evaluator.py
```

결과:

```text
[WinError 5] 액세스가 거부되었습니다: __pycache__ 아래 pyc 파일 쓰기/교체 실패
```

이 오류는 Python 코드 문법 오류라기보다 기존 `__pycache__` 파일에 대한 쓰기 권한 문제로 보인다.

따라서 바이트코드 파일을 만들지 않는 방식으로 다시 확인했다.

실행한 명령:

```powershell
python -B -c "from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr import constants, state, utils, prompts, masking, evaluator; print('import_ok')"
```

결과:

```text
import_ok
```

의미:

```text
constants.py, state.py, utils.py, prompts.py, masking.py, evaluator.py는 import 가능한 상태다.
즉, 이번 상수화 수정으로 인한 기본 문법/import 오류는 확인되지 않았다.
```
