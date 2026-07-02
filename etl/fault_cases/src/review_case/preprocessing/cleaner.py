from __future__ import annotations

import re


HEADER_FOOTER_PATTERNS = [
    re.compile(r"^\s*자동차사고\s+과실비율.*$"),
]


def normalize_symbols(text: str) -> str:
    replacements = {
        "\u00a0": " ",
        "：": ":",
        "＝": "=",
        "ㆍ": " ",
        "·": " ",
        "–": "-",
        "—": "-",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def repair_broken_labels(text: str) -> str:
    labels = [
        "심의번호",
        "결정비율",
        "사고내용",
        "참고 인정기준",
        "주장 내용",
        "입증 자료",
        "입증자료",
        "주요 쟁점",
        "주요쟁점",
        "결정 근거",
        "결정근거",
        "결정 이유",
        "결정이유",
        "참고기준",
    ]
    for label in labels:
        compact_label = label.replace(" ", "")
        spaced = r"\s*".join(map(re.escape, compact_label))
        text = re.sub(spaced, label, text)
    return text


def remove_header_footer_lines(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if any(pattern.match(stripped) for pattern in HEADER_FOOTER_PATTERNS):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def compact_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_text(text: str) -> str:
    text = normalize_symbols(text or "")
    text = repair_broken_labels(text)
    text = remove_header_footer_lines(text)
    return compact_text(text)
