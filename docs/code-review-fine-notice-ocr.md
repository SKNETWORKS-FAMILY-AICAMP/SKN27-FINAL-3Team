# 코드 검수 리포트 — `patch/fine-notice-ocr-test`

> 검수 기준 커밋: `e8f4c32` (fix: invalid base64, 손상 PDF 입력 failed envelope 처리)  
> 검수 범위: `ai/agents/fine_notice_analysis/agent.py`, `test/test_fine_notice_ocr.py`  
> 검수 등급: medium  
> 생성일: 2026-06-30

---

## 변경 요약

이번 diff의 핵심 변경은 두 가지입니다.

1. **`agent.py` line 115** — `base64.b64decode(notice_image)` → `base64.b64decode(notice_image, validate=True)`  
   유효하지 않은 base64 문자열을 더 엄격하게 거부하기 위한 수정.

2. **`test_fine_notice_ocr.py`** — `test_ocr_rejects_invalid_base64` 테스트를 `_pdf` / `_jpeg` 두 개로 분리하고 `test_ocr_rejects_corrupted_pdf` 추가.

---

## 발견된 문제 목록 (7건)

| # | 심각도 | 파일 | 줄 | 판정 | 한줄 요약 |
|---|--------|------|----|------|-----------|
| 1 | 🔴 높음 | `agent.py` | 100 | CONFIRMED | PDF를 JPEG로 오분류 (mime_type 생략 시) |
| 2 | 🔴 높음 | `test_fine_notice_ocr.py` | 31 | CONFIRMED | pytestmark가 GPT 불필요 테스트까지 skip |
| 3 | 🟡 중간 | `agent.py` | 115 | PLAUSIBLE | validate=True가 개행/URL-safe base64 거부 |
| 4 | 🟡 중간 | `agent.py` | 116 | PLAUSIBLE | bare `except Exception`이 예상치 못한 에러 삼킴 |
| 5 | 🟡 중간 | `test_fine_notice_ocr.py` | 186 | PLAUSIBLE | JPEG 테스트가 JPEG 경로를 커버하지 않음 |
| 6 | 🟢 낮음 | `test_fine_notice_ocr.py` | 182 | PLAUSIBLE | `envelope=None`일 때 AttributeError 가능 |
| 7 | 🟢 낮음 | `test_fine_notice_ocr.py` | 197 | CONFIRMED | 함수 내 `import base64 as _b64` 중복 |

---

## 상세 설명

---

### #1 🔴 PDF를 JPEG로 오분류 (mime_type 생략 시)

**파일:** [ai/agents/fine_notice_analysis/agent.py](../ai/agents/fine_notice_analysis/agent.py#L100)  
**줄:** 100  
**판정:** CONFIRMED

#### 문제 코드

```python
# agent.py line 100
notice_mime_type = state.get("notice_mime_type") or "image/jpeg"
```

```python
# agent.py line 123-143
if notice_mime_type == "application/pdf":
    # PDF → 이미지 변환 후 GPT 전달
    pages = _pdf_to_images(raw_bytes)
    ...
else:
    # MIME 타입 그대로 GPT에 전달
    image_blocks = _build_image_blocks([(notice_image, notice_mime_type)])
```

#### 왜 문제인가?

`FineNoticeState`에서 `notice_mime_type`은 `Optional[str]` + `total=False`로 선언되어 있어 호출 시 **생략 가능**합니다.

```python
# state.py line 12
notice_mime_type: Optional[str]  # "image/jpeg"|"image/png"|"application/pdf"
```

호출자가 `notice_mime_type`을 생략하면:

1. line 100의 `or "image/jpeg"`가 적용되어 기본값이 `"image/jpeg"`가 됨
2. line 123의 PDF 분기를 **통과하지 못함**
3. PDF base64 바이트가 JPEG data-URI로 GPT에 전달됨
4. GPT는 JPEG를 받을 것으로 기대하므로 OCR 결과가 깨지거나 실패

```python
# 이렇게 호출하면 조용히 오분류됨
graph.invoke({
    "notice_image": pdf_base64,
    # notice_mime_type 누락
})
```

런타임 에러도 없고 타입 체커 경고도 없어 디버깅이 매우 어렵습니다.

#### 현재 위험도 평가

- 현재 테스트와 내부 호출자는 **항상 `"application/pdf"`를 명시**하므로 즉각적인 위험은 낮음
- 외부 API로 노출되거나 새 호출자가 추가될 경우 실수 발생 가능성이 있음

#### 권장 수정

```python
# 방어적으로 처리: mime_type 없으면 명시적 오류 반환
notice_mime_type = state.get("notice_mime_type")
if not notice_mime_type:
    err = "notice_mime_type이 필요합니다 (image/jpeg, image/png, application/pdf)."
    env = make_envelope("failed", {"ocr_status": "failed", "ocr_error": err}, [], ["이미지 재업로드 요청"])
    return {"ocr_status": "failed", "ocr_error": err, "notice_image": None,
            "agent_results": update_agent_results(state, env)}
```

---

### #2 🔴 pytestmark가 GPT 불필요 테스트까지 skip

**파일:** [test/test_fine_notice_ocr.py](../test/test_fine_notice_ocr.py#L31)  
**줄:** 31  
**판정:** CONFIRMED

#### 문제 코드

```python
# test_fine_notice_ocr.py lines 31-34
pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY") or not _GRAPH_AVAILABLE,
    reason="OPENAI_API_KEY not set or 의존성 누락 — 통합 테스트 건너뜀",
)
```

#### 왜 문제인가?

`pytestmark`는 **모듈 전체**에 적용됩니다. `OPENAI_API_KEY`가 없으면 아래 4개 테스트도 전부 skip됩니다.

| 테스트 | GPT 호출 여부 | 실제 skip 이유 |
|--------|--------------|----------------|
| `test_ocr_rejects_missing_image` | ❌ 불필요 | agent.py line 106에서 조기 반환 |
| `test_ocr_rejects_invalid_base64_pdf` | ❌ 불필요 | agent.py line 119에서 조기 반환 |
| `test_ocr_rejects_invalid_base64_jpeg` | ❌ 불필요 | agent.py line 119에서 조기 반환 |
| `test_ocr_rejects_corrupted_pdf` | ❌ 불필요 | agent.py line 133에서 조기 반환 |

각 테스트 docstring에도 **"GPT 호출 불필요"** 라고 명시되어 있습니다. API 키가 없는 CI 환경에서 오류 처리 경로가 전혀 검증되지 않습니다.

#### 권장 수정

```python
# GPT가 필요한 통합 테스트에만 적용되는 마커 별도 정의
requires_api = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY") or not _GRAPH_AVAILABLE,
    reason="OPENAI_API_KEY not set — 통합 테스트 건너뜀",
)

# 그래프 import만 필요한 테스트용 마커
requires_graph = pytest.mark.skipif(
    not _GRAPH_AVAILABLE,
    reason="의존성 누락 — 테스트 건너뜀",
)

# 통합 테스트에만 requires_api 적용
@requires_api
@pytest.mark.parametrize(...)
def test_ocr_classifies_fine_type_and_stage(...): ...

# 오류 경로 테스트는 requires_graph만 적용
@requires_graph
def test_ocr_rejects_missing_image(): ...
```

---

### #3 🟡 validate=True가 개행/URL-safe base64 거부

**파일:** [ai/agents/fine_notice_analysis/agent.py](../ai/agents/fine_notice_analysis/agent.py#L115)  
**줄:** 115  
**판정:** PLAUSIBLE

#### 문제 코드

```python
# agent.py line 115
raw_bytes = base64.b64decode(notice_image, validate=True)
```

#### 왜 문제인가?

Python `base64.b64decode(s, validate=True)`는 base64 알파벳 외의 문자가 있으면 `binascii.Error`를 발생시킵니다. 이 때 거부되는 입력 유형:

**케이스 1 — 개행 포함 base64 (MIME/RFC 2045)**

```python
# base64.encodebytes()는 76자마다 \n 삽입
import base64
data = b"some image bytes"
encoded = base64.encodebytes(data).decode()
# 'c29tZSBpbWFnZSBieXRlcw==\n'  ← \n 포함

# validate=True로 디코딩 시 binascii.Error 발생
base64.b64decode(encoded, validate=True)  # 💥 Error
```

모바일 앱, curl 멀티파트 업로드, 이메일 첨부 파이프라인 등 외부 클라이언트가 이 방식을 사용할 수 있습니다.

**케이스 2 — URL-safe base64**

```python
# URL-safe base64는 +/= 대신 -_= 사용
import base64
encoded = base64.urlsafe_b64encode(data).decode()
# 'c29tZSBpbWFnZSBieXRlcw=='  ← 표준이지만 - _ 포함 가능

base64.b64decode(encoded, validate=True)  # 💥 - 또는 _ 있으면 Error
```

#### 현재 위험도 평가

- 현재 내부 호출자(`test_fine_notice_ocr.py` line 91)는 `base64.b64encode().decode()`를 사용 → 개행 없음, 안전
- 외부 API가 없어 현재는 PLAUSIBLE 수준
- 외부 HTTP 엔드포인트가 추가되면 CONFIRMED 수준으로 상승

#### 권장 수정

```python
# validate=True 전에 화이트스페이스 제거
_cleaned = notice_image.strip().replace("\n", "").replace("\r", "").replace(" ", "")
raw_bytes = base64.b64decode(_cleaned, validate=True)
```

---

### #4 🟡 bare `except Exception`이 예상치 못한 에러 삼킴

**파일:** [ai/agents/fine_notice_analysis/agent.py](../ai/agents/fine_notice_analysis/agent.py#L116)  
**줄:** 116  
**판정:** PLAUSIBLE

#### 문제 코드

```python
# agent.py lines 114-120
try:
    raw_bytes = base64.b64decode(notice_image, validate=True)
except Exception:   # ← 너무 넓음
    err = "이미지 디코딩 실패 — 올바른 파일을 다시 업로드해 주세요."
    ...
    return {"ocr_status": "failed", ...}
```

#### 왜 문제인가?

`except Exception`은 `binascii.Error`뿐만 아니라 아래도 모두 잡습니다:

| 예외 | 발생 원인 | 올바른 처리 |
|------|-----------|------------|
| `binascii.Error` | 잘못된 base64 문자 | 사용자에게 재업로드 요청 ✅ |
| `ValueError` | 잘못된 패딩 | 사용자에게 재업로드 요청 ✅ |
| `MemoryError` | 메모리 부족 | 시스템 오류로 처리해야 함 ❌ |
| 기타 `RuntimeError` | 라이브러리 버그 | 실제 버그로 로깅해야 함 ❌ |

모든 케이스가 동일한 "이미지 재업로드 요청" 메시지로 처리되어 **실제 서버 이상을 운영자가 감지하기 어렵습니다.**

#### 권장 수정

```python
import binascii

try:
    raw_bytes = base64.b64decode(notice_image, validate=True)
except (binascii.Error, ValueError):
    err = "이미지 디코딩 실패 — 올바른 파일을 다시 업로드해 주세요."
    env = make_envelope("failed", {"ocr_status": "failed", "ocr_error": err}, [], ["이미지 재업로드 요청"])
    return {"ocr_status": "failed", "ocr_error": err, "notice_image": None,
            "agent_results": update_agent_results(state, env)}
# MemoryError 등 예상치 못한 예외는 자연스럽게 전파됨
```

---

### #5 🟡 JPEG 테스트가 실제 JPEG 경로를 커버하지 않음

**파일:** [test/test_fine_notice_ocr.py](../test/test_fine_notice_ocr.py#L186)  
**줄:** 186  
**판정:** PLAUSIBLE

#### 문제 코드

```python
def test_ocr_rejects_invalid_base64_jpeg():
    result = graph.invoke({
        "notice_image": "!!!invalid-base64!!!",
        "notice_mime_type": "image/jpeg",   # ← JPEG 지정
    })
    assert result["ocr_status"] == "failed"
```

#### 왜 문제인가?

`"!!!invalid-base64!!!"`는 `agent.py` line 115에서 **MIME 타입 분기 전에** 차단됩니다.

```
line 115: base64.b64decode("!!!invalid-base64!!!", validate=True)
          → binascii.Error 발생
          → except 블록 (lines 116-120) 진입
          → "failed" 반환
          ↳ line 123의 MIME 타입 분기에 절대 도달하지 않음
```

결과적으로 `test_ocr_rejects_invalid_base64_pdf`와 **완전히 동일한 코드 경로**를 실행합니다. JPEG 전용 경로인 line 143은 한 번도 실행되지 않습니다.

```python
# 이 경로가 전혀 테스트되지 않음
else:
    image_blocks = _build_image_blocks([(notice_image, notice_mime_type)])  # line 143
```

#### 권장 수정

유효한 JPEG base64를 사용하는 테스트 추가:

```python
def test_ocr_jpeg_path_reaches_gpt():
    """유효한 JPEG base64가 _build_image_blocks에 올바르게 전달되는지 확인."""
    # 1x1 픽셀 최소 JPEG
    minimal_jpeg = base64.b64encode(MINIMAL_JPEG_BYTES).decode()
    # GPT 호출은 mock 처리
    with patch("ai.agents.fine_notice_analysis.agent._call_gpt") as mock_gpt:
        mock_gpt.return_value = {...}
        graph.invoke({"notice_image": minimal_jpeg, "notice_mime_type": "image/jpeg"})
    mock_gpt.assert_called_once()
    _, kwargs = mock_gpt.call_args
    # image_url에 "data:image/jpeg;base64," 접두사 확인
```

또는 두 테스트를 파라미터화하여 중복 제거:

```python
@pytest.mark.parametrize("mime_type", ["application/pdf", "image/jpeg", "image/png"])
def test_ocr_rejects_invalid_base64(mime_type):
    result = graph.invoke({"notice_image": "!!!invalid!!!", "notice_mime_type": mime_type})
    assert result["ocr_status"] == "failed"
    assert "재업로드" in (result.get("ocr_error") or "")
```

---

### #6 🟢 `envelope=None`일 때 AttributeError 가능

**파일:** [test/test_fine_notice_ocr.py](../test/test_fine_notice_ocr.py#L182)  
**줄:** 182  
**판정:** PLAUSIBLE

#### 문제 코드

```python
# test_fine_notice_ocr.py lines 182-183 (invalid_base64_pdf 테스트)
envelope = result.get("agent_results", {}).get("fine_notice_analysis", {})
assert "이미지 재업로드 요청" in (envelope.get("next_actions") or [])
```

#### 왜 문제인가?

```python
result.get("agent_results", {}).get("fine_notice_analysis", {})
```

이 표현식에서 `.get("fine_notice_analysis", {})`의 기본값 `{}`은 키가 **없을 때만** 적용됩니다. 키가 존재하면서 값이 `None`이면 `None`이 반환됩니다.

```python
# 이 상황에서 envelope = None
result = {"agent_results": {"fine_notice_analysis": None}}

envelope = result.get("agent_results", {}).get("fine_notice_analysis", {})
# envelope == None  (키 있음, 값 None → 기본값 미적용)

envelope.get("next_actions")  # 💥 AttributeError: 'NoneType' has no attribute 'get'
```

비교: `test_ocr_agent_result_envelope_present`는 line 148에서 `assert envelope`로 이를 사전 차단합니다.

#### 권장 수정

```python
envelope = (result.get("agent_results") or {}).get("fine_notice_analysis") or {}
assert "이미지 재업로드 요청" in (envelope.get("next_actions") or [])
```

---

### #7 🟢 함수 내 `import base64 as _b64` 중복

**파일:** [test/test_fine_notice_ocr.py](../test/test_fine_notice_ocr.py#L197)  
**줄:** 197  
**판정:** CONFIRMED

#### 문제 코드

```python
# test_fine_notice_ocr.py line 10 — 모듈 최상단
import base64

# ...

# test_fine_notice_ocr.py line 197 — 함수 내부
def test_ocr_rejects_corrupted_pdf():
    import base64 as _b64          # ← 중복, 별칭 불필요
    bad_pdf = _b64.b64encode(b"not a real pdf content").decode()
```

#### 왜 문제인가?

- 런타임 오류는 없으나 `_b64`라는 별칭이 **의도적인 aliasing**처럼 보여 독자를 혼란시킴
- "이 함수에서 base64를 다르게 사용하는 이유가 있나?" 라는 불필요한 의문 유발

#### 권장 수정

```python
def test_ocr_rejects_corrupted_pdf():
    bad_pdf = base64.b64encode(b"not a real pdf content").decode()
    ...
```

---

## 총평

이번 diff의 핵심 변경(`validate=True`)은 방향성이 맞습니다. 잘못된 base64를 GPT 호출 전에 조기 차단하는 것은 올바른 설계입니다.

다만 함께 고려할 사항:

1. **즉시 수정 권장**: #2 (pytestmark — 오류 테스트가 keyless CI에서 skip됨)
2. **외부 API 노출 전 수정 권장**: #3 (개행 base64 거부), #1 (mime_type 기본값)
3. **코드 품질**: #4 (bare except), #5 (JPEG 커버리지), #6 (envelope None 가드), #7 (중복 import)
