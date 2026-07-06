# -*- coding: utf-8 -*-
"""PDF 추출 텍스트를 전처리하는 함수 모음입니다."""

import re
import unicodedata


def clean_pdf_text(text: str) -> str:
    """PDF 추출 텍스트의 기본 노이즈를 정리합니다."""

    # None이 들어와도 빈 문자열로 처리합니다.
    text = remove_control_chars(text or "")

    # 전각 문자와 호환 문자를 일반 형태로 정규화합니다.
    text = unicodedata.normalize("NFKC", text)

    # 비슷한 특수기호를 통일합니다.
    text = normalize_symbols(text)

    # 반복 공백과 빈 줄을 정리합니다.
    text = normalize_spaces(text)

    # 페이지 번호와 반복 헤더 같은 노이즈 줄을 제거합니다.
    text = remove_noise_lines(text)

    # 세로로 깨진 표 라벨을 복원합니다.
    text = repair_vertical_labels(text)

    # 세로 라벨 글자가 수정요소 줄 앞에 끼어든 경우 제거합니다.
    text = remove_residual_vertical_label_prefixes(text)

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
        "內": "내",
        "後": "후",
        "前": "전",
    }

    # 치환 목록을 순서대로 적용합니다.
    for src, dst in pairs.items():
        text = text.replace(src, dst)

    # 정규화된 텍스트를 반환합니다.
    return text


def remove_control_chars(text: str) -> str:
    """줄바꿈/탭을 제외한 제어문자를 제거합니다."""

    return "".join(ch for ch in text if ch in "\n\t" or not unicodedata.category(ch).startswith("C"))


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
    """페이지 번호, 반복 header/footer, 의미 없는 줄을 제거합니다."""

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

        # 숫자만 있는 줄은 페이지 번호일 가능성이 높아 제거합니다.
        if re.fullmatch(r"\d{1,3}", line):
            continue

        # 점선 목차를 제거합니다.
        if re.fullmatch(r"[.·\-\s]{5,}", line):
            continue

        # 반복 헤더 줄은 제거합니다.
        if line.startswith("자동차사고 과실비율 인정기준 │"):
            continue

        # 장 표지에서 깨진 단독 단어는 rule 본문에서 노이즈인 경우가 많습니다.
        if line in {"제1장.", "제2장.", "제3장.", "자동차와", "보행자의", "자동차(이륜차", "포함)의", "자전거(농기계", "사고"}:
            continue

        # 표의 세로 라벨을 나중에 복원하기 위해 보존할 수 있는 줄만 남깁니다.
        kept_lines.append(line)

    # 줄을 다시 합쳐 반환합니다.
    return "\n".join(kept_lines)


def repair_vertical_labels(text: str) -> str:
    """세로로 깨진 주요 라벨을 복원합니다."""

    # 과/실/비/율/조/정/예/시가 줄 단위로 깨진 경우입니다.
    text = re.sub(r"과\s*\n\s*실\s*\n\s*비\s*\n\s*율\s*\n\s*조\s*\n\s*정\s*\n\s*예\s*\n\s*시", "과실비율 조정 예시", text)

    # 기본 과실비율이 줄바꿈으로 깨진 경우입니다.
    text = re.sub(r"기본\s*\n\s*과실비율", "기본 과실비율", text)

    # 사고 상황이 줄바꿈으로 깨진 경우입니다.
    text = re.sub(r"사고\s*\n\s*상황", "사고 상황", text)

    # 관련 법규가 줄바꿈으로 깨진 경우입니다.
    text = re.sub(r"관련\s*\n\s*법규", "관련 법규", text)

    # 참고 판례가 줄바꿈으로 깨진 경우입니다.
    text = re.sub(r"참고\s*\n\s*판례", "참고 판례", text)

    # 활용시 참고 사항이 줄바꿈으로 깨진 경우입니다.
    text = re.sub(r"활용시\s*\n\s*참고\s*\n\s*사항", "활용시 참고 사항", text)

    # 복원된 텍스트를 반환합니다.
    return text



def remove_residual_vertical_label_prefixes(text: str) -> str:
    """세로 라벨 글자가 내용 줄 앞에 붙은 흔적을 제거합니다."""

    text = re.sub(r"(?m)^\s*[과실비율조정예시]\s+(?=(A|B|차|보)\s+)", "", text)
    text = re.sub(r"(?m)^\s*[과실비율조정예시]\s*$", "", text)
    return text

def repair_ratio_expressions(text: str) -> str:
    """A0 B100 같은 비율 표현을 A 0 : B 100으로 정규화합니다."""

    # A0 B100 형태를 A 0 : B 100 형태로 바꿉니다.
    text = re.sub(r"\bA\s*(\d{1,3})\s*B\s*(\d{1,3})\b", r"A \1 : B \2", text)

    # A 0 : B 100 형태의 공백을 통일합니다.
    text = re.sub(r"\bA\s*(\d{1,3})\s*:\s*B\s*(\d{1,3})\b", r"A \1 : B \2", text)

    # 보행자 기본과실비율처럼 붙은 표현을 분리합니다.
    text = text.replace("기본과실비율", "기본 과실비율")

    # 정규화된 텍스트를 반환합니다.
    return text


def structure_rule_text(text: str) -> str:
    """파싱이 잘 되도록 rule 텍스트를 정돈합니다."""

    # (A), (B), (보), (차) 줄이 붙어 있으면 새 줄로 분리합니다.
    text = re.sub(r"(?<!\n)\((A|B|보|차)\)", r"\n(\1)", text)

    # 기본 과실비율 라벨을 통일합니다.
    text = text.replace("기본과실비율", "기본 과실비율")

    # 과실비율 표현을 다시 정리합니다.
    text = repair_ratio_expressions(text)

    # 공백을 정리합니다.
    text = normalize_spaces(text)

    # 구조화된 텍스트를 반환합니다.
    return text
