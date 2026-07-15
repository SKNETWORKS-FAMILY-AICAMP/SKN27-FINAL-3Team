# 과태료 이의신청서 생성 Agent 설계

## 1. 목표

사용자가 처분 정보(성명, 과태료 내역, 이의 사유 등)를 입력하면, 법적 필수 항목을 빠짐없이 채운 이의신청서를 자동 생성하는 Agent를 만든다. 산출물은 두 가지 형태를 지원한다.

- **정형 서식형**: 첨부된 PDF(`과태료 처분에 대한 이의신청서`, 강동구청 양식)처럼 표 구조가 정해진 문서
- **자유 양식형**: 지정 서식이 없는 기관에 제출할 때 쓰는 A4 텍스트형 문서 (신청인 정보 / 대상 처분 내역 / 신청 취지 / 신청 이유 / 첨부 서류 순서로 작성)

## 2. 입력 데이터 스키마

```python
from pydantic import BaseModel
from typing import Optional
from datetime import date

class Applicant(BaseModel):
    name: str                    # 성명
    resident_number: str         # 주민(사업자)등록번호
    address: str                 # 주소
    phone: str                   # 연락처

class Disposition(BaseModel):
    case_number: str             # 과태료 부과(납부고지서) 번호
    imposed_date: date           # 부과 일자 / 고지받은 일자
    amount: int                  # 과태료 금액
    reason: str                  # 위반 내용(고지서에 적힌 그대로)
    issuing_agency: str          # 부과 기관 (예: ㅇㅇ구청장, ㅇㅇ경찰서장)
    vehicle_number: Optional[str] = None  # 자동차번호 (자동차 관련 건일 때만)

class ObjectionRequest(BaseModel):
    applicant: Applicant
    disposition: Disposition
    grounds: str                 # 신청 이유 (부당성, 고의·과실 없음, 법정 감경 사유 등)
    attachments: list[str] = []  # 첨부 서류 목록
    form_type: str = "free"      # "free" | "official" (정형 서식 사용 여부)
```

## 3. Agent 파이프라인

```
[1] 입력 수집/검증
     └─ 필수 항목 누락 체크 (신청인정보, 처분내역, 신청취지, 신청이유)
[2] 신청 취지 문장 자동 조립
     └─ "{기관장}이 {부과일자} 신청인에 대하여 한 과태료 부과 처분에 불복하므로 이의를 신청합니다."
[3] 신청 이유 초안 생성 (LLM)
     └─ 사용자가 입력한 사실관계를 근거로 법률 문체로 다듬기
[4] 문서 렌더링
     └─ form_type에 따라 템플릿(docx/표) 또는 텍스트 양식 선택
[5] 최종 검증
     └─ 필수 항목 6종이 출력물에 모두 포함됐는지 재확인
```

### 3.1 필수 항목 체크리스트 (검증 단계에서 사용)

| 항목 | 필수 여부 | 소스 |
|---|---|---|
| 신청인 정보 (성명/주민번호/주소/연락처) | 필수 | `applicant` |
| 대상 처분 내역 (부과번호/일자/금액/위반내용) | 필수 | `disposition` |
| 신청 취지 (정형 문구) | 필수 | 자동 조립 |
| 신청 이유 (부당성/고의과실 없음/감경사유) | 필수 | `grounds` + LLM 보강 |
| 첨부 서류 목록 | 필수 | `attachments` |
| 수신처(귀하) + 날짜 + 서명란 | 필수 | 템플릿 고정 문구 |

## 4. 코드 구조 (Python 예시)

```
objection_agent/
├── models.py          # 위 pydantic 스키마
├── validator.py        # 필수 항목 검증
├── prompt_builder.py    # LLM 프롬프트 조립
├── generator.py         # Claude API 호출, 신청이유 문장 다듬기
├── renderer.py           # docx/텍스트 출력
├── templates/
│   ├── free_form.txt          # 자유 양식 템플릿
│   └── official_form.docx     # 표 기반 정형 서식 템플릿
└── main.py               # 파이프라인 오케스트레이션
```

### 4.1 validator.py

```python
def validate(req: ObjectionRequest) -> list[str]:
    errors = []
    if not req.applicant.name or not req.applicant.resident_number:
        errors.append("신청인 정보 누락")
    if not req.disposition.case_number or not req.disposition.amount:
        errors.append("처분 내역 누락")
    if not req.grounds:
        errors.append("신청 이유 누락")
    return errors
```

### 4.2 prompt_builder.py — 신청 이유 보강용 프롬프트

```python
def build_grounds_prompt(req: ObjectionRequest) -> str:
    return f"""아래 사실관계를 바탕으로 과태료 이의신청서의 '신청 이유' 항목을
법률 문서 문체로 3~5문장 작성하라. 과장하지 말고 사용자가 제공한 사실만 사용할 것.

[처분 사유] {req.disposition.reason}
[사용자 주장] {req.grounds}
[감경 사유 해당 여부] {"명시된 경우 포함, 없으면 생략"}
"""
```

### 4.3 renderer.py — 자유 양식 출력 예시

```python
FREE_FORM_TEMPLATE = """
이 의 신 청 서

1. 신청인 정보
   성명: {applicant_name}   주민등록번호: {resident_number}
   주소: {address}          연락처: {phone}

2. 대상 처분 내역
   과태료 부과 번호: {case_number}
   부과 일자: {imposed_date}
   과태료 금액: {amount}원
   위반 내용: {reason}

3. 신청 취지
   {gist}

4. 신청 이유
   {grounds_final}

5. 첨부 서류
{attachments_list}

{year}년 {month}월 {day}일
신청인: {applicant_name} (서명 또는 인)

{agency} 귀하
"""
```

정형 서식(official)은 `python-docx`로 첨부 PDF와 동일한 표(신청인/과태료 처분내역/이의신청내용 3단 표)를 채우는 방식으로 구현한다. `docx` 스킬을 사용해 템플릿의 표 셀에 값만 치환하면 첨부 PDF와 동일한 결과물을 얻을 수 있다.

## 5. 확장 포인트

- 감경 사유(기초생활수급자, 미성년자 등) 자동 판단: 사용자 답변에서 키워드 추출 → 법정 감경 조항 자동 인용
- 기관별 정형 서식이 다르므로, `official_form.docx` 템플릿을 기관 코드별로 여러 개 관리
- 최종 출력 전 LLM에게 "6개 필수 항목이 모두 포함됐는가"를 재검증시키는 self-check 단계 추가 권장

## 6. 참고

- 자유 양식 필수 항목 출처: [대련 행정사무소](https://www.daeryunlaw-administration.com/lawInfo_new/11574)
- 정형 서식 예시: 첨부된 강동구청 「과태료 처분에 대한 이의신청서」 PDF
