# API · 인터페이스 설계서
**과태료·범칙금 고지서 분석 Agent** · Design Document 3/3

| 항목 | 값 |
|------|-----|
| 문서 번호 | API-003 |
| 버전 | v3.0 |
| 작성일 | 2026-06-29 |
| 변경 요약 | v2.0 6-노드 → v3.0 2-노드 재설계. 텍스트 입력 호출 제거. 감경·이의 판단 인터페이스 제거. |

---

## 1. 개요

본 문서는 과태료·범칙금 고지서 분석 Agent의 인터페이스를 정의한다. Supervisor와 Agent 간의 `graph.invoke()` 계약, 노드별 함수 시그니처, GPT-4o 호출 인터페이스, Django REST API 연동 명세를 포함한다.

| 인터페이스 | 방향 | 프로토콜 | 문서 섹션 |
|-----------|------|---------|---------|
| Supervisor → Agent | 호출 | LangGraph graph.invoke() | 2장 |
| Agent → Supervisor | 반환 | agent_results dict | 3장 |
| Agent → GPT-4o | 외부 API | OpenAI Chat Completions | 4장 |
| Supervisor → Django | 외부 REST | HTTP GET /api/files/{id}/ | 5장 (Supervisor 책임) |
| 노드 간 (내부) | 단방향 State | LangGraph State 공유 | 6장 |

---

## 2. graph.invoke() 인터페이스

### 2-1. 함수 시그니처

```python
from langgraph.graph import StateGraph

graph: StateGraph  # fine_notice_analysis_graph

result = graph.invoke(input: dict) -> dict
# 반환: {"agent_results": {"fine_notice_analysis": FineNoticeEnvelope}}
```

### 2-2. 입력 파라미터 전체 목록

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|---------|------|------|--------|------|
| notice_image | str\|None | 필수 | None | base64 이미지. Supervisor가 변환하여 전달 |
| notice_mime_type | str | 조건부 | "image/jpeg" | "image/jpeg"\|"image/png"\|"application/pdf" |

> ✅ notice_image 없으면 ocr_status=failed 즉시 반환.  
> ❌ **텍스트 직접 입력 (notice_stage, law_code 등) 은 v3.0에서 지원하지 않음.**  
> ℹ️ **이미지 소싱(Django /api/files/, 챗봇 업로드 등)은 Supervisor 책임 — OCR 에이전트는 notice_image(base64)만 수신.**

### 2-3. 호출 예시 — 이미지 입력

```python
import base64

with open("notice.jpg", "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

result = graph.invoke({
    "notice_image":     b64,
    "notice_mime_type": "image/jpeg",
})

analysis = result["agent_results"]["fine_notice_analysis"]
print(analysis["status"])                              # "success"
print(analysis["structured_result"]["fine_type"])      # "과태료"
print(analysis["structured_result"]["notice_stage"])   # "사전통지"
```

### 2-4. 호출 예시 — PDF 입력

```python
with open("notice.pdf", "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

result = graph.invoke({
    "notice_image":     b64,
    "notice_mime_type": "application/pdf",
})
# PDF 페이지 > 10이면 ocr_status="failed", ocr_error="PDF 페이지 초과" (R-08)
```

### 2-5. 호출 예시 — 이미지 재업로드

```python
# 1차 호출: degraded (opinion_deadline 누락)
# Supervisor가 고지서 이미지 재업로드 요청 → 사용자가 더 선명한 이미지 제공

result = graph.invoke({
    "notice_image":     "<base64_new_image>",
    "notice_mime_type": "image/jpeg",
})
# R-03: 새 이미지 도착 시 이전 OCR 결과 자동 초기화
```

---

## 3. agent_results 반환 인터페이스

### 3-1. 최상위 구조

```python
{
    "fine_notice_analysis": {
        "node_name":         str,        # "고지서 OCR·과태료/범칙금 분석 노드"
        "node_code":         str,        # "fine_notice_analysis"
        "status":            str,        # "success"|"degraded"|"partial"|"failed"|"rejected"
        "summary":           str,        # 1줄 요약
        "structured_result": dict,       # 3-2 참조
        "evidence":          list[dict], # OCR 출처 기록
        "missing_fields":    list[str],
        "next_actions":      list[str],
        "limitations":       list[str],
    }
}
```

### 3-2. structured_result 상세

| 필드 | 타입 | 설명 | 유형별 존재 여부 |
|------|------|------|----------------|
| ocr_status | str | "success"\|"degraded"\|"partial"\|"failed"\|"rejected" | 공통 |
| ocr_error | str\|None | 구조 오류 메시지 (R-08) | 공통 |
| fine_type | str\|None | "과태료"\|"범칙금"\|"벌금"\|None | 공통 |
| notice_stage | str\|None | "사전통지"\|"1차 고지서"\|"즉결심판" | 공통 |
| law_code | str\|None | "도로교통법 제17조" 형식 | ④ 없음 |
| violation_text | str\|None | 마스킹된 위반 내용 원문 | 없을 수 있음 |
| violation_datetime | str\|None | 위반 일시 | 없을 수 있음 |
| violation_location | str\|None | 위반 장소 | 없을 수 있음 |
| fine_amount | int\|None | 부과 금액 | ④ 미확정 가능 |
| prepayment_amount | int\|None | 사전납부 금액 (이미지 추출값) | ① 전용. 나머지 None (R-06) |
| opinion_deadline | str\|None | YYYY-MM-DD. 유형별 의미 다름 | 공통 |
| payment_deadline_2nd | str\|None | YYYY-MM-DD. 2차 납부기한 (1차+20일 가산) | ③ 전용 |
| additional_amount | int\|None | 2차 납부 시 가산금액 (fine_amount × 1.2) | ③ 전용 |
| vehicle_number | str\|None | 마스킹된 차량번호 | ④ 없음 |
| issuing_authority | str\|None | 발급 기관 | 공통 |
| demerit_points_base | int\|None | 이번 위반 벌점 | ③ 전용 |
| demerit_points_accumulated | int\|None | 누적 처분벌점 | ③ 전용 |
| charge_number | str\|None | 부과번호·관리번호·통고서번호 | ①②③ 유효 |
| court_venue | str\|None | 즉결심판 출석 장소 | ④ 전용 |
| missing_fields | list[str] | 누락 필드 목록 | 공통 |

> **opinion_deadline 유형별 의미**
> - ① 과태료 사전통지: 의견제출기한
> - ② 과태료 고지서: 납부기한 ⚠️ **이의신청 가능 기한(질서위반행위규제법 제20조) = 수령일+60일로 납부기한과 다를 수 있음 — Supervisor 별도 계산 필요**
> - ③ 범칙금 통고서: 1차 납부기한 (`payment_deadline_2nd`에 2차 납부기한 별도 추출)
> - ④ 즉결심판: **출석(예정)일시** (납부기한 아님)

### 3-3. next_actions 값 목록

| next_actions 값 | 트리거 조건 |
|----------------|-----------|
| `"법률 근거 검색 노드 호출"` | ocr_status=success + fine_type=과태료 |
| `"OCR 결과만 반환 — 이의신청 불가"` | ocr_status=success + fine_type=범칙금 (법원행정 영역) |
| `"이미지 재업로드 요청"` | ocr_status=degraded/partial/failed |
| `"서비스 범위 외 안내"` | ocr_status=rejected |

### 3-4. 반환 예시 — ① 과태료 사전통지서

```python
{
    "fine_notice_analysis": {
        "status": "success",
        "summary": "속도위반 20km 초과 — 사전통지 OCR success",
        "structured_result": {
            "ocr_status":        "success",
            "ocr_error":         None,
            "fine_type":         "과태료",
            "notice_stage":      "사전통지",
            "law_code":          "도로교통법 제17조 제1항",
            "violation_text":    "속도위반 20km 초과",
            "violation_datetime":"2026-05-01T14:30:00",
            "violation_location":"서울시 강남구 테헤란로",
            "fine_amount":       60000,
            "prepayment_amount": 48000,     # 이미지에 인쇄된 사전납부 금액
            "opinion_deadline":  "2026-07-01",
            "vehicle_number":    "12가●●●●",
            "charge_number":     "20260001",
            "demerit_points_base": None,
            "missing_fields":    [],
        },
        "missing_fields": [],
        "next_actions": ["법률 근거 검색 노드 호출"],
    }
}
```

---

## 4. GPT-4o 호출 인터페이스

### 4-1. ocr_node — Vision 호출

```python
response = openai.chat.completions.create(
    model="gpt-4o",
    max_tokens=1024,
    messages=[{
        "role": "user",
        "content": [
            {"type": "text",      "text": NOTICE_EXTRACTION_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ],
    }],
)

raw_text = response.choices[0].message.content.strip()
# [R-11] 마스킹 선행 — JSON 파싱 이전에 반드시 호출
raw_text = mask_personal_info(raw_text)
```

### 4-2. OCR 프롬프트 필드 매핑

| 프롬프트 설명 | 추출 필드 | 비고 |
|-------------|---------|------|
| 문서 제목·서식명 | document_title | fine_type 분류에 사용 후 제거 |
| 서식명으로 고지 단계 판단 | notice_stage | "사전통지"\|"1차 고지서"\|"즉결심판" |
| 의견제출기한\|납부기한\|납부기한(1차) | opinion_deadline | YYYY-MM-DD |
| 과태료 금액\|범칙금 금액 | fine_amount | 숫자만 |
| 사전납부금액\|사전납부 | prepayment_amount | 숫자만 |
| 위반내용\|범칙내용 | violation_text | |
| 벌점 | demerit_points_base | |
| 처분벌점\|누적벌점 | demerit_points_accumulated | |
| 적용법조 | law_code | |
| 발급기관 | issuing_authority | |
| 부과번호\|관리번호 | charge_number | |
| 가산금액 | additional_amount | ③ 전용 |
| 출석 장소 | court_venue | ④ 전용 |

### 4-3. fine_type 분류 로직 (_classify_fine_type)

```python
def _classify_fine_type(title: str, authority: str, has_demerit: bool) -> str | None:
    t, a = title or "", authority or ""
    if "즉결심판" in t and "과태료" not in t:  return "범칙금"  # P-0
    if "검찰" in a:                             return "벌금"    # P-1
    if "약식명령" in t or "벌과금" in t:        return "벌금"    # P-2
    if "범칙금" in t:                           return "범칙금"  # P-3
    if "과태료" in t:                           return "과태료"  # P-4
    if has_demerit:                             return "범칙금"  # P-5
    if any(kw in a for kw in ("구청","시청")):  return "과태료"  # P-6
    return None                                                  # GPT fallback
```

### 4-4. GPT 오류 처리 전략

| 오류 유형 | 처리 방식 | 최종 ocr_status |
|----------|----------|----------------|
| JSON 파싱 실패 | ocr_error="GPT 응답 파싱 실패" | failed |
| PDF 빈 페이지 | ocr_error="PDF 변환 결과 페이지 없음" | failed |
| PDF 페이지 초과 | ocr_error="PDF 페이지 초과" (R-08) | failed |

---

## 5. Django REST API 연동 (Supervisor 책임)

> ℹ️ Django `/api/files/{attachment_id}/` 연동은 **Supervisor 책임**이다.  
> OCR 에이전트는 notice_image(base64)만 수신하며, 파일 스토리지 접근 코드를 포함하지 않는다.

### 5-1. 연동 흐름 (참고용)

```
사용자 업로드 → Supervisor → Django /api/files/{id}/ → base64 변환 → graph.invoke({notice_image: b64})
```

| 역할 | 담당 |
|------|------|
| 챗봇 UI / 파일 수신 | Supervisor |
| Django /api/files/ 호출 | Supervisor |
| base64 변환 후 notice_image 전달 | Supervisor |
| OCR 판독 | OCR 에이전트 (notice_image만 수신) |

---

## 6. 노드별 내부 함수 시그니처

### 6-1. ① ocr_node

```python
def ocr_node(state: LangGraphState) -> dict:
    """
    1. notice_image 없으면 즉시 failed 반환
    2. PDF: pdf_to_images() — >10p → failed (R-08)
    3. GPT-4o Vision 호출
    4. R-11: mask_personal_info(raw_text) — JSON 파싱 이전
    5. JSON 파싱 실패 → failed
    6. _classify_fine_type() → fine_type 결정; 벌금·None → rejected 즉시 반환
    7. 코드 레벨 이중 마스킹 (resident_number, vehicle_number)
    8. evaluate_ocr() → ocr_status, missing_fields; partial → 즉시 반환
    9. R-03: flat["ocr_error"] = result.get("ocr_error") — 성공 시 None으로 초기화
    10. notice_image = None (개인정보 폐기)
    """

def _build_image_blocks(pages: list[tuple[str, str]]) -> list[dict]:
    """(base64, mime_type) → GPT image_url 블록 리스트"""

def _call_gpt(image_blocks: list[dict]) -> dict:
    """GPT-4o Vision 호출 → 마스킹 → JSON 파싱. 실패 시 failed dict"""

def _classify_fine_type(title: str, authority: str, has_demerit: bool) -> str | None:
    """우선순위 7단계 룩업. 미매칭 시 None → GPT fallback"""
```

### 6-2. ② confidence_verification_node

```python
def confidence_verification_node(state: LangGraphState) -> dict:
    """
    V-01: notice_stage 유효 값 검증
    V-02: fine_type 유효 값 검증
    V-03: fine_amount 양의 정수 검증
    V-04: law_code 형식 정규식 검증
    V-05 (R-01): fine_type × notice_stage VALID_COMBINATIONS 검증
    format_errors 누적 → ocr_status=partial 재판정
    """

VALID_COMBINATIONS: set[tuple[str, str]] = {
    ("과태료", "사전통지"),
    ("과태료", "1차 고지서"),
    ("범칙금", "사전통지"),
    ("범칙금", "즉결심판"),
    # 과태료 2차 고지서(납부독촉장)는 도로교통법 시행규칙 별지 서식 미존재 — 서비스 범위 외 제외
    # 벌금은 notice_stage 무관 — 조합 검증 제외
}
```

---

## 7. Supervisor 인터페이스 계약

### 7-1. Supervisor가 반드시 지켜야 할 규칙

| 규칙 ID | 규칙 | 위반 시 영향 |
|---------|------|-----------|
| S-01 | 이미지 재업로드 시 이전 OCR 결과 필드를 invoke에 포함하지 말 것 (R-03이 방어하지만 권장) | State 오염 가능성 |
| S-02 | today는 "YYYY-MM-DD" 형식으로 전달. 없으면 생략 | 형식 오류 시 내부 fallback (R-10) |
| S-03 | ocr_status=rejected 시 graph.invoke() 재호출 금지 | 불필요한 GPT 호출 |
| S-04 | notice_image 없이 호출 금지. 이미지 소싱(Django, 챗봇 업로드)은 Supervisor가 처리 후 base64로 변환하여 전달 | ocr_status=failed 즉시 반환 |

### 7-2. Supervisor 의사결정 흐름

```python
result   = graph.invoke({"notice_image": b64})
analysis = result["agent_results"]["fine_notice_analysis"]
status   = analysis["status"]

if status == "success":
    sr = analysis["structured_result"]
    fine_type    = sr["fine_type"]
    notice_stage = sr["notice_stage"]
    # → 이의신청서 생성 Agent 또는 감경 안내 흐름으로 전달

elif status == "degraded":
    # 추출 가능한 필드는 있으나 일부 누락
    # missing_fields를 확인하여 허용 수준이면 그대로 활용
    # 아니면 "고지서를 더 선명하게 다시 업로드해 주세요" 안내
    ...

elif status == "partial":
    # 핵심 필드 추출 실패 또는 형식 오류
    # "고지서 이미지를 다시 업로드해 주세요" 안내
    ...

elif status == "rejected":
    # 벌금(형사처벌)이거나 고지서를 인식할 수 없는 경우
    # "죄송합니다. 해당 고지서는 서비스 지원 범위에 해당하지 않습니다." 안내
    ...

elif status == "failed":
    ocr_error = analysis["structured_result"].get("ocr_error")
    if ocr_error == "PDF 페이지 초과":
        # "PDF가 너무 깁니다. 고지서 페이지만 추출해서 재업로드해 주세요"
        ...
    else:
        # "고지서 이미지를 다시 업로드해 주세요"
        ...
```
