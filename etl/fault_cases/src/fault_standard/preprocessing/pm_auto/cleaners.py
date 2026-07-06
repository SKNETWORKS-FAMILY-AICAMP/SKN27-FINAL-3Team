# -*- coding: utf-8 -*-
"""PDF 추출 텍스트를 전처리하는 함수 모음입니다."""

import re
import unicodedata


def clean_pdf_text(text: str) -> str:
    """PDF 추출 텍스트의 기본 노이즈를 정리합니다."""

    # None이 들어와도 빈 문자열로 처리합니다.
    text = text or ""

    # 전각 문자와 호환 문자를 일반 형태로 정규화합니다.
    text = unicodedata.normalize("NFKC", text)

    # 비슷한 특수기호를 통일합니다.
    text = normalize_symbols(text)

    # 반복 공백과 빈 줄을 정리합니다.
    text = normalize_spaces(text)

    # 페이지 번호와 목차 점선 같은 노이즈 줄을 제거합니다.
    text = remove_noise_lines(text)

    # 줄바꿈 때문에 깨진 주요 라벨을 복원합니다.
    text = repair_broken_labels(text)

    # PM 기준서에서 중요한 용어를 통일합니다.
    text = normalize_pm_terms(text)

    # 과실비율 표현을 정규화합니다.
    text = repair_ratio_expressions(text)

    # 마지막으로 공백을 다시 정리합니다.
    text = normalize_spaces(text)

    # 앞뒤 공백을 제거해 반환합니다.
    return text.strip()


def normalize_symbols(text: str) -> str:
    """전각 기호와 비슷한 특수문자를 통일합니다."""

    # 의미가 유지되는 치환만 적용합니다.
    pairs = {
        "：": ":",
        "％": "%",
        "＋": "+",
        "－": "-",
        "–": "-",
        "—": "-",
        "∼": "~",
        "～": "~",
        "ㆍ": "·",
        "對": "대",
    }

    # 치환 목록을 순서대로 적용합니다.
    for src, dst in pairs.items():
        text = text.replace(src, dst)

    # 정규화된 텍스트를 반환합니다.
    return text


def normalize_spaces(text: str) -> str:
    """반복 공백과 불필요한 빈 줄을 정리합니다."""

    # 윈도우 줄바꿈을 일반 줄바꿈으로 통일합니다.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 탭은 공백 하나로 바꿉니다.
    text = text.replace("\t", " ")

    # 같은 줄 안의 2칸 이상 공백을 1칸으로 줄입니다.
    text = re.sub(r"[ ]{2,}", " ", text)

    # 줄 앞뒤 공백을 줄입니다.
    text = re.sub(r"\n[ ]+", "\n", text)
    text = re.sub(r"[ ]+\n", "\n", text)

    # 빈 줄이 너무 많이 반복되면 2줄 이하로 줄입니다.
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 정리된 텍스트를 반환합니다.
    return text.strip()


def remove_noise_lines(text: str) -> str:
    """페이지 번호, 목차 점선, 의미 없는 줄을 제거합니다."""

    # 남길 줄을 저장합니다.
    kept_lines: list[str] = []

    # 줄 단위로 검사합니다.
    for raw_line in text.splitlines():
        # 줄 앞뒤 공백을 제거합니다.
        line = raw_line.strip()

        # 빈 줄은 문단 경계로 남깁니다.
        if not line:
            kept_lines.append("")
            continue

        # - 1 - 같은 페이지 번호를 제거합니다.
        if re.fullmatch(r"-\s*\d+\s*-", line):
            continue

        # 숫자만 있는 줄은 페이지 번호일 가능성이 높아 제거합니다.
        if re.fullmatch(r"\d{1,3}", line):
            continue

        # 점선이나 의미 없는 선을 제거합니다.
        if re.fullmatch(r"[.·\-\s]{5,}", line):
            continue

        # 나머지 줄은 보존합니다.
        kept_lines.append(line)

    # 줄을 다시 합쳐 반환합니다.
    return "\n".join(kept_lines)


def repair_broken_labels(text: str) -> str:
    """줄바꿈 때문에 깨진 주요 라벨을 복원합니다."""

    # 기본/과실 분리 표현을 복원합니다.
    text = re.sub(r"기본\s*\n\s*과실", "기본과실", text)

    # 사고/상황 분리 표현을 복원합니다.
    text = re.sub(r"사고\s*\n\s*상황", "사고상황", text)

    # 수정/요소 분리 표현을 복원합니다.
    text = re.sub(r"수정\s*\n\s*요소", "수정요소", text)

    # 도표/해설 분리 표현을 복원합니다.
    text = re.sub(r"도표\s*\n\s*해설", "도표해설", text)

    # 관련/법규 분리 표현을 복원합니다.
    text = re.sub(r"관련\s*\n\s*법규", "관련법규", text)

    # 참고/판례 분리 표현을 복원합니다.
    text = re.sub(r"참고\s*\n\s*판례", "참고판례", text)

    # 복원된 텍스트를 반환합니다.
    return text


def normalize_pm_terms(text: str) -> str:
    """PM 기준서에서 중요한 용어를 통일합니다."""

    # 개인형 이동장치를 개인형이동장치로 통일합니다.
    text = text.replace("개인형 이동장치", "개인형이동장치")

    # 전동 킥보드를 전동킥보드로 통일합니다.
    text = text.replace("전동 킥보드", "전동킥보드")

    # 자전거 도로를 자전거도로로 통일합니다.
    text = text.replace("자전거 도로", "자전거도로")

    # 자전거 횡단도를 자전거횡단도로 통일합니다.
    text = text.replace("자전거 횡단도", "자전거횡단도")

    # 차도가 아닌 장소 표현을 보존합니다.
    text = text.replace("차도가 아닌 장소", "차도가 아닌 장소")

    # 정규화된 텍스트를 반환합니다.
    return text


def repair_ratio_expressions(text: str) -> str:
    """A 50 B 50 같은 비율 표현을 A 50 : B 50으로 정규화합니다."""

    # A 50 B 50 형태를 A 50 : B 50 형태로 바꿉니다.
    text = re.sub(
        r"\bA\s*(\d{1,3}(?:\(\d{1,3}\))?)\s*B\s*(\d{1,3}(?:\(\d{1,3}\))?)\b",
        r"A \1 : B \2",
        text,
    )

    # 이미 콜론이 있는 표현도 공백을 통일합니다.
    text = re.sub(r"\bA\s*(\d{1,3})\s*:\s*B\s*(\d{1,3})\b", r"A \1 : B \2", text)

    # 정규화된 텍스트를 반환합니다.
    return text


def structure_rule_text(text: str) -> str:
    """파싱이 잘 되도록 도표 텍스트를 정돈합니다."""

    # PM A 줄이 붙어 있으면 새 줄로 분리합니다.
    text = re.sub(r"(?<!\n)PM\s*A\s*:", "\nPM A :", text)

    # PM B 줄이 붙어 있으면 새 줄로 분리합니다.
    text = re.sub(r"(?<!\n)PM\s*B\s*:", "\nPM B :", text)

    # 자동차 A 줄이 붙어 있으면 새 줄로 분리합니다.
    text = re.sub(r"(?<!\n)자동차\s*A\s*:", "\n자동차 A :", text)

    # 자동차 B 줄이 붙어 있으면 새 줄로 분리합니다.
    text = re.sub(r"(?<!\n)자동차\s*B\s*:", "\n자동차 B :", text)

    # 기본과실 라벨을 통일합니다.
    text = text.replace("기본 과실", "기본과실")

    # PM 용어를 다시 정규화합니다.
    text = normalize_pm_terms(text)

    # 과실비율 표현을 다시 정리합니다.
    text = repair_ratio_expressions(text)

    # 공백을 정리합니다.
    text = normalize_spaces(text)

    # 구조화된 텍스트를 반환합니다.
    return text
