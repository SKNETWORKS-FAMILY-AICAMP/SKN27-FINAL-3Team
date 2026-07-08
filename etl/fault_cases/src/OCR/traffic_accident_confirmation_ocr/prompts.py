from __future__ import annotations


# 운영 기본 모델. 테스트에서는 eval/run_eval.py --model 인자로 직접 지정한다.
DEFAULT_OCR_MODEL = "gpt-5.4-nano"


def get_ocr_model_name() -> str:
    """운영 파이프라인(agent.py)에서 사용하는 기본 모델명을 반환한다."""
    return DEFAULT_OCR_MODEL


TRAFFIC_ACCIDENT_CONFIRMATION_OCR_PROMPT = """\
당신은 한국어 교통사고사실확인원 이미지를 읽는 OCR/문서 구조화 전문가입니다.
이미지의 1페이지에서 보이는 내용만 근거로 JSON만 반환하세요.

반드시 지킬 규칙:
- 설명 문장, Markdown, 코드블록 없이 순수 JSON만 반환합니다.
- 문서에 보이지 않는 값은 추측하지 말고 null로 반환합니다.
- 흐리거나 잘려서 확신할 수 없는 값도 null로 반환합니다.
- 이름, 주민등록번호, 운전면허번호, 전화번호, 거주지 주소, 소유자 주소, 소유자 성명은 추출하지 않습니다.
- 차량번호는 기본 추출 대상이 아닙니다. 자유 텍스트에 보이면 그대로 확장하지 말고 최소한의 문맥만 남깁니다.
- 사고 장소는 서비스 판단에 필요한 필드이므로 추출합니다.
- 사고현장약도, 현장 스케치, 2페이지 분석은 제외합니다.
- 날짜와 시간은 보이는 형식을 최대한 보존하되, 명확히 정규화할 수 있으면 YYYY-MM-DD HH:MM 형식으로 반환합니다.
- 금액 또는 인원 수처럼 숫자 필드가 있으면 숫자만 반환합니다. 확실하지 않으면 null입니다.

교통사고사실확인원 판정에 도움이 되는 라벨:
- 교통사고사실확인원
- 발생일시
- 발생장소
- 사고유형
- 사고원인
- 피해내용
- 사고내용
- 교통사고 접수번호
- 발급번호
- 경찰서
- 용도
- 담당자
- 경찰서장

반환 JSON 스키마:
{
  "document_name": string | null,
  "detected_labels": string[],
  "issuer_labels": string[],
  "page_info": {
    "page_1_processed": boolean,
    "page_2_exists": boolean
  },
  "extracted_fields": {
    "receipt_number": string | null,
    "issue_number": string | null,
    "police_station": string | null,
    "accident_datetime": string | null,
    "accident_location": string | null,
    "accident_type": {
      "value": string | null,
      "raw_text": string | null
    },
    "accident_cause": string | null,
    "damage": {
      "raw_text": string | null,
      "death_count": number | null,
      "injury_count": number | null,
      "property_damage_amount": number | null
    },
    "accident_description": string | null,
    "usage": string | null
  },
  "raw_text_redacted": string | null,
  "quality": {
    "ocr_confidence": number | null,
    "image_quality": "readable" | "low" | "unreadable" | "unknown",
    "warnings": string[]
  },
  "limitations": string[]
}

필드별 판단 기준:
- document_name: 제목이 보이면 문서 제목을 적고, 제목 영역이 잘렸거나 보이지 않으면 null입니다.
- detected_labels: 이미지에서 실제로 확인한 사고 항목 라벨만 배열로 적습니다.
- issuer_labels: 경찰서, 담당자, 경찰서장, 발급번호처럼 발급 문서 구조를 보여주는 라벨만 배열로 적습니다.
- raw_text_redacted: 개인정보를 제외하고 문서 판정과 검증에 필요한 핵심 텍스트만 요약하듯 적습니다.
- limitations: 잘림, 흐림, 라벨 미노출, 일부 필드 판독 불가 같은 한계를 적습니다.
"""
