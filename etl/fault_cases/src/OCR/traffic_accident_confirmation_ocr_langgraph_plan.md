# 교통사고사실확인원 OCR LangGraph 계획 및 Output Schema 정의

## 1. 목적

교통사고사실확인원 OCR LangGraph는 경찰서에서 발급한 교통사고사실확인원 **1page 이미지**를 OCR 처리하고, 과실비율 분석 및 보고서 업데이트에 사용할 수 있도록 주요 사고 정보를 구조화하여 Supervisor에게 전달한다.

본 기능은 과실비율을 판단하는 Agent가 아니다.  
교통사고사실확인원 이미지를 읽고 필요한 항목을 추출한 뒤, 뽑힌 항목과 안 뽑힌 항목을 정리하여 Supervisor에게 전달하는 **OCR LangGraph**이다.

최종적으로 생성되는 Output Schema는 이후 **과실비율 분석 LangGraph 또는 과실비율 Agent가 공식 사고 기록으로 참고하는 입력 데이터**가 된다.

즉, 역할은 다음과 같이 구분한다.

| 구분 | 역할 |
|---|---|
| 교통사고사실확인원 OCR LangGraph | 문서 OCR, 문서 여부 확인, 주요 항목 추출, 누락 항목 정리 |
| Supervisor | OCR 결과를 보고 다음 노드 호출 여부 판단 |
| 과실비율 Agent / LangGraph | OCR로 추출된 공식 사고 기록과 사용자 진술, RAG 검색 결과를 함께 사용하여 과실비율 분석 |

---

## 2. 업로드 기준

MVP 단계에서는 사용자가 **교통사고사실확인원 1page 이미지만 업로드**하도록 안내한다.

2page 사고현장약도는 현재 단계에서 분석하지 않는다.  
약도는 도로 구조, 차량 진행 방향, 충돌 지점 등을 Vision 기반으로 해석해야 하므로, 추후 실제로 필요하다고 판단될 때 별도 Vision 분석 노드로 확장한다.

### 사용자 업로드 안내 문구

```text
경찰서에서 발급받은 교통사고사실확인원 첫 번째 페이지만 업로드해주세요.
두 번째 페이지의 사고현장약도는 현재 분석 대상이 아닙니다.
```

또는 짧게 표현하면 다음과 같다.

```text
교통사고사실확인원 1page 이미지를 업로드해주세요.
사고현장약도가 포함된 2page는 현재 단계에서 분석하지 않습니다.
```

### 지원 파일 형식과 입력 전달 방식

MVP에서는 테스트 폴더 `etl/fault_cases/src/OCR/raw/1page`에 있는 이미지처럼 `.jpg`, `.jpeg`, `.png`만 받는다.
API 입력 계약은 파일 경로가 아니라 `base64 + mime_type`으로 둔다.

| 확장자 | MIME 타입 | 처리 여부 |
|---|---|---:|
| `.jpg` | `image/jpeg` | 지원 |
| `.jpeg` | `image/jpeg` | 지원 |
| `.png` | `image/png` | 지원 |
| `.webp` | `image/webp` | MVP 제외 |
| `.pdf` | `application/pdf` | MVP 제외 |

base64를 사용하는 이유는 이미지 파일의 바이너리를 API 요청 본문에 안전하게 넣기 위해서다.
교통사고사실확인원은 개인정보가 포함될 수 있으므로, 외부 공개 URL을 만들어 모델에 전달하는 방식보다 base64 직접 전달이 더 적합하다.
또한 참고 구현인 `ai/agents/fine_notice_analysis/agent.py`도 이미지 입력을 base64 기반으로 처리하므로 기존 패턴을 가져오기 쉽다.

예상 입력 형태는 다음과 같다.

```text
data:image/png;base64,{base64_image}
data:image/jpeg;base64,{base64_image}
```

base64 외에도 base32, base58, base85 같은 인코딩은 있지만, 이미지 data URL과 Vision/OCR API 입력에서는 일반적으로 base64를 사용한다.
따라서 MVP에서는 다른 base 계열 인코딩을 고려하지 않는다.

예상 코드 흐름은 다음과 같다.

```python
from pathlib import Path
import base64

def encode_image_to_base64(path: str) -> tuple[str, str]:
    image_path = Path(path)
    suffix = image_path.suffix.lower()

    if suffix in [".jpg", ".jpeg"]:
        mime_type = "image/jpeg"
    elif suffix == ".png":
        mime_type = "image/png"
    else:
        raise ValueError(f"unsupported image type: {suffix}")

    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return encoded, mime_type
```

예상 결과는 다음과 같다.

```python
base64_image, mime_type = encode_image_to_base64("sample.png")

# mime_type == "image/png"
# base64_image == "iVBORw0KGgoAAAANSUhEUgAA..."
```

---

## 3. 처리 흐름

흐름도는 MVP 단계에서 단순하게 유지한다.  
세부 검증 기준, 2page deferred 처리, 개인정보 처리, failure_reason, quality 정보는 흐름도에 추가하지 않고 **스키마와 설명 문단에만 반영**한다.

```mermaid
flowchart TD
    A([Supervisor가<br/>교통사고사실확인원 OCR LangGraph 호출]) --> B["OCR 수행<br/>이미지 글자 인식<br/>원문 텍스트 생성"]

    B --> C["교통사고사실확인원 여부 확인<br/>제목 및 주요 항목 확인"]

    C --> D{"교통사고사실확인원으로<br/>확인되는가?"}

    D -- "No" --> E["사용자용 오류 메시지 생성<br/>교통사고사실확인원 이미지만<br/>업로드 가능합니다"]

    E --> F["임시 이미지 삭제"]

    F --> G([종료:<br/>재업로드 필요])

    D -- "Yes" --> H["항목 매핑 및 OCR 결과 생성<br/>뽑힌 항목 정리<br/>안 뽑힌 항목 정리<br/>표준 형식으로 정리"]

    H --> I["임시 이미지 삭제"]

    I --> J["Supervisor로 OCR 결과 전달<br/>뽑힌 항목 + 안 뽑힌 항목 전달"]

    J --> K([완료:<br/>Supervisor 판단 대기])
```

### 실제 LangGraph 노드 구조

흐름도는 발표와 공유를 위해 단순하게 유지하지만, 실제 코드는 아래 두 노드로 나누는 것이 좋다.

```text
ocr_node
  - MIME 타입 확인
  - base64 디코딩 가능 여부 확인
  - GPT Vision/OCR 호출
  - JSON 파싱
  - 개인정보 1차 마스킹
  - 필드 정규화
  - success/partial/failed 1차 판정

document_verification_node
  - 제목/핵심 라벨/발급 문서 구조 점수 검증
  - 날짜, 숫자, 사고유형 enum 형식 검증
  - 최종 status 조정
  - Supervisor 전달 envelope 생성
```

라우팅은 아래처럼 둔다.

```text
ocr_node 결과가 failed이면 END
ocr_node 결과가 partial이어도 문서 검증이 가능하면 document_verification_node
ocr_node 결과가 success이면 document_verification_node
document_verification_node 이후 END
```

`partial`을 바로 종료하지 않는 이유는 이 문서에서 “교통사고사실확인원 여부 검증”이 중요하기 때문이다.
일부 필드가 누락되어도 제목, 사고 핵심 라벨, 경찰 발급 문서 구조가 확인되면 Supervisor가 추가 질문이나 재업로드 요청을 더 정확히 만들 수 있다.

---

## 4. 처리 흐름 설명

처리 흐름은 다음과 같이 단순하게 유지한다.

1. Supervisor가 교통사고사실확인원 OCR LangGraph를 호출한다.
2. OCR을 수행하여 이미지에서 원문 텍스트를 생성한다.
3. 제목과 주요 항목 라벨을 기준으로 교통사고사실확인원 여부를 확인한다.
4. 교통사고사실확인원이 아니면 사용자용 오류 메시지를 생성하고 재업로드가 필요하다는 결과를 반환한다.
5. 교통사고사실확인원으로 확인되면 주요 항목을 매핑하고 OCR 결과를 생성한다.
6. 뽑힌 항목과 안 뽑힌 항목을 표준 형식으로 정리한다.
7. 임시 이미지를 삭제한다.
8. Supervisor에게 OCR 결과를 전달한다.

---

## 5. 교통사고사실확인원 여부 확인 기준

교통사고사실확인원 여부는 단순히 문서 제목만으로 판단하지 않는다.  
OCR 결과에서 다음 세 가지 기준을 함께 확인하여 대상 문서 여부를 판단한다.

| 기준 | 확인 내용 | 판단 방식 |
|---|---|---|
| 1차 기준 | 제목 확인 | OCR 원문에 `교통사고사실확인원` 또는 유사 문구가 있는지 확인 |
| 2차 기준 | 사고 핵심 항목 라벨 확인 | `발생일시`, `발생장소`, `사고유형`, `사고원인`, `피해내용`, `사고내용` 중 일정 개수 이상 존재 |
| 3차 기준 | 경찰 발급 문서 구조 확인 | `교통사고 접수번호`, `발급번호`, `경찰서`, `용도`, `담당자`, `경찰서장` 등 발급 문서형 요소 확인 |

즉, 단순히 제목만 보는 것이 아니라 다음 3가지를 함께 확인한다.

```text
제목 + 사고 핵심 라벨 + 경찰 발급 문서 구조
```

### 5-1. 추천 판정 로직

```text
교통사고사실확인원 판정 기준

1. 제목 기준
- "교통사고사실확인원" 문구가 있으면 +1

2. 사고 항목 라벨 기준
- 발생일시
- 발생장소
- 사고유형
- 사고원인
- 피해내용
- 사고내용

위 6개 중 4개 이상 확인되면 +1

3. 발급 문서 구조 기준
- 교통사고 접수번호
- 발급번호
- 경찰서
- 용도
- 담당자
- 경찰서장

위 항목 중 2개 이상 확인되면 +1

총 3점 중 2점 이상이면 교통사고사실확인원으로 판단한다.
단, 제목이 없고 나머지 기준만 충족한 경우에는 완전한 success가 아니라 partial 또는 확인 필요 상태로 처리할 수 있다.
```

### 5-2. 제목만으로 판단하지 않는 이유

제목만 기준으로 하면 다음과 같은 이미지가 잘못 통과될 수 있다.

```text
교통사고사실확인원 발급 안내문
교통사고사실확인원 신청서
블로그 캡처
정부24 안내 화면
보험사 제출 안내문
```

이런 이미지에도 “교통사고사실확인원”이라는 단어가 포함될 수 있다.  
따라서 실제 확인원 1page에 포함되는 사고 항목 라벨과 경찰 발급 문서 구조를 함께 확인해야 한다.

진짜 교통사고사실확인원 1page라면 보통 아래 항목들이 함께 나타난다.

```text
발생일시
발생장소
사고유형
사고원인
피해내용
사고내용
용도
담당자
```

이 조합이 확인되면 단순 안내문이 아니라 실제 확인원일 가능성이 높다.

---

## 6. 1page / 2page 처리 기준

교통사고사실확인원은 1page 본문과 2page 사고현장약도로 구성될 수 있다.

MVP 단계에서는 1page를 OCR의 핵심 대상으로 본다.  
1page에서 사고일시, 사고장소, 사고유형, 사고원인, 피해내용, 사고내용 등 과실비율 분석에 필요한 공식 사고 기록을 추출한다.

2page 사고현장약도는 현재 단계에서 이미지 분석을 수행하지 않는다.  
약도는 도로 구조, 차량 진행 방향, 충돌 지점 등을 Vision 기반으로 해석해야 하므로, 추후 실제로 필요하다고 판단될 때 별도 Vision 분석 노드로 확장한다.

따라서 현재 스키마에는 2page를 분석하지 않았다는 상태만 남긴다.

```json
{
  "scene_diagram": {
    "page_2_exists": false,
    "analysis_status": "not_provided",
    "reason": "MVP 단계에서는 1page만 업로드 대상으로 설정",
    "raw_image_ref": null
  }
}
```

만약 사용자가 2page까지 함께 업로드한 경우에도 MVP 단계에서는 다음과 같이 기록만 한다.

```json
{
  "scene_diagram": {
    "page_2_exists": true,
    "analysis_status": "deferred",
    "reason": "MVP 단계에서는 사고현장약도 Vision 분석 제외",
    "raw_image_ref": null
  }
}
```

---

## 7. 반환 상태 기준

OCR LangGraph는 다음 세 가지 상태 중 하나로 결과를 반환한다.

| status | 의미 |
|---|---|
| success | 교통사고사실확인원으로 확인되었고 주요 항목이 정상 추출된 상태 |
| partial | 교통사고사실확인원으로 확인되었지만 일부 항목이 누락된 상태 |
| failed | 교통사고사실확인원으로 확인되지 않거나 OCR 처리가 불가능한 상태 |

실패 상태에서는 실패 원인을 구분하기 위해 `failure_reason`을 함께 반환한다.

| failure_reason | 의미 |
|---|---|
| not_target_document | 교통사고사실확인원이 아닌 문서 |
| low_image_quality | 이미지 품질 문제로 OCR이 어려운 경우 |
| ocr_failed | OCR 처리 자체가 실패한 경우 |
| page_1_not_found | 교통사고사실확인원 1page를 확인하지 못한 경우 |
| unsupported_file_type | 지원하지 않는 파일 형식 |

상태 판정은 문서 여부와 필드 누락 정도를 함께 본다.
모든 필드를 동일하게 취급하면 접수번호 하나가 누락되어도 전체 실패가 되거나,
반대로 사고내용이 빠졌는데도 성공으로 처리되는 문제가 생긴다.
따라서 과실비율 Agent가 직접 쓰는 필드는 `critical`, 문서 식별이나 보조 설명에 가까운 필드는 `important`로 나눈다.

```python
CRITICAL_FIELDS = [
    "accident_datetime",
    "accident_location",
    "accident_type.value",
    "accident_description",
]

IMPORTANT_FIELDS = [
    "receipt_number",
    "issue_number",
    "police_station",
    "accident_cause",
    "damage.raw_text",
    "usage",
]
```

| 조건 | status | 이유 |
|---|---|---|
| 대상 문서가 아니거나 OCR 호출/파싱 실패 | failed | 후속 Agent가 신뢰할 수 있는 사고 기록이 없음 |
| 대상 문서이고 critical 필드가 모두 있음 | success | 과실비율 분석에 필요한 최소 사고 사실 확보 |
| 대상 문서이나 critical 또는 important 일부 누락 | partial | 추가 질문, 재업로드, 사용자 확인으로 보완 가능 |

`partial`은 실패가 아니다.
Supervisor가 부족한 항목을 사용자에게 확인하거나, 기존 대화 내용으로 보완할 수 있는 상태다.

---

## 8. OCR LangGraph Output Schema

```json
{
  "node_code": "traffic_accident_confirmation_ocr",
  "status": "success | partial | failed",
  "document_type": "traffic_accident_confirmation | unknown",
  "message": "OCR 처리 결과 요약 메시지",
  "failure_reason": null,

  "structured_result": {
    "document_check": {
      "is_target_document": true,
      "document_name": "교통사고사실확인원",
      "reason": "제목, 사고 핵심 라벨, 경찰 발급 문서 구조 기준 확인",
      "verification_score": 3,
      "verification_criteria": {
        "title_matched": true,
        "accident_labels_matched_count": 6,
        "issuer_structure_matched_count": 4
      }
    },

    "page_info": {
      "page_1_processed": true,
      "page_2_exists": false
    },

    "extracted_fields": {
      "receipt_number": null,
      "issue_number": null,
      "police_station": null,

      "accident_datetime": null,
      "accident_location": null,

      "accident_type": {
        "value": null,
        "raw_text": null
      },

      "accident_cause": null,

      "damage": {
        "raw_text": null,
        "death_count": null,
        "injury_count": null,
        "property_damage_amount": null
      },

      "accident_description": null,
      "usage": null
    },

    "scene_diagram": {
      "page_2_exists": false,
      "analysis_status": "not_provided | deferred",
      "reason": "MVP 단계에서는 사고현장약도 Vision 분석 제외",
      "raw_image_ref": null
    },

    "missing_fields": []
  },

  "quality": {
    "ocr_confidence": null,
    "image_quality": "readable | low | unreadable",
    "warnings": []
  },

  "privacy": {
    "masking_applied": true,
    "excluded_sensitive_fields": [
      "resident_registration_number",
      "driver_license_number"
    ],
    "masked_fields": [
      "name",
      "address",
      "phone_number",
      "vehicle_number",
      "owner_name"
    ]
  },

  "limitations": []
}
```

---

## 9. extracted_fields 설명

| 필드명 | 의미 |
|---|---|
| receipt_number | 교통사고 접수번호 |
| issue_number | 발급번호 |
| police_station | 담당 경찰서 |
| accident_datetime | 사고 발생 일시 |
| accident_location | 사고 발생 장소 |
| accident_type.value | 사고유형 정리값 |
| accident_type.raw_text | 사고유형 OCR 원문 |
| accident_cause | 사고원인 |
| damage.raw_text | 피해내용 OCR 원문 |
| damage.death_count | 사망자 수 |
| damage.injury_count | 부상자 수 |
| damage.property_damage_amount | 물적 피해 금액 |
| accident_description | 사고내용 |
| usage | 발급 용도 |

기존에 고려했던 `person_role`은 제외한다.  
최신 교통사고사실확인원 양식에서 가해자/피해자 구분은 항상 존재하는 필드가 아니므로, OCR 필수 추출 항목으로 두지 않는다.

---

## 10. 과실비율 Agent 사용 관점의 핵심 필드

OCR LangGraph의 Output은 이후 과실비율 Agent가 참고할 수 있는 공식 사고 기록이다.  
따라서 과실비율 Agent 입장에서 중요한 필드는 다음과 같이 나눌 수 있다.

### 10-1. 과실비율 분석에 직접 사용되는 필드

| 필드 | 사용 목적 |
|---|---|
| accident_datetime | 사고 시점 확인, 야간/주간 여부 등 추가 판단 가능 |
| accident_location | 도로 유형, 교차로, 고속도로, 주차장 등 사고 장소 판단의 단서 |
| accident_type.value | 차대차, 차량단독, 차대사람 등 기본 사고 유형 분류 |
| accident_cause | 경찰 기록상 사고원인 확인 |
| damage.raw_text | 인피/물피 등 피해 내용 확인 |
| accident_description | 과실비율 분석의 핵심 사고 설명 |
| scene_diagram.analysis_status | 약도 분석이 포함되었는지 여부 확인 |

### 10-2. 보고서 업데이트 또는 문서 식별에 사용되는 필드

| 필드 | 사용 목적 |
|---|---|
| receipt_number | 교통사고 접수번호 기록 |
| issue_number | 발급번호 기록 |
| police_station | 담당 경찰서 기록 |
| usage | 발급 용도 기록 |
| document_check | OCR 결과 신뢰 여부 확인 |
| quality | OCR 품질 및 경고 확인 |
| missing_fields | 사용자 추가 질문 생성에 활용 |

### 10-3. 과실비율 Agent가 직접 사용하지 않는 개인정보성 필드

| 항목 | 처리 |
|---|---|
| 성명 | 필요 시 마스킹 |
| 주민등록번호 | Supervisor 전달 결과에서 제외 |
| 주소 | 필요 시 마스킹 |
| 전화번호 | 필요 시 마스킹 |
| 운전면허번호 | Supervisor 전달 결과에서 제외 |
| 차량번호 | 필요 시 마스킹 |
| 소유자명 | 필요 시 마스킹 |

---

## 11. success 반환 예시

```json
{
  "node_code": "traffic_accident_confirmation_ocr",
  "status": "success",
  "document_type": "traffic_accident_confirmation",
  "message": "교통사고사실확인원 OCR 처리가 완료되었습니다.",
  "failure_reason": null,

  "structured_result": {
    "document_check": {
      "is_target_document": true,
      "document_name": "교통사고사실확인원",
      "reason": "제목, 사고 핵심 라벨, 경찰 발급 문서 구조 기준 확인",
      "verification_score": 3,
      "verification_criteria": {
        "title_matched": true,
        "accident_labels_matched_count": 6,
        "issuer_structure_matched_count": 4
      }
    },

    "page_info": {
      "page_1_processed": true,
      "page_2_exists": false
    },

    "extracted_fields": {
      "receipt_number": "2026-000000",
      "issue_number": "제2026-000000호",
      "police_station": "○○경찰서",

      "accident_datetime": "2026.06.25 14:30",
      "accident_location": "서울시 ○○구 ○○로",

      "accident_type": {
        "value": "차대차",
        "raw_text": "■ 차대차 □ 차량단독 □ 차대사람 □ 기타"
      },

      "accident_cause": "안전운전의무 위반",

      "damage": {
        "raw_text": "부상 1명, 물피 있음",
        "death_count": 0,
        "injury_count": 1,
        "property_damage_amount": null
      },

      "accident_description": "교차로에서 직진 차량과 좌회전 차량이 충돌한 사고",
      "usage": "보험회사 제출용"
    },

    "scene_diagram": {
      "page_2_exists": false,
      "analysis_status": "not_provided",
      "reason": "MVP 단계에서는 1page만 업로드 대상으로 설정",
      "raw_image_ref": null
    },

    "missing_fields": []
  },

  "quality": {
    "ocr_confidence": null,
    "image_quality": "readable",
    "warnings": []
  },

  "privacy": {
    "masking_applied": true,
    "excluded_sensitive_fields": [
      "resident_registration_number",
      "driver_license_number"
    ],
    "masked_fields": [
      "name",
      "address",
      "phone_number",
      "vehicle_number",
      "owner_name"
    ]
  },

  "limitations": [
    "2page 사고현장약도는 현재 단계에서 분석하지 않았습니다."
  ]
}
```

---

## 12. partial 반환 예시

```json
{
  "node_code": "traffic_accident_confirmation_ocr",
  "status": "partial",
  "document_type": "traffic_accident_confirmation",
  "message": "교통사고사실확인원으로 확인되었으나 일부 항목이 누락되었습니다.",
  "failure_reason": null,

  "structured_result": {
    "document_check": {
      "is_target_document": true,
      "document_name": "교통사고사실확인원",
      "reason": "제목과 주요 항목 라벨은 확인되었으나 일부 발급 문서 구조 항목이 부족합니다.",
      "verification_score": 2,
      "verification_criteria": {
        "title_matched": true,
        "accident_labels_matched_count": 4,
        "issuer_structure_matched_count": 1
      }
    },

    "page_info": {
      "page_1_processed": true,
      "page_2_exists": false
    },

    "extracted_fields": {
      "receipt_number": null,
      "issue_number": null,
      "police_station": "○○경찰서",

      "accident_datetime": "2026.06.25 14:30",
      "accident_location": "서울시 ○○구 ○○로",

      "accident_type": {
        "value": "차대차",
        "raw_text": "차대차"
      },

      "accident_cause": null,

      "damage": {
        "raw_text": "부상 1명, 물피 있음",
        "death_count": null,
        "injury_count": 1,
        "property_damage_amount": null
      },

      "accident_description": "교차로에서 직진 차량과 좌회전 차량이 충돌한 사고",
      "usage": null
    },

    "scene_diagram": {
      "page_2_exists": false,
      "analysis_status": "not_provided",
      "reason": "2page 사고현장약도 이미지가 업로드되지 않았습니다.",
      "raw_image_ref": null
    },

    "missing_fields": [
      "receipt_number",
      "issue_number",
      "accident_cause",
      "usage"
    ]
  },

  "quality": {
    "ocr_confidence": null,
    "image_quality": "readable",
    "warnings": [
      "일부 항목 라벨 또는 값이 흐리게 인식되었습니다."
    ]
  },

  "privacy": {
    "masking_applied": true,
    "excluded_sensitive_fields": [
      "resident_registration_number",
      "driver_license_number"
    ],
    "masked_fields": [
      "name",
      "address",
      "phone_number",
      "vehicle_number",
      "owner_name"
    ]
  },

  "limitations": [
    "접수번호, 발급번호, 사고원인, 용도는 OCR 결과에서 확인되지 않았습니다.",
    "2page 사고현장약도는 업로드되지 않았습니다."
  ]
}
```

---

## 13. failed 반환 예시

```json
{
  "node_code": "traffic_accident_confirmation_ocr",
  "status": "failed",
  "document_type": "unknown",
  "message": "교통사고사실확인원 이미지만 업로드 가능합니다.",
  "failure_reason": "not_target_document",

  "structured_result": {
    "document_check": {
      "is_target_document": false,
      "document_name": "unknown",
      "reason": "교통사고사실확인원 제목, 사고 핵심 라벨, 경찰 발급 문서 구조를 충분히 확인하지 못했습니다.",
      "verification_score": 0,
      "verification_criteria": {
        "title_matched": false,
        "accident_labels_matched_count": 0,
        "issuer_structure_matched_count": 0
      }
    },

    "page_info": {
      "page_1_processed": false,
      "page_2_exists": false
    },

    "extracted_fields": {
      "receipt_number": null,
      "issue_number": null,
      "police_station": null,

      "accident_datetime": null,
      "accident_location": null,

      "accident_type": {
        "value": null,
        "raw_text": null
      },

      "accident_cause": null,

      "damage": {
        "raw_text": null,
        "death_count": null,
        "injury_count": null,
        "property_damage_amount": null
      },

      "accident_description": null,
      "usage": null
    },

    "scene_diagram": {
      "page_2_exists": false,
      "analysis_status": "not_provided",
      "reason": null,
      "raw_image_ref": null
    },

    "missing_fields": [
      "traffic_accident_confirmation_document"
    ]
  },

  "quality": {
    "ocr_confidence": null,
    "image_quality": "unknown",
    "warnings": []
  },

  "privacy": {
    "masking_applied": false,
    "excluded_sensitive_fields": [],
    "masked_fields": []
  },

  "limitations": [
    "업로드된 이미지에서 교통사고사실확인원으로 확인 가능한 제목, 주요 항목 라벨, 발급 문서 구조를 찾지 못했습니다."
  ]
}
```

---

## 14. 개인정보 처리 기준

교통사고사실확인원에는 성명, 주민등록번호, 주소, 전화번호, 운전면허번호, 차량번호, 소유자명 등이 포함될 수 있다.

그러나 과실비율 분석에 직접 필요한 항목은 사고일시, 사고장소, 사고유형, 사고원인, 피해내용, 사고내용 중심이다.

따라서 개인정보 처리 원칙은 다음과 같다.

- 원본 이미지는 영구 저장하지 않는다.
- OCR 처리 후 임시 이미지는 삭제한다.
- 주민등록번호와 운전면허번호는 Supervisor 전달 결과에서 제외한다.
- 성명, 주소, 전화번호, 차량번호, 소유자명은 필요 시 마스킹한다.
- Supervisor에는 과실비율 분석에 필요한 사고 사실 정보 중심으로 전달한다.
- 개인정보가 포함된 raw OCR text 저장 여부는 별도 정책으로 제한한다.

개인정보 정책에서 가장 중요한 구분은 `사고 장소`와 `사람의 주소`가 다르다는 점이다.
사고 장소는 사고 정황과 도로 상황 판단에 필요하므로 추출해야 하지만,
거주지 주소나 차량 소유자 주소는 과실비율 판단에 직접 필요하지 않으므로 추출하지 않는다.

추출해야 하는 정보는 다음으로 제한한다.

| 필드 | 추출 여부 | 이유 |
|---|---:|---|
| 사고 일시 | 추출 | 사고 정황 판단의 핵심 |
| 사고 장소 | 추출 | 사고 지점/도로 상황 판단에 필요 |
| 사고 유형 | 추출 | 차대차, 차대사람, 단독사고 등 분류 필요 |
| 사고 원인 | 추출 | 신호위반, 안전거리, 진로변경 등 판단 근거 |
| 피해 내용 | 추출 | 인적/물적 피해 여부 확인 |
| 사고 개요 | 추출 | 과실 판단 Agent에 전달할 핵심 문장 |
| 접수번호/발급번호 | 선택 추출 | 문서 식별용 메타데이터 |
| 경찰서/발급기관 | 선택 추출 | 문서 신뢰도 확인용 메타데이터 |

추출하지 않거나 마스킹해야 하는 정보는 다음과 같다.

| 정보 | 기본 정책 | 이유 |
|---|---|---|
| 성명 | 제외 또는 마스킹 | 과실 판단에 직접 필요하지 않음 |
| 주민등록번호 | 제외 | 민감정보 |
| 운전면허번호 | 제외 | 민감정보 |
| 전화번호 | 제외 | 연락처 개인정보 |
| 거주지 주소 | 제외 | 사고 장소와 다름 |
| 소유자 주소 | 제외 | 과실 판단에 불필요 |
| 차량번호 | 기본 제외, 필요 시 마스킹 | 차량 식별정보 |
| 소유자명 | 제외 또는 마스킹 | 과실 판단에 불필요 |

프롬프트에는 다음 지침을 넣는다.

```text
주민등록번호, 운전면허번호, 성명, 전화번호, 거주지 주소, 소유자 주소, 차량번호, 소유자명은 추출하지 마세요.
사고 발생 장소는 추출하되, 사람의 주소나 연락처는 추출하지 마세요.
불필요한 개인정보가 보이면 값으로 저장하지 말고 null로 두세요.
```

코드 후처리에서도 `fine_notice_analysis/masking.py`처럼 정규식 기반 마스킹 함수를 두어,
모델이 실수로 개인정보를 반환하더라도 저장 전 한 번 더 제거한다.

예상 마스킹 예시는 다음과 같다.

```python
masked = mask_sensitive_text("홍길동 010-1234-5678 서울시 ... 12가3456")

# "홍*동 010-****-**** 서울시 ... **가****"
```

이미지 저장 정책은 다음과 같이 둔다.

- Agent 상태에는 `document_image = None`을 기본값으로 둔다.
- 원본 이미지는 영구 저장하지 않는다.
- 테스트용 raw 폴더의 원본은 입력 데이터로만 사용한다.
- 임시 파일을 만들었다면 처리 후 삭제한다.
- 전체 OCR 원문 로그는 기본 저장하지 않는다.
- 디버깅이 필요하면 마스킹된 로그만 남긴다.

---

## 15. Supervisor 전달 기준

OCR LangGraph는 결과를 직접 판단하거나 과실비율을 계산하지 않는다.

OCR LangGraph의 역할은 다음으로 제한한다.

- 교통사고사실확인원 이미지 OCR 수행
- 교통사고사실확인원 여부 확인
- 주요 항목 추출
- 뽑힌 항목과 안 뽑힌 항목 정리
- 개인정보 제외 또는 마스킹
- 2page 사고현장약도 분석 보류 상태 기록
- Supervisor가 사용할 수 있는 구조화 결과 반환

Supervisor는 OCR 결과를 기반으로 다음 단계를 결정한다.

- 기존 보고서 업데이트
- 추가 질문 생성
- 부족한 항목 사용자 확인
- 과실비율 분석 LangGraph 또는 관련 노드 호출
- 추후 필요 시 2page Vision 분석 노드 호출

---

## 16. 과실비율 Agent 전달 시 주의사항

OCR 결과는 과실비율 분석의 참고 자료이지, 그 자체로 과실비율을 확정하는 근거가 아니다.

과실비율 Agent는 다음 자료를 함께 사용해야 한다.

- OCR로 추출된 교통사고사실확인원 공식 사고 기록
- 사용자가 챗봇 대화에서 입력한 사고 경위
- 추가 질문으로 보완된 사고 정보
- RAG로 검색한 과실비율 기준, 판례, 분쟁심의 사례
- 필요 시 사고현장약도 Vision 분석 결과

따라서 OCR Output Schema는 과실비율 Agent가 사용할 수 있도록 구조화하되, 다음 제한사항을 함께 전달해야 한다.

- OCR 결과는 이미지 품질에 따라 누락 또는 오인식이 발생할 수 있다.
- 교통사고사실확인원 1page만으로 차량 진행 방향, 충돌 지점, 도로 구조를 모두 알 수 없다.
- 2page 사고현장약도는 MVP 단계에서 분석하지 않는다.
- 과실비율 최종 판단은 OCR 결과만으로 수행하지 않는다.
- OCR 결과와 사용자 진술이 충돌할 경우 Supervisor 또는 과실비율 Agent가 추가 확인 질문을 생성해야 한다.

---

## 17. 본 이슈 범위

본 이슈는 교통사고사실확인원 OCR LangGraph의 결과 스키마 정의와 기본 계획을 범위로 한다.

### 포함 범위

- 교통사고사실확인원 여부 확인
- OCR 결과 구조화
- 뽑힌 항목 / 안 뽑힌 항목 정리
- Supervisor 전달용 결과 스키마 정의
- 개인정보 처리 기준 정의
- 2page 사고현장약도 deferred 처리
- 과실비율 Agent가 사용할 수 있는 OCR Output 구조 정의

### 제외 범위

- 과실비율 판단
- 사고 경위 대화형 질문
- 1차 보고서 생성
- 보고서 업데이트 실제 수행
- 법률 판단 또는 소송 가능성 판단
- 2page 사고현장약도 Vision 분석
- 사고현장약도 기반 도로 구조, 차량 진행 방향, 충돌 지점 판단

---

## 18. 요약

교통사고사실확인원 OCR LangGraph는 과실비율 분석을 직접 수행하지 않는다.

이 LangGraph는 경찰서 발급 교통사고사실확인원 1page 이미지를 OCR 처리하고, 과실비율 분석과 보고서 업데이트에 필요한 공식 사고 기록을 구조화하여 Supervisor에게 전달하는 역할만 수행한다.

흐름도는 Supervisor 호출, OCR 수행, 교통사고사실확인원 여부 확인, 항목 매핑, 임시 이미지 삭제, Supervisor 결과 전달의 단순 흐름으로 유지한다.

교통사고사실확인원 여부는 단순히 제목만으로 판단하지 않고, `제목`, `사고 핵심 항목 라벨`, `경찰 발급 문서 구조`의 세 가지 기준을 함께 확인한다.

2page 사고현장약도는 MVP 단계에서 분석하지 않고, 존재 여부와 분석 보류 상태만 결과 스키마에 남긴다.

최종 Output Schema는 이후 과실비율 Agent가 공식 사고 기록으로 참고할 수 있도록 설계하되, OCR 결과만으로 과실비율을 확정하지 않도록 제한사항을 함께 전달한다.

---

## 19. 계획 검토 결과

현재 계획은 역할 분리, 1page 중심 MVP, 2page 사고현장약도 deferred 처리, 개인정보 마스킹 원칙이 잘 잡혀 있다.  
다만 실제 구현자가 바로 LangGraph 노드와 테스트를 만들기에는 아래 항목이 더 명확해야 한다.

### 19-1. 현재 계획에서 좋은 점

- OCR LangGraph가 과실비율 판단을 하지 않는다고 명확히 분리했다.
- 교통사고사실확인원 여부를 제목 하나로만 판단하지 않고, 제목 + 사고 핵심 라벨 + 경찰 발급 문서 구조를 함께 본다.
- 2page 사고현장약도는 MVP에서 분석하지 않고, 향후 Vision 노드로 분리한다.
- 개인정보를 Supervisor 전달 결과에서 제외하거나 마스킹한다는 원칙이 있다.
- 과실비율 Agent가 OCR 결과를 참고 자료로만 사용해야 한다는 제한사항이 명확하다.

### 19-2. 구현 전 확인해야 할 점

| 항목 | 문제 | 보완 방향 |
|---|---|---|
| 입력 계약 | jpg/png를 모두 받는다는 요구가 스키마에 명확하지 않다. | `image/jpeg`, `image/png`를 필수 지원 MIME으로 명시한다. |
| 상태값 기준 | `success`, `partial`, `failed`는 있으나 필수/권장 필드 기준이 부족하다. | critical/important 필드를 나누고 누락 기준으로 상태를 결정한다. |
| LangGraph 노드 구조 | 흐름도는 단순하지만 실제 노드 파일 단위가 없다. | `ocr_node`, `confidence_verification_node` 또는 `document_verification_node` 구조를 명시한다. |
| Supervisor envelope | 참고 구현처럼 `agent_results[node_code]`에 어떤 형태로 들어가는지 부족하다. | `node_name`, `node_code`, `status`, `summary`, `structured_result`, `missing_fields`, `next_actions`, `limitations`를 명시한다. |
| OCR 프롬프트 | 추출 필드만 있고 GPT/Vision 모델에 줄 JSON 반환 규칙이 없다. | JSON only, 없는 값 null, 개인정보 제외, 날짜/숫자 정규화 규칙을 추가한다. |
| 파일 정리 | 임시 이미지 삭제만 있고 base64 입력 처리 기준이 없다. | 입력은 base64 + mime_type, 처리 후 image field는 `None`으로 제거한다. |
| 테스트 기준 | 테스트 이미지 폴더는 있으나 합격/부분합격/실패 케이스 기준이 없다. | `raw/1page`의 jpg/png 샘플을 기준으로 스모크 테스트 항목을 만든다. |
| RAG 입력 연결 | 과실비율 Agent에서 어떤 평탄화 필드를 읽는지 약하다. | `ocr_evidence`에 넣을 최소 필드를 별도 정의한다. |

---

## 20. 권장 폴더 구조

참고 구현인 `ai/agents/fine_notice_analysis`는 OCR Agent를 `agent.py`, `graph.py`, `state.py`, `prompts.py`, `verification.py`, `masking.py`, `utils.py`, `evaluator.py`로 분리한다.  
교통사고사실확인원 OCR도 같은 패턴을 따르는 것이 좋다.

### 20-1. 현재 관련 폴더

```text
etl/fault_cases/src/OCR/
├─ traffic_accident_confirmation_ocr_langgraph_plan.md
└─ raw/
   └─ 1page/
      ├─ *.jpg
      └─ *.png

etl/fault_cases/Fault_cases_MD/흐름도/
└─ 교통사고사실확인원이 OCR LangGraph 프로세스 흐름도.md

ai/agents/fine_notice_analysis/
├─ agent.py
├─ evaluator.py
├─ graph.py
├─ masking.py
├─ prompts.py
├─ state.py
├─ utils.py
└─ verification.py
```

### 20-2. 구현 시 권장 생성 위치

OCR Agent는 `etl`보다 `ai/agents` 아래에 두는 편이 기존 구조와 맞다.  
`etl/fault_cases/src/OCR/raw/1page`는 개발/테스트 샘플 이미지 보관 위치로 유지한다.

```text
ai/agents/traffic_accident_confirmation_ocr/
├─ __init__.py
├─ agent.py          # 이미지 입력 검증, OCR/Vision 호출, 1차 필드 추출
├─ evaluator.py      # success/partial/failed 판정
├─ graph.py          # LangGraph 구성 및 fallback graph
├─ masking.py        # 개인정보 마스킹
├─ prompts.py        # OCR JSON 추출 프롬프트
├─ state.py          # State TypedDict와 Literal 상태 정의
├─ utils.py          # envelope, agent_results 업데이트
└─ verification.py   # 문서 여부/형식/정규화 검증

etl/fault_cases/src/OCR/raw/1page/
├─ 14-07-00-경기도남양주.png
├─ 15-07-18-광주광역시.jpg
├─ ...
└─ 24-08-26-충청남도.png
```

### 20-3. OCR 구현 진행 순서

폴더 구조를 먼저 확인한 뒤에는 아래 순서로 진행하는 것이 좋다.  
이 순서는 `fine_notice_analysis`의 기존 구조를 참고하되, 교통사고사실확인원 OCR에 필요한 입력 계약과 Supervisor 전달 규격을 먼저 고정하는 흐름이다.

#### 전체 단계

| 단계 | 작업 | 이유 | 완료 기준 |
|---:|---|---|---|
| 1 | 입력 기준 확정 | jpg/png를 모두 받아야 하므로 파일 형식과 입력 형태를 먼저 고정해야 한다. | `image/jpeg`, `image/png` 지원, 입력은 base64 + mime_type |
| 2 | Agent 폴더 생성 | 기존 OCR Agent와 같은 위치에 두어 Supervisor 연동 패턴을 맞춘다. | `ai/agents/traffic_accident_confirmation_ocr/` 생성 |
| 3 | State 정의 | 노드들이 주고받을 key를 먼저 정해야 이후 코드가 흔들리지 않는다. | `state.py`에 입력/출력 State 정의 |
| 4 | Utils/envelope 작성 | Supervisor가 받을 결과 형태를 먼저 고정해야 후속 노드가 같은 규격으로 결과를 넣는다. | `make_envelope`, `update_agent_results` 작성 |
| 5 | OCR 프롬프트 작성 | 모델이 반환할 JSON 구조를 정해야 `agent.py`의 파싱/정규화 기준이 생긴다. | `prompts.py`에 JSON only 프롬프트 작성 |
| 6 | 마스킹 유틸 작성 | OCR 결과에 개인정보가 섞일 수 있으므로 초기에 방어선을 만든다. | `masking.py`에 주민번호/면허번호/차량번호 등 마스킹 |
| 7 | 필드 판정 로직 작성 | success/partial 기준이 있어야 OCR 결과를 안정적으로 분류할 수 있다. | `evaluator.py`에 critical/important 기준 작성 |
| 8 | OCR 노드 구현 | 실제 이미지 입력 검증, GPT Vision 호출, JSON 파싱, 필드 정규화를 담당한다. | `agent.py`의 `ocr_node` 구현 |
| 9 | 문서 검증 노드 구현 | OCR 결과가 진짜 교통사고사실확인원인지 최종 검증한다. | `verification.py`의 `document_verification_node` 구현 |
| 10 | Graph 연결 | 노드 실행 순서와 실패/성공 라우팅을 고정한다. | `graph.py`에서 `ocr_node -> document_verification_node -> END` 연결 |
| 11 | raw/1page 테스트 | 실제 jpg/png 샘플로 MVP 요구를 만족하는지 확인한다. | jpg 1개, png 1개에서 `success` 또는 `partial` 반환 |

#### 실제 파일 작성 추천 순서

실제 코드를 만들 때는 아래 순서가 가장 안전하다.

```text
1. state.py
2. utils.py
3. prompts.py
4. masking.py
5. evaluator.py
6. agent.py
7. verification.py
8. graph.py
9. raw/1page 테스트
```

이 순서를 권장하는 이유는 다음과 같다.

- `state.py`를 먼저 만들면 모든 노드가 같은 입력/출력 계약을 공유한다.
- `utils.py`를 먼저 만들면 실패/성공 결과가 항상 같은 envelope로 Supervisor에 들어간다.
- `prompts.py`를 먼저 만들면 `agent.py`에서 어떤 JSON을 파싱해야 하는지 명확해진다.
- `masking.py`를 초기에 만들면 OCR raw 응답과 필드 값에 개인정보가 섞이는 위험을 줄일 수 있다.
- `evaluator.py`를 먼저 만들면 OCR 결과를 어떤 기준으로 `success`와 `partial`로 나눌지 고정된다.
- `agent.py`는 위 계약들을 모두 사용하므로 중간 이후에 구현하는 것이 좋다.
- `verification.py`는 OCR 결과를 받은 뒤 문서 여부와 형식 오류를 검증하는 후처리이므로 `agent.py` 다음이 자연스럽다.
- `graph.py`는 마지막에 노드들을 연결하는 파일이므로 각 노드가 준비된 뒤 작성한다.

#### 단계별 예상 실행 결과

입력 파일이 jpg인 경우:

```text
input:
  document_mime_type: image/jpeg
  document_image: base64 string

expected:
  ocr_status: success 또는 partial
  document_type: traffic_accident_confirmation
  document_image: None
  agent_results.traffic_accident_confirmation_ocr 존재
```

입력 파일이 png인 경우:

```text
input:
  document_mime_type: image/png
  document_image: base64 string

expected:
  ocr_status: success 또는 partial
  document_type: traffic_accident_confirmation
  document_image: None
  agent_results.traffic_accident_confirmation_ocr 존재
```

지원하지 않는 파일 형식인 경우:

```text
input:
  document_mime_type: application/pdf 또는 image/webp

expected:
  ocr_status: failed
  failure_reason: unsupported_file_type
  next_actions: 교통사고사실확인원 1page jpg/png 재업로드 요청
```

base64가 깨진 경우:

```text
input:
  document_mime_type: image/png
  document_image: invalid base64 string

expected:
  ocr_status: failed
  failure_reason: invalid_image_payload 또는 ocr_failed
  document_image: None
```

---

## 21. 구현 기준 상세

### 21-1. 입력 State

jpg와 png를 모두 받아야 하므로 입력은 파일 경로보다 base64 + mime_type을 기본 계약으로 둔다.  
테스트에서는 `raw/1page`의 로컬 파일을 base64로 읽어 이 State에 넣는다.

```python
from typing import Optional
from typing_extensions import TypedDict, Literal

OCRStatus = Literal["success", "partial", "failed"]
DocumentType = Literal["traffic_accident_confirmation", "unknown"]


class TrafficAccidentConfirmationOCRState(TypedDict, total=False):
    # Supervisor 입력
    document_image: Optional[str]       # base64, 처리 후 None
    document_mime_type: Optional[str]   # image/jpeg | image/png
    source_filename: Optional[str]

    # OCR 노드 출력
    ocr_status: Optional[OCRStatus]
    document_type: Optional[DocumentType]
    ocr_error: Optional[str]
    failure_reason: Optional[str]
    raw_text_redacted: Optional[str]
    extracted_fields: dict
    document_check: dict
    page_info: dict
    scene_diagram: dict
    quality: dict
    privacy: dict
    missing_fields: list[str]
    limitations: list[str]

    # Supervisor 수신
    agent_results: dict
```

### 21-2. 지원 파일 형식

MVP에서는 아래 MIME만 허용한다.

```text
image/jpeg
image/png
```

확장자는 `.jpg`, `.jpeg`, `.png`를 허용한다.  
`image/webp`, `application/pdf`는 현재 테스트 폴더 요구에는 없으므로 MVP에서는 제외하고, 필요 시 추후 확장한다.

지원하지 않는 형식이면 다음으로 반환한다.

```json
{
  "status": "failed",
  "failure_reason": "unsupported_file_type",
  "message": "jpg 또는 png 형식의 교통사고사실확인원 1page 이미지를 업로드해주세요."
}
```

### 21-3. LangGraph 노드 구조

참고 구현인 `fine_notice_analysis`와 맞추기 위해 아래 구조를 권장한다.

```text
ocr_node
  - mime_type 확인
  - base64 디코딩 가능 여부 확인
  - GPT Vision 또는 OCR 엔진 호출
  - JSON 파싱
  - 개인정보 1차 마스킹
  - 필드 정규화
  - critical 누락이면 partial 또는 failed envelope 생성

document_verification_node
  - 제목/핵심 라벨/발급 문서 구조 점수 검증
  - 날짜, 숫자, 사고유형 enum 등 형식 검증
  - 최종 status 조정
  - Supervisor envelope 생성
```

라우팅은 아래처럼 둔다.

```text
ocr_node 결과가 failed이면 END
ocr_node 결과가 partial이어도 문서 검증이 가능하면 document_verification_node
ocr_node 결과가 success이면 document_verification_node
document_verification_node 이후 END
```

참고 구현은 `partial`을 바로 종료하지만, 이 문서는 “교통사고사실확인원 여부 검증”이 중요하므로 partial이어도 검증 노드를 한 번 더 태우는 편이 낫다.

### 21-4. base64 사용 기준과 이미지 전달 방식

OCR 대상 파일은 최종적으로 이미지 바이너리이지만, API 요청 본문에는 바이너리를 그대로 넣기 어렵다.
그래서 이미지 파일을 base64 문자열로 변환한 뒤 GPT Vision/OCR 입력에 넣는 방식을 사용한다.

예상 입력 형태는 다음과 같다.

```text
data:image/png;base64,{base64_image}
data:image/jpeg;base64,{base64_image}
```

base64를 사용하는 이유는 다음과 같다.

- 로컬 테스트 이미지도 별도 서버 업로드 없이 바로 모델에 전달할 수 있다.
- 교통사고사실확인원은 개인정보가 섞일 가능성이 있으므로 공개 URL 방식보다 안전하다.
- `fine_notice_analysis/agent.py`도 이미지/PDF를 base64로 모델에 전달하는 구조를 사용하고 있어 참고하기 쉽다.
- JPG와 PNG를 같은 흐름으로 처리할 수 있다.

대안은 있지만 MVP에서는 base64 직접 전달만 사용한다.

| 방식 | 설명 | MVP 적용 여부 | 이유 |
|---|---|---:|---|
| base64 직접 전달 | 로컬 이미지 파일을 읽어 base64 문자열로 변환해 요청 | 사용 | 구현이 단순하고 개인정보 문서에 적합 |
| 이미지 URL 전달 | 외부에서 접근 가능한 이미지 URL을 모델에 전달 | 제외 | 공개 URL 생성/권한 관리 부담이 있고 개인정보 노출 위험이 큼 |
| 파일 업로드 후 file_id 전달 | 파일 저장소에 먼저 올린 뒤 참조값으로 호출 | 후순위 | 운영 단계에서는 가능하지만 MVP에는 과함 |

주의할 점은 다음과 같다.

- base64 외에도 base32, base58, base85 같은 인코딩이 있지만, 이미지 API의 data URL 방식에서는 일반적으로 base64를 사용한다.
- base64는 원본보다 문자열 크기가 커지므로 너무 큰 이미지는 리사이즈 또는 압축이 필요하다.
- base64 문자열에 줄바꿈이 섞이면 디코딩 오류가 날 수 있으므로 저장/전달 전 정규화한다.
- Python에서는 `base64.b64decode(value, validate=True)`처럼 검증 옵션을 켜면 잘못된 입력을 빨리 잡을 수 있다.

예상 코드 흐름은 다음과 같다.

```python
from pathlib import Path
import base64

def encode_image_to_base64(path: str) -> tuple[str, str]:
    image_path = Path(path)
    suffix = image_path.suffix.lower()

    if suffix in [".jpg", ".jpeg"]:
        mime_type = "image/jpeg"
    elif suffix == ".png":
        mime_type = "image/png"
    else:
        raise ValueError(f"unsupported image type: {suffix}")

    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return encoded, mime_type
```

예상 결과는 다음과 같다.

```python
base64_image, mime_type = encode_image_to_base64("sample.png")

# mime_type == "image/png"
# base64_image == "iVBORw0KGgoAAAANSUhEUgAA..."
```

### 21-5. GPT Vision/OCR 호출 비용 관리 기준

이 계획은 GPT Vision/OCR 모델을 호출하는 구조이므로 실제 API 호출마다 비용이 발생한다.
특히 이미지는 텍스트보다 입력 비용이 커질 수 있으므로 테스트와 운영 호출을 분리해야 한다.

비용 관리를 위해 다음 기준을 둔다.

- MVP 입력 확장자는 `.jpg`, `.jpeg`, `.png`만 허용한다.
- 너무 큰 이미지는 모델 호출 전에 리사이즈/압축한다.
- 폴더 전체를 무조건 반복 호출하지 않는다.
- 첫 테스트는 JPG 1장, PNG 1장 정도의 smoke test로 제한한다.
- 실패 시 무한 재시도하지 않고 최대 재시도 횟수를 둔다.
- 같은 파일을 반복 테스트할 가능성이 있으면 파일 해시 기반 캐시를 후속으로 고려한다.
- 단위 테스트는 모델을 직접 호출하지 않고 mock 응답으로 검증한다.
- 실제 API 호출 테스트는 명시적으로 실행하는 통합 테스트로 분리한다.

테스트 단계별 예상 비용 발생 여부는 다음과 같다.

| 테스트 종류 | 모델 호출 여부 | 비용 발생 | 목적 |
|---|---:|---:|---|
| unit test | 없음 | 없음 | base64 변환, MIME 판정, 상태 판정 검증 |
| mock graph test | 없음 | 없음 | LangGraph 흐름과 success/partial/failed 분기 검증 |
| smoke test | 있음 | 있음 | 실제 JPG/PNG 1장씩 OCR 가능 여부 확인 |
| batch test | 있음 | 있음 | 여러 장 처리 성능/품질 확인, 명시적으로 실행 |

예상 실행 결과는 다음처럼 구분한다.

```text
unit test passed
mock graph test passed
real smoke test: 2 files processed, 1 success, 1 partial, 0 failed
```

이 기준을 두는 이유는 개발 중 실수로 전체 이미지 폴더를 반복 호출하면 비용이 예상보다 빠르게 증가할 수 있기 때문이다.
따라서 구현 초기에는 mock 기반 검증을 먼저 끝내고, 실제 모델 호출은 마지막 확인 단계에서만 수행한다.

### 21-6. 개인정보 최소 수집 및 제외 기준

교통사고사실확인원에는 사고 사실뿐 아니라 사람의 이름, 주소, 연락처, 차량번호 같은 민감 정보가 포함될 수 있다.
하지만 이 OCR Agent의 목적은 과실비율 판단에 필요한 사고 사실을 구조화하는 것이므로, 불필요한 개인정보는 애초에 추출하지 않는 방향이 안전하다.

추출해야 하는 정보는 다음으로 제한한다.

| 필드 | 추출 여부 | 이유 |
|---|---:|---|
| 사고 일시 | 추출 | 사고 정황 판단의 핵심 |
| 사고 장소 | 추출 | 사고 지점/도로 상황 판단에 필요 |
| 사고 유형 | 추출 | 차대차, 차대사람, 단독사고 등 분류 필요 |
| 사고 원인 | 추출 | 신호위반, 안전거리, 진로변경 등 판단 근거 |
| 피해 내용 | 추출 | 인적/물적 피해 여부 확인 |
| 사고 개요 | 추출 | 과실 판단 Agent에 전달할 핵심 문장 |
| 접수번호/발급번호 | 선택 추출 | 문서 식별용 메타데이터 |
| 경찰서/발급기관 | 선택 추출 | 문서 신뢰도 확인용 메타데이터 |

추출하지 않거나 마스킹해야 하는 정보는 다음과 같다.

| 정보 | 기본 정책 | 이유 |
|---|---|---|
| 성명 | 제외 또는 마스킹 | 과실 판단에 직접 필요하지 않음 |
| 주민등록번호 | 제외 | 민감정보 |
| 운전면허번호 | 제외 | 민감정보 |
| 전화번호 | 제외 | 연락처 개인정보 |
| 거주지 주소 | 제외 | 사고 장소와 다름 |
| 소유자 주소 | 제외 | 과실 판단에 불필요 |
| 차량번호 | 기본 제외, 필요 시 마스킹 | 차량 식별정보 |
| 소유자명 | 제외 또는 마스킹 | 과실 판단에 불필요 |

여기서 중요한 구분은 `사고 장소`와 `사람의 주소`가 다르다는 점이다.
사고 장소는 과실 판단에 필요한 정보이므로 추출해야 하지만,
거주지 주소나 차량 소유자 주소는 문서에 있더라도 추출하지 않는 것이 좋다.

프롬프트에는 다음 지침을 넣는다.

```text
주민등록번호, 운전면허번호, 성명, 전화번호, 거주지 주소, 소유자 주소, 차량번호, 소유자명은 추출하지 마세요.
사고 발생 장소는 추출하되, 사람의 주소나 연락처는 추출하지 마세요.
불필요한 개인정보가 보이면 값으로 저장하지 말고 null로 두세요.
```

코드 후처리에서도 한 번 더 방어한다.
`fine_notice_analysis/masking.py`처럼 정규식 기반 마스킹 함수를 만들고,
모델이 실수로 개인정보를 반환하더라도 저장 전 제거한다.

예상 마스킹 예시는 다음과 같다.

```python
masked = mask_sensitive_text("홍길동 010-1234-5678 서울시 ... 12가3456")

# "홍*동 010-****-**** 서울시 ... **가****"
```

이미지 저장 정책은 다음과 같이 둔다.

- Agent 상태에는 `document_image = None`을 기본값으로 둔다.
- 원본 이미지는 영구 저장하지 않는다.
- 테스트용 raw 폴더의 원본은 입력 데이터로만 사용한다.
- 임시 파일을 만들었다면 처리 후 삭제한다.
- 전체 OCR 원문 로그는 기본 저장하지 않는다.
- 디버깅이 필요하면 마스킹된 로그만 남긴다.

이 기준을 두는 이유는 OCR 품질보다 개인정보 노출 리스크가 더 큰 문제가 될 수 있기 때문이다.
따라서 추출 단계, 후처리 단계, 저장 단계에서 각각 한 번씩 개인정보를 줄이는 구조로 설계한다.

### 21-7. MVP 입력/비용/개인정보 정책 요약

MVP에서는 다음 정책으로 진행한다.

- OCR 방식: GPT Vision/OCR 사용
- 이미지 전달: base64 직접 전달
- 외부 이미지 URL: 사용하지 않음
- 지원 확장자: `.jpg`, `.jpeg`, `.png`
- 실제 API 호출: smoke test부터 제한적으로 수행
- 단위 테스트: mock 응답 기반으로 비용 없이 수행
- 개인정보: 사고 판단에 필요한 정보만 추출
- 이름/전화번호/주소/차량번호: 제외 또는 마스킹
- 원본 이미지: Agent 상태나 로그에 영구 저장하지 않음

---

## 22. 상태 판정 기준 상세

### 22-1. 문서 판정 기준

`verification_score`는 기존 계획대로 0~3점을 사용한다.

| 기준 | 점수 | 조건 |
|---|---:|---|
| title_matched | 1 | `교통사고사실확인원` 또는 OCR 오인식 보정 후 유사 제목 확인 |
| accident_labels_matched | 1 | `발생일시`, `발생장소`, `사고유형`, `사고원인`, `피해내용`, `사고내용` 중 4개 이상 |
| issuer_structure_matched | 1 | `교통사고 접수번호`, `발급번호`, `경찰서`, `용도`, `담당자`, `경찰서장` 중 2개 이상 |

판정은 아래처럼 한다.

| 조건 | status | document_type | 설명 |
|---|---|---|---|
| score 3 | success 또는 partial | traffic_accident_confirmation | 대상 문서 확실 |
| score 2 + title_matched true | success 또는 partial | traffic_accident_confirmation | 대상 문서 가능성 높음 |
| score 2 + title_matched false | partial | traffic_accident_confirmation | 제목 누락/오인식 가능, 확인 필요 |
| score 0~1 | failed | unknown | 대상 문서로 보기 어려움 |

### 22-2. 필드 누락 기준

과실비율 Agent가 직접 쓰는 필드를 critical로 둔다.

```python
CRITICAL_FIELDS = [
    "accident_datetime",
    "accident_location",
    "accident_type.value",
    "accident_description",
]

IMPORTANT_FIELDS = [
    "receipt_number",
    "issue_number",
    "police_station",
    "accident_cause",
    "damage.raw_text",
    "usage",
]
```

상태 판정은 아래처럼 한다.

| 조건 | status |
|---|---|
| 대상 문서가 아니거나 OCR 호출/파싱 실패 | failed |
| 대상 문서이고 critical 필드가 모두 있음 | success |
| 대상 문서이나 critical 또는 important 필드 일부 누락 | partial |

`partial`은 실패가 아니다. Supervisor가 추가 질문을 만들거나 사용자에게 재업로드/확인을 요청할 수 있는 상태다.

---

## 23. OCR 프롬프트 기준

`prompts.py`에는 아래 규칙이 들어가야 한다.

```text
당신은 한국 교통사고사실확인원 OCR 전문가입니다.
이미지에서 교통사고사실확인원 1page의 필드를 추출하여 JSON만 반환하세요.
설명, Markdown, 코드블록 없이 순수 JSON만 반환하세요.

문서가 교통사고사실확인원으로 보이지 않으면:
- document_type: "unknown"
- is_target_document: false
- 추출 불가 필드는 null

추출 필드:
- document_name
- receipt_number
- issue_number
- police_station
- accident_datetime
- accident_location
- accident_type_raw
- accident_type_value
- accident_cause
- damage_raw_text
- death_count
- injury_count
- property_damage_amount
- accident_description
- usage
- detected_labels
- issuer_labels
- quality_warnings

규칙:
- 이미지에 없는 필드는 null
- 날짜/시간은 가능한 원문을 보존하되, 명확하면 YYYY-MM-DD HH:mm 형식으로 정규화
- 금액은 숫자만 추출하고 불명확하면 null
- 사망자/부상자 수는 숫자로 추출하고 불명확하면 null
- 주민등록번호, 운전면허번호는 반환하지 않음
- 성명, 주소, 전화번호, 차량번호, 소유자명은 반환하지 않거나 마스킹
- 사고현장약도 또는 2page 내용은 분석하지 않음
```

---

## 24. Supervisor 전달 Envelope 기준

참고 구현과 맞추기 위해 최종 결과는 `agent_results["traffic_accident_confirmation_ocr"]`에 저장한다.

```json
{
  "node_name": "교통사고사실확인원 OCR 노드",
  "node_code": "traffic_accident_confirmation_ocr",
  "status": "success",
  "summary": "교통사고사실확인원 OCR 처리 완료",
  "structured_result": {},
  "evidence": [],
  "missing_fields": [],
  "next_actions": [
    "과실비율 분석 LangGraph 호출 가능"
  ],
  "limitations": [
    "OCR 결과는 이미지 품질에 따라 오인식될 수 있습니다.",
    "2page 사고현장약도는 MVP 단계에서 분석하지 않았습니다."
  ]
}
```

상태별 `next_actions`는 아래처럼 둔다.

| status | next_actions |
|---|---|
| success | `과실비율 분석 LangGraph 호출 가능` |
| partial | `누락 필드 사용자 확인`, `필요 시 이미지 재업로드 요청`, `과실비율 분석 시 제한사항 포함` |
| failed | `교통사고사실확인원 1page jpg/png 재업로드 요청` |

---

## 25. 과실비율 Agent 연결용 최소 OCR Evidence

과실비율 Agent에는 전체 OCR 결과를 그대로 넘기기보다, 아래 최소 필드를 `ocr_evidence`로 평탄화해서 넘기는 것이 좋다.

```json
{
  "source_reference": "traffic_accident_confirmation_ocr",
  "document_type": "traffic_accident_confirmation",
  "status": "success",
  "accident_datetime": "2026-06-25 14:30",
  "accident_location": "서울시 ○○구 ○○로",
  "accident_type": "차대차",
  "accident_cause": "안전운전의무 위반",
  "damage_summary": "부상 1명, 물피 있음",
  "accident_description": "교차로에서 직진 차량과 좌회전 차량이 충돌한 사고",
  "missing_fields": [],
  "limitations": [
    "OCR 결과만으로 과실비율을 확정하지 않습니다.",
    "2page 사고현장약도는 분석되지 않았습니다."
  ]
}
```

이 구조는 `text_ml_case_search` 쪽에서 이미 언급되는 `ocr_evidence` 선택 입력과도 맞다.

---

## 26. 테스트 계획 및 비용 관리

테스트 샘플은 아래 폴더를 기준으로 한다.

```text
etl/fault_cases/src/OCR/raw/1page
```

현재 샘플에는 `.jpg`, `.png`가 모두 있으므로 두 형식이 모두 통과해야 한다.

GPT Vision/OCR 모델을 실제로 호출하는 테스트는 비용이 발생한다.
따라서 모든 테스트를 실제 API 호출로 돌리지 않고, mock 기반 테스트와 실제 smoke test를 분리한다.

| 테스트 종류 | 모델 호출 여부 | 비용 발생 | 목적 |
|---|---:|---:|---|
| unit test | 없음 | 없음 | base64 변환, MIME 판정, 상태 판정 검증 |
| mock graph test | 없음 | 없음 | LangGraph 흐름과 success/partial/failed 분기 검증 |
| smoke test | 있음 | 있음 | 실제 JPG/PNG 1장씩 OCR 가능 여부 확인 |
| batch test | 있음 | 있음 | 여러 장 처리 성능/품질 확인, 명시적으로 실행 |

비용 관리를 위해 다음 기준을 둔다.

- 폴더 전체를 무조건 반복 호출하지 않는다.
- 첫 실제 테스트는 JPG 1장, PNG 1장 정도로 제한한다.
- 실패 시 무한 재시도하지 않고 최대 재시도 횟수를 둔다.
- 같은 파일을 반복 테스트할 가능성이 있으면 파일 해시 기반 캐시를 후속으로 고려한다.
- 실제 API 호출 테스트는 명시적으로 실행하는 통합 테스트로 분리한다.

예상 실행 결과는 다음처럼 구분한다.

```text
unit test passed
mock graph test passed
real smoke test: 2 files processed, 1 success, 1 partial, 0 failed
```

### 26-1. 스모크 테스트

| 테스트 | 기대 결과 |
|---|---|
| png 샘플 1개 입력 | `status`가 `success` 또는 `partial`, `document_image`는 반환에서 제거 |
| jpg 샘플 1개 입력 | `status`가 `success` 또는 `partial`, `document_image`는 반환에서 제거 |
| 지원하지 않는 확장자 입력 | `failed`, `failure_reason=unsupported_file_type` |
| base64 깨진 입력 | `failed`, `failure_reason=ocr_failed` 또는 `invalid_image_payload` |
| 대상 문서가 아닌 이미지 | `failed`, `failure_reason=not_target_document` |

### 26-2. 필드 테스트

| 테스트 | 기대 결과 |
|---|---|
| 사고일시/장소/유형/내용 모두 추출 | `success` |
| 사고내용 또는 사고유형 누락 | `partial`, `missing_fields`에 누락 필드 포함 |
| 접수번호/발급번호만 누락 | `partial` 또는 `success with warnings` 중 하나로 정책 고정 필요 |
| 주민등록번호/운전면허번호 인식 | Supervisor 결과에 포함하지 않음 |
| 차량번호 인식 | 필요 시 마스킹 |

현재 계획에서는 상태값을 3개만 사용하므로, `success with warnings`는 별도 상태로 만들지 않고 `quality.warnings`에 넣는 것을 권장한다.

---

## 27. 최종 판단

현재 MD는 기획 방향은 충분하지만, 구현 계획서로는 아래가 부족했다.

- jpg/png 입력 계약
- 실제 LangGraph 파일 구조
- 참고 구현과 같은 envelope 규격
- 필수/권장 필드 기반 status 판정
- OCR 프롬프트 규칙
- 테스트 기준
- 과실비율 Agent에 넘길 최소 `ocr_evidence` 형태

위 보완 내용을 반영하면, 이 MD는 단순 아이디어 문서가 아니라 실제 `traffic_accident_confirmation_ocr` Agent 구현 기준 문서로 사용할 수 있다.

---

## 28. 섹션별 결정 이유와 구현 근거

이 문서의 각 설계 결정은 단순 취향이 아니라, Supervisor와 후속 과실비율 Agent가 안정적으로 사용할 수 있는 입력을 만들기 위한 것이다.  
아래 표는 “왜 이렇게 정했는지”를 구현 관점에서 정리한 것이다.

| 섹션 | 결정 내용 | 이렇게 정한 이유 | 구현상 기대 효과 |
|---|---|---|---|
| 1. 목적 | OCR LangGraph는 과실비율 판단을 하지 않는다. | OCR 결과는 이미지 인식 결과라 오인식 가능성이 있고, 과실비율 판단은 RAG/사용자 진술/사고현장약도까지 함께 봐야 한다. | OCR 노드의 책임이 작아져 테스트와 유지보수가 쉬워진다. |
| 2. 업로드 기준 | MVP는 1page 이미지만 받는다. | 테스트 폴더가 `raw/1page` 중심이고, 2page 약도는 OCR보다 Vision 해석 문제에 가깝다. | 초기 구현 범위를 줄이고, 실제 사고 사실 필드 추출 성공률을 먼저 검증할 수 있다. |
| 3~4. 처리 흐름 | OCR -> 문서 여부 확인 -> 항목 매핑 -> Supervisor 전달로 단순화한다. | 흐름도가 복잡하면 어떤 노드에서 실패했는지 추적하기 어렵다. MVP에서는 핵심 성공/실패 경로가 명확해야 한다. | LangGraph 라우팅과 fallback graph 구현이 단순해진다. |
| 5. 문서 여부 확인 | 제목 + 사고 라벨 + 발급 구조를 함께 본다. | 안내문, 신청서, 블로그 캡처에도 `교통사고사실확인원` 문구가 있을 수 있다. | 대상 문서 오탐을 줄인다. |
| 6. 2page 처리 | 2page는 `deferred`로 기록만 한다. | 사고현장약도는 도로 구조, 방향, 충돌 지점 해석이 필요해서 OCR 필드 추출과 성격이 다르다. | 나중에 Vision 노드를 붙이더라도 현재 OCR 스키마를 깨지 않는다. |
| 7. 반환 상태 | `success`, `partial`, `failed` 3개로 둔다. | 상태가 너무 많으면 Supervisor 분기가 복잡해진다. `partial`과 `quality.warnings`로 대부분 표현 가능하다. | 후속 Agent가 단순한 상태값으로 라우팅할 수 있다. |
| 8~9. Output Schema | 원문 전체보다 구조화 필드를 중심으로 전달한다. | 개인정보가 포함된 raw text를 그대로 넘기면 보안 리스크가 커진다. 후속 Agent도 전체 원문보다 사고 필드가 필요하다. | 개인정보 노출을 줄이고 RAG 입력 생성이 쉬워진다. |
| 10. 과실비율 Agent 사용 필드 | 사고일시, 장소, 유형, 원인, 피해, 사고내용을 핵심으로 둔다. | 과실비율 검색과 쟁점 태깅에 직접 쓰이는 정보가 이 필드들이다. 접수번호/발급번호는 문서 식별용이지 사고 판단의 핵심은 아니다. | RAG 검색문 보강에 필요한 정보만 안정적으로 넘긴다. |
| 14. 개인정보 처리 | 주민등록번호/운전면허번호는 제외하고 차량번호 등은 마스킹한다. | 이 정보들은 과실비율 분석에 직접 필요하지 않고 민감도가 높다. | Supervisor와 로그에 민감정보가 남을 가능성을 낮춘다. |
| 20. 구현 위치 | Agent 구현은 `ai/agents` 아래에 둔다. | 기존 `fine_notice_analysis`가 같은 OCR Agent 성격으로 `ai/agents`에 있다. `etl`은 샘플/전처리 자료 위치로 보는 것이 자연스럽다. | 기존 Agent import, 테스트, Supervisor 연동 패턴을 재사용할 수 있다. |
| 21. 입력 State | base64 + MIME 타입을 입력 계약으로 둔다. | 웹/챗봇 업로드에서는 파일 경로보다 base64 payload와 MIME이 안정적인 전달 단위다. | 로컬 파일, API 업로드, 테스트 입력을 같은 구조로 처리할 수 있다. |
| 22. 필드 판정 | critical/important 필드를 나눈다. | 모든 필드를 동일하게 보면 접수번호 하나 누락 때문에 전체 실패가 될 수 있다. 반대로 사고내용 누락은 후속 분석에 치명적이다. | 실패와 부분 성공을 더 현실적으로 나눌 수 있다. |
| 23. 프롬프트 | JSON only, 없는 값 null, 개인정보 제외를 강제한다. | LLM이 설명 문장이나 Markdown을 섞으면 JSON 파싱이 깨진다. | `json.loads` 기반 파싱과 오류 처리가 단순해진다. |
| 24. Envelope | `agent_results[node_code]`에 표준 envelope를 넣는다. | Supervisor가 여러 Agent 결과를 같은 방식으로 수집해야 한다. | fine_notice_analysis와 같은 연동 패턴을 유지한다. |
| 25. 최소 OCR Evidence | 후속 Agent에는 평탄화된 최소 필드만 넘긴다. | 깊은 nested schema 전체를 넘기면 후속 Agent가 필요 없는 정보까지 의존하게 된다. | 과실비율 Agent의 입력 계약이 단순해지고 변경에 강해진다. |
| 26. 테스트 | jpg/png 스모크 테스트를 우선한다. | 실제 테스트 폴더에 jpg와 png가 모두 있으므로, 이 둘을 못 받으면 MVP 요구를 만족하지 못한다. | 파일 형식 이슈를 초기에 잡을 수 있다. |

---

## 29. `fine_notice_analysis` 참고 코드 활용 기준

`ai/agents/fine_notice_analysis`는 교통사고사실확인원 OCR과 도메인은 다르지만, “이미지 기반 OCR Agent를 LangGraph로 만들고 Supervisor에 envelope를 전달한다”는 구조가 같다.  
따라서 아래 기준으로 재사용한다.

### 29-1. 그대로 가져가도 좋은 패턴

| 참고 파일 | 참고할 코드/구조 | 가져갈 이유 | 교통사고사실확인원 OCR 적용 방식 |
|---|---|---|---|
| `state.py` | `TypedDict`, `Literal` 기반 State 정의 | LangGraph의 입출력 key가 명확해지고, 노드 간 상태 전달이 안정적이다. | `FineNoticeState` 대신 `TrafficAccidentConfirmationOCRState`를 만든다. |
| `graph.py` | `StateGraph`, `_route_after_ocr`, fallback graph | `langgraph`가 없는 환경에서도 `.invoke()` 테스트가 가능하다. | `ocr_node -> document_verification_node -> END` 흐름으로 변형한다. |
| `agent.py` | MIME 확인, base64 디코딩, 이미지 block 생성, GPT 호출, JSON 파싱 | OCR 입력 처리의 핵심 공통 로직이다. | 변수명과 허용 MIME만 교통사고사실확인원에 맞게 바꾼다. |
| `utils.py` | `make_envelope`, `update_agent_results` | Supervisor가 Agent 결과를 일관된 형태로 받게 해준다. | `node_code`를 `traffic_accident_confirmation_ocr`로 바꾼다. |
| `evaluator.py` | critical/important 기반 상태 판정 | 필드 누락을 체계적으로 `success/partial`로 나눌 수 있다. | 사고 분석 필드 기준으로 `CRITICAL_FIELDS`, `IMPORTANT_FIELDS`를 다시 정의한다. |
| `verification.py` | 형식 오류를 모아 `format_errors`에 넣고 partial로 조정 | 검증 오류를 하나만 보고 멈추지 않고 모두 수집한다. | 문서 판정 점수, 날짜/숫자/사고유형 검증 오류를 모은다. |
| `masking.py` | regex 기반 개인정보 마스킹 | OCR raw 응답이나 필드 값에 섞인 개인정보를 코드 레벨에서 한 번 더 막는다. | 주민등록번호, 운전면허번호, 차량번호, 전화번호 패턴을 추가한다. |
| `prompts.py` | JSON만 반환하도록 하는 프롬프트 구조 | LLM 응답 파싱 안정성을 높인다. | 추출 필드를 교통사고사실확인원 필드로 교체한다. |

### 29-2. 그대로 가져가면 안 되는 부분

| 참고 파일 | 그대로 쓰면 안 되는 코드 | 이유 | 대체 구현 |
|---|---|---|---|
| `agent.py` | `_classify_fine_type` | 과태료/범칙금/벌금 분류는 고지서 전용 로직이다. | `_verify_traffic_accident_confirmation` 또는 `document_check` 점수 계산으로 대체한다. |
| `agent.py` | PDF 변환 로직 | 현재 요구는 jpg/png 테스트 파일이고 PDF는 MVP 범위가 아니다. | MVP에서는 제외하고, 추후 PDF 업로드 필요 시 별도 추가한다. |
| `state.py` | `fine_type`, `notice_stage`, `law_code`, `fine_amount` 등 | 과태료 고지서 필드라 교통사고사실확인원과 맞지 않는다. | `accident_datetime`, `accident_location`, `accident_type`, `accident_description` 등으로 교체한다. |
| `verification.py` | `VALID_COMBINATIONS` | 과태료/범칙금 단계 조합 검증이라 도메인이 다르다. | 제목/사고 라벨/발급 구조 점수 검증으로 바꾼다. |
| `prompts.py` | 고지 단계, 법조, 벌점, 납부기한 추출 규칙 | 교통사고사실확인원에는 필요 없는 필드다. | 교통사고 접수번호, 발생일시, 사고내용, 피해내용 추출 규칙으로 바꾼다. |

---

## 30. 파일별 구현 상세와 예상 결과

아래는 실제 구현 시 파일별로 어떤 코드를 만들고, 실행 결과가 어떻게 나와야 하는지 정리한 것이다.

### 30-1. `state.py`

역할은 LangGraph 전체에서 공유할 상태 계약을 정의하는 것이다.  
`fine_notice_analysis/state.py`처럼 `TypedDict`를 쓰는 이유는 각 노드가 어떤 key를 읽고 쓰는지 문서와 코드에서 동시에 드러나기 때문이다.

예상 코드 구조:

```python
OCRStatus = Literal["success", "partial", "failed"]
DocumentType = Literal["traffic_accident_confirmation", "unknown"]


class TrafficAccidentConfirmationOCRState(TypedDict, total=False):
    document_image: Optional[str]
    document_mime_type: Optional[str]
    source_filename: Optional[str]
    ocr_status: Optional[OCRStatus]
    document_type: Optional[DocumentType]
    failure_reason: Optional[str]
    extracted_fields: dict
    missing_fields: list[str]
    agent_results: dict
```

예상 실행 결과:

```python
state = {
    "document_image": "...base64...",
    "document_mime_type": "image/png",
}
result = graph.invoke(state)

assert result["document_image"] is None
assert result["ocr_status"] in {"success", "partial", "failed"}
```

### 30-2. `graph.py`

역할은 노드 연결과 라우팅이다.  
`fine_notice_analysis/graph.py`의 fallback graph는 가져가는 것이 좋다. 이유는 개발 환경에 `langgraph`가 설치되지 않아도 최소 `.invoke()` 테스트를 할 수 있기 때문이다.

권장 흐름:

```text
ocr_node
  failed -> END
  success/partial -> document_verification_node

document_verification_node
  -> END
```

예상 코드 구조:

```python
def _route_after_ocr(state):
    if state.get("ocr_status") == "failed":
        return END
    return "document_verification_node"
```

예상 실행 결과:

```json
{
  "ocr_status": "success",
  "agent_results": {
    "traffic_accident_confirmation_ocr": {
      "status": "success",
      "next_actions": ["과실비율 분석 LangGraph 호출 가능"]
    }
  }
}
```

### 30-3. `agent.py`

역할은 OCR/Vision 호출 전후의 실무 처리를 담당하는 것이다.  
`fine_notice_analysis/agent.py`에서 가장 참고할 부분은 아래다.

- `_ALLOWED_MIME_TYPES`
- base64 디코딩
- `_build_image_blocks`
- `_call_gpt`
- JSON 파싱 실패 처리
- 처리 후 `document_image`를 `None`으로 제거
- 실패 시 `make_envelope`로 즉시 반환

교통사고사실확인원 OCR에서는 MIME을 아래처럼 제한한다.

```python
_ALLOWED_MIME_TYPES = {"image/jpeg", "image/png"}
```

그 이유는 현재 테스트 폴더에 `.jpg`, `.png`가 있고, 사용자가 둘 다 받아야 한다고 명시했기 때문이다. PDF나 webp까지 열면 테스트 범위가 넓어지고, 실패 원인도 늘어난다.

예상 실패 결과:

```json
{
  "ocr_status": "failed",
  "failure_reason": "unsupported_file_type",
  "document_image": null,
  "agent_results": {
    "traffic_accident_confirmation_ocr": {
      "status": "failed",
      "next_actions": ["교통사고사실확인원 1page jpg/png 재업로드 요청"]
    }
  }
}
```

예상 성공/부분성공 결과:

```json
{
  "ocr_status": "partial",
  "document_type": "traffic_accident_confirmation",
  "document_image": null,
  "extracted_fields": {
    "accident_datetime": "2026-06-25 14:30",
    "accident_location": "서울시 ○○구 ○○로",
    "accident_type": {
      "value": "차대차",
      "raw_text": "차대차"
    },
    "accident_description": null
  },
  "missing_fields": ["accident_description"]
}
```

### 30-4. `prompts.py`

역할은 OCR 모델이 반환해야 할 JSON 형태를 강제하는 것이다.  
`fine_notice_analysis/prompts.py`처럼 “JSON만 반환”을 강하게 써야 한다. 이유는 `agent.py`가 `json.loads`를 기본으로 파싱하기 때문이다.

프롬프트에 반드시 들어갈 근거:

- `null` 규칙이 없으면 모델이 추측값을 채울 수 있다.
- 개인정보 제외 규칙이 없으면 주민등록번호/차량번호 등이 그대로 반환될 수 있다.
- 2page 분석 제외 규칙이 없으면 모델이 약도나 도로 구조를 과도하게 해석할 수 있다.

예상 모델 반환:

```json
{
  "document_name": "교통사고사실확인원",
  "is_target_document": true,
  "receipt_number": "2026-000000",
  "accident_datetime": "2026-06-25 14:30",
  "accident_location": "서울시 ○○구 ○○로",
  "accident_type_raw": "차대차",
  "accident_type_value": "차대차",
  "accident_cause": "안전운전의무 위반",
  "damage_raw_text": "부상 1명, 물피 있음",
  "death_count": 0,
  "injury_count": 1,
  "property_damage_amount": null,
  "accident_description": "교차로에서 직진 차량과 좌회전 차량이 충돌한 사고",
  "usage": "보험회사 제출용",
  "detected_labels": ["발생일시", "발생장소", "사고유형", "사고내용"],
  "issuer_labels": ["교통사고 접수번호", "발급번호", "경찰서"],
  "quality_warnings": []
}
```

### 30-5. `evaluator.py`

역할은 추출 결과를 보고 `success/partial`을 판정하는 것이다.  
`fine_notice_analysis/evaluator.py`의 `CRITICAL_FIELDS`, `IMPORTANT_FIELDS`, `evaluate_ocr` 구조를 거의 그대로 가져가되 필드만 바꾼다.

권장 기준:

```python
CRITICAL_FIELDS = [
    "accident_datetime",
    "accident_location",
    "accident_type.value",
    "accident_description",
]

IMPORTANT_FIELDS = [
    "receipt_number",
    "issue_number",
    "police_station",
    "accident_cause",
    "damage.raw_text",
    "usage",
]
```

이렇게 나누는 이유:

- `accident_description`이 없으면 RAG 검색문과 사고 쟁점 태깅이 약해진다.
- `accident_location`이 없으면 교차로/도로/주차장 같은 맥락 판단이 어렵다.
- `receipt_number`, `issue_number`는 문서 식별에는 중요하지만 과실비율 분석 자체에는 직접 영향이 작다.

예상 실행 결과:

```python
fields = {
    "accident_datetime": "2026-06-25 14:30",
    "accident_location": "서울시 ○○구 ○○로",
    "accident_type": {"value": "차대차"},
    "accident_description": None,
}

status, missing = evaluate_ocr(fields)

assert status == "partial"
assert "accident_description" in missing
```

### 30-6. `verification.py`

역할은 OCR 결과가 정말 교통사고사실확인원인지, 그리고 값 형식이 후속 Agent가 쓰기 좋은지 검증하는 것이다.  
`fine_notice_analysis/verification.py`처럼 모든 오류를 `format_errors`에 모으고, 오류가 있으면 `partial`로 낮추는 구조가 좋다.

검증 항목:

- `verification_score`가 2점 이상인지
- 제목 없이 라벨만 맞은 경우 `partial`로 낮출지
- `accident_type.value`가 허용 enum인지
- `death_count`, `injury_count`, `property_damage_amount`가 숫자 또는 null인지
- `accident_datetime`이 너무 이상한 문자열은 아닌지

권장 사고유형 enum:

```python
ACCIDENT_TYPE_VALUES = {
    "차대차",
    "차대사람",
    "차량단독",
    "기타",
    "unknown",
}
```

예상 실행 결과:

```json
{
  "ocr_status": "partial",
  "document_check": {
    "is_target_document": true,
    "verification_score": 2,
    "verification_criteria": {
      "title_matched": false,
      "accident_labels_matched_count": 5,
      "issuer_structure_matched_count": 2
    }
  },
  "limitations": [
    "문서 제목이 명확히 인식되지 않아 확인이 필요합니다."
  ]
}
```

### 30-7. `masking.py`

역할은 OCR raw 응답 또는 필드 값에 개인정보가 섞였을 때 마지막 방어선을 제공하는 것이다.  
`fine_notice_analysis/masking.py`는 차량번호와 주민등록번호 패턴 중심이라 참고하되, 교통사고사실확인원에서는 아래 패턴을 더 고려한다.

권장 마스킹 대상:

```text
주민등록번호: 000000-0000000
운전면허번호: 00-00-000000-00 또는 지역명 포함 면허번호
전화번호: 010-0000-0000
차량번호: 12가3456, 123가4567
성명: 모델 추출 필드에서 제외하는 것이 우선
주소: 전체 반환하지 않는 것이 우선
```

이렇게 하는 이유는 과실비율 Agent가 이름, 주민번호, 면허번호를 전혀 필요로 하지 않기 때문이다.  
필요 없는 개인정보는 마스킹보다 “추출하지 않음”이 더 안전하다.

예상 실행 결과:

```python
mask_personal_info("홍길동 900101-1234567 12가3456")
# "홍길동 ●●●●●●-●●●●●●● 12가●●●●"
```

### 30-8. `utils.py`

역할은 Supervisor에 전달할 표준 envelope를 만드는 것이다.  
`fine_notice_analysis/utils.py`의 `make_envelope`, `update_agent_results`는 거의 같은 구조로 가져가면 된다.

바꿀 부분:

```python
"node_name": "교통사고사실확인원 OCR 노드"
"node_code": "traffic_accident_confirmation_ocr"
results["traffic_accident_confirmation_ocr"] = envelope
```

예상 실행 결과:

```json
{
  "agent_results": {
    "traffic_accident_confirmation_ocr": {
      "node_name": "교통사고사실확인원 OCR 노드",
      "node_code": "traffic_accident_confirmation_ocr",
      "status": "success",
      "structured_result": {
        "extracted_fields": {
          "accident_type": {
            "value": "차대차"
          }
        }
      },
      "missing_fields": [],
      "next_actions": ["과실비율 분석 LangGraph 호출 가능"],
      "limitations": ["2page 사고현장약도는 MVP 단계에서 분석하지 않았습니다."]
    }
  }
}
```

---

## 31. 코드 재사용 우선순위

구현할 때는 아래 순서로 가져가는 것이 가장 안전하다.

| 우선순위 | 가져올 대상 | 이유 |
|---:|---|---|
| 1 | `utils.py` envelope 패턴 | Supervisor 연동 규격을 먼저 고정해야 후속 노드가 흔들리지 않는다. |
| 2 | `state.py` TypedDict 패턴 | State key를 먼저 고정해야 `agent.py`, `verification.py`, `graph.py`가 같은 계약을 공유한다. |
| 3 | `graph.py` fallback graph 패턴 | LangGraph 설치 여부와 상관없이 기본 invoke 테스트가 가능하다. |
| 4 | `agent.py` base64/MIME/JSON 파싱 패턴 | 이미지 OCR Agent의 실패 처리를 안정화한다. |
| 5 | `prompts.py` JSON only 프롬프트 패턴 | OCR 응답 파싱 실패를 줄인다. |
| 6 | `evaluator.py` critical/important 판정 패턴 | success/partial 기준을 코드로 고정한다. |
| 7 | `verification.py` format_errors 수집 패턴 | 검증 오류를 한 번에 Supervisor에 전달한다. |
| 8 | `masking.py` regex 마스킹 패턴 | 개인정보가 결과에 섞이는 것을 마지막으로 방어한다. |

반대로 가장 먼저 만들면 안 되는 것은 OCR 프롬프트만 단독으로 만드는 방식이다.  
프롬프트가 먼저 만들어져도 State, envelope, evaluator 기준이 없으면 모델 응답이 어디에 들어가야 하는지 불명확해지고, 나중에 필드명이 계속 바뀐다.

---

## 32. 최소 구현 완료 기준

이 OCR LangGraph의 MVP 구현은 아래 조건을 만족하면 완료로 본다.

1. `image/jpeg`, `image/png` 입력을 모두 받는다.
2. base64가 깨졌거나 MIME이 틀리면 `failed` envelope를 반환한다.
3. 정상 이미지 처리 후 `document_image`는 결과에서 `None`이 된다.
4. `agent_results["traffic_accident_confirmation_ocr"]`가 항상 생성된다.
5. 교통사고사실확인원 문서 점수 `verification_score`가 생성된다.
6. 사고 핵심 필드 누락 시 `partial`과 `missing_fields`가 생성된다.
7. 개인정보 필드는 반환하지 않거나 마스킹된다.
8. 2page 분석은 하지 않고 `scene_diagram.analysis_status`에 `not_provided` 또는 `deferred`만 기록된다.
9. `raw/1page`의 jpg 샘플 1개와 png 샘플 1개가 최소 스모크 테스트를 통과한다.

예상 최종 스모크 테스트 출력 예:

```text
case: 15-07-18-광주광역시.jpg
mime: image/jpeg
status: success 또는 partial
document_type: traffic_accident_confirmation
missing_fields: [] 또는 일부 필드
document_image_removed: true
agent_result_exists: true

case: 14-07-00-경기도남양주.png
mime: image/png
status: success 또는 partial
document_type: traffic_accident_confirmation
missing_fields: [] 또는 일부 필드
document_image_removed: true
agent_result_exists: true
```
