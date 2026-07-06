# -*- coding: utf-8 -*-
"""PDF 추출 텍스트를 전처리하는 함수 모음입니다."""

import re
import unicodedata


def clean_pdf_text(text: str) -> str:
    """PDF 추출 텍스트의 기본 노이즈를 정리합니다."""

    # 전각 문자와 호환 문자를 일반 형태로 정규화합니다.
    text = unicodedata.normalize("NFKC", text or "")

    # 비슷한 특수기호를 통일합니다.
    text = normalize_symbols(text)

    # 반복 공백과 빈 줄을 정리합니다.
    text = normalize_spaces(text)

    # 페이지 번호, 목차 점선 같은 노이즈 줄을 제거합니다.
    text = remove_noise_lines(text)

    # 줄바꿈으로 깨진 주요 라벨을 복원합니다.
    text = repair_broken_labels(text)

    # A 50 B 50 같은 과실비율 표현을 정규화합니다.
    text = repair_ratio_expressions(text)

    # 우->좌 같은 방향 표현을 우→좌로 통일합니다.
    text = normalize_direction_arrows(text)

    # 마지막으로 공백을 다시 정리합니다.
    text = normalize_spaces(text)

    # 앞뒤 공백을 제거해 반환합니다.
    return text.strip()


def normalize_symbols(text: str) -> str:
    """전각 기호와 비슷한 특수문자를 통일합니다."""

    # 원문 의미를 잃지 않는 범위에서만 치환합니다.
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

        # - 17 - 같은 페이지 번호를 제거합니다.
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

    # 문서에서 반복되는 라벨 복원 패턴입니다.
    patterns = {
        r"기본\s*\n\s*과실": "기본과실",
        r"사고\s*\n\s*상황": "사고상황",
        r"수정\s*\n\s*요소": "수정요소",
        r"도표\s*\n\s*해설": "도표해설",
        r"관련\s*\n\s*법규": "관련법규",
        r"참고\s*\n\s*판례": "참고판례",
    }

    # 패턴을 순서대로 적용합니다.
    for pattern, repl in patterns.items():
        text = re.sub(pattern, repl, text)

    # 복원된 텍스트를 반환합니다.
    return text


def repair_ratio_expressions(text: str) -> str:
    """A 50 B 50 같은 비율 표현을 A 50 : B 50으로 정규화합니다."""

    # A 50 B 50 형태를 A 50 : B 50 형태로 바꿉니다.
    text = re.sub(
        r"\bA\s*(\d{1,3}(?:\(\d{1,3}\))?)\s*B\s*(\d{1,3}(?:\(\d{1,3}\))?)\b",
        r"A \1 : B \2",
        text,
    )

    # A50:B30처럼 붙은 표현을 띄어 씁니다.
    text = re.sub(r"\bA(\d{1,3})\s*:\s*B(\d{1,3})\b", r"A \1 : B \2", text)

    # 이미 콜론이 있는 표현도 공백을 통일합니다.
    text = re.sub(r"\bA\s*(\d{1,3})\s*:\s*B\s*(\d{1,3})\b", r"A \1 : B \2", text)

    # 정규화된 텍스트를 반환합니다.
    return text


def normalize_direction_arrows(text: str) -> str:
    """우->좌, 좌->우 같은 방향 표현을 보존 가능한 화살표로 정규화합니다."""

    # 화살표 표현을 한 가지로 통일합니다.
    text = text.replace("우->좌", "우→좌")
    text = text.replace("좌->우", "좌→우")
    text = text.replace("우 → 좌", "우→좌")
    text = text.replace("좌 → 우", "좌→우")

    # 통일된 텍스트를 반환합니다.
    return text


def structure_rule_text(text: str) -> str:
    """파싱이 잘 되도록 사고상황과 당사자 줄을 정돈합니다."""

    # 사고상황과 자동차 A를 줄바꿈으로 분리합니다.
    text = re.sub(r"사고상황\s*자동차\s*A\s*:", "사고상황\n자동차 A :", text)

    # 자동차 B가 같은 줄에 붙어 있으면 새 줄로 보냅니다.
    text = re.sub(r"(?<!\n)자동차\s*B\s*:", "\n자동차 B :", text)

    # 이륜차 B도 같은 방식으로 분리합니다.
    text = re.sub(r"(?<!\n)이륜차\s*B\s*:", "\n이륜차 B :", text)

    # 과실비율 표현을 다시 정리합니다.
    text = repair_ratio_expressions(text)

    # 공백을 정리합니다.
    text = normalize_spaces(text)

    # 구조화된 텍스트를 반환합니다.
    return text
