"""법적 의미를 바꾸지 않는 텍스트 정리와 판결문 구역 분리 모듈."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any


BREAK_TAG_RE = re.compile(r"(?i)<\s*(br|/p|/div|/li|/tr)\s*/?\s*>")
HTML_TAG_RE = re.compile(r"<[^>]*>")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
INLINE_SPACE_RE = re.compile(r"[ \t\u00a0]+")
MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
TARGET_HEADING_RE = re.compile(
    r"【\s*(?P<bracket>주\s*문|이\s*유)\s*】"
    r"|^\s*\[\s*(?P<square>주\s*문|이\s*유)\s*\]",
    re.MULTILINE,
)
ANY_HEADING_RE = re.compile(
    r"【\s*[가-힣][가-힣\s,·]{0,30}\s*】"
    r"|^\s*\[\s*[가-힣][가-힣\s,·]{0,30}\s*\]",
    re.MULTILINE,
)


def clean_text(raw_text: Any, preserve_newlines: bool = False) -> str:
    """HTML·제어문자를 제거하되 문단 보존 여부를 선택할 수 있습니다."""

    if raw_text is None:
        return ""
    text = html.unescape(str(raw_text))
    text = BREAK_TAG_RE.sub("\n", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = CONTROL_RE.sub(" ", text)
    text = INLINE_SPACE_RE.sub(" ", text)
    if preserve_newlines:
        lines = [line.strip() for line in text.split("\n")]
        text = "\n".join(lines)
        return MULTI_NEWLINE_RE.sub("\n\n", text).strip()
    return re.sub(r"\s+", " ", text).strip()


def _heading_name(match: re.Match[str]) -> str:
    value = match.group("bracket") or match.group("square") or ""
    return value.replace(" ", "")


def _content_span(
    body: str,
    start: int,
    end: int,
) -> tuple[str, int, int]:
    raw = body[start:end]
    left_trim = len(raw) - len(raw.lstrip())
    content = raw.strip()
    content_start = start + left_trim
    return content, content_start, content_start + len(content)


@dataclass(frozen=True)
class BodySections:
    """정리된 판례 본문과 본문 기준 구역 offset."""

    clean_body_text: str
    preamble_text: str
    order_text: str
    reason_text: str
    unlabeled_body_text: str
    section_offsets: dict[str, dict[str, int]]


def split_body_sections(raw_body: Any) -> BodySections:
    """주문·이유와 나머지 미분류 본문을 섞지 않고 보존합니다."""

    body = clean_text(raw_body, preserve_newlines=True)
    if not body:
        return BodySections("", "", "", "", "", {})

    target_matches = list(TARGET_HEADING_RE.finditer(body))
    all_matches = list(ANY_HEADING_RE.finditer(body))
    order_match = next(
        (match for match in target_matches if _heading_name(match) == "주문"),
        None,
    )
    reason_match = next(
        (match for match in target_matches if _heading_name(match) == "이유"),
        None,
    )

    def next_heading_start(match: re.Match[str]) -> int | None:
        return next(
            (
                candidate.start()
                for candidate in all_matches
                if candidate.start() > match.start()
            ),
            None,
        )

    first_target = order_match or reason_match
    if order_match and reason_match:
        first_target = min((order_match, reason_match), key=lambda m: m.start())
    if first_target:
        preamble, preamble_start, preamble_end = _content_span(
            body, 0, first_target.start()
        )
    else:
        preamble, preamble_start, preamble_end = "", -1, -1

    order = ""
    order_start = -1
    order_end = -1
    reason = ""
    reason_start = -1
    reason_end = -1
    unlabeled = ""
    unlabeled_start = -1
    unlabeled_end = -1

    if order_match:
        content_start = order_match.end()
        next_heading = next_heading_start(order_match)
        content_end = next_heading if next_heading is not None else len(body)
        raw_order = body[content_start:content_end]

        # 주문 뒤에 이유/다른 헤더가 없으면 첫 문단만 주문으로 판단하고
        # 나머지를 미분류 본문으로 보존합니다.
        order_left_trim = len(raw_order) - len(raw_order.lstrip())
        trimmed_order = raw_order.lstrip()
        if next_heading is None and (
            "\n\n" in trimmed_order or "\n" in trimmed_order
        ):
            separator = "\n\n" if "\n\n" in trimmed_order else "\n"
            first_paragraph, remainder = trimmed_order.split(separator, 1)
            first_start = content_start + order_left_trim
            order, order_start, order_end = _content_span(
                body,
                first_start,
                first_start + len(first_paragraph),
            )
            remainder_start = (
                first_start + len(first_paragraph) + len(separator)
            )
            unlabeled, unlabeled_start, unlabeled_end = _content_span(
                body,
                remainder_start,
                len(body),
            )
        else:
            order, order_start, order_end = _content_span(
                body,
                content_start,
                content_end,
            )

        if reason_match and reason_match.start() > order_match.start():
            # next_heading이 이유인 일반적인 경우 위 주문 범위가 이미 정확합니다.
            pass
        elif next_heading is not None and reason_match is None:
            unlabeled, unlabeled_start, unlabeled_end = _content_span(
                body,
                next_heading,
                len(body),
            )

    if reason_match:
        content_start = reason_match.end()
        next_heading = next_heading_start(reason_match)
        content_end = next_heading if next_heading is not None else len(body)
        reason, reason_start, reason_end = _content_span(
            body,
            content_start,
            content_end,
        )
        if next_heading is not None:
            unlabeled, unlabeled_start, unlabeled_end = _content_span(
                body,
                next_heading,
                len(body),
            )
    elif not order_match:
        unlabeled = body
        unlabeled_start = 0
        unlabeled_end = len(body)

    offsets: dict[str, dict[str, int]] = {}
    if preamble:
        offsets["BODY_PREAMBLE"] = {
            "start": preamble_start,
            "end": preamble_end,
        }
    if order:
        offsets["ORDER"] = {"start": order_start, "end": order_end}
    if reason:
        offsets["REASON"] = {"start": reason_start, "end": reason_end}
    if unlabeled:
        offsets["UNLABELED_BODY"] = {
            "start": unlabeled_start,
            "end": unlabeled_end,
        }

    return BodySections(
        clean_body_text=body,
        preamble_text=preamble,
        order_text=order,
        reason_text=reason,
        unlabeled_body_text=unlabeled,
        section_offsets=offsets,
    )


@dataclass(frozen=True)
class PreprocessedTextParts:
    """전처리 텍스트와 재구성 가능한 구역 위치."""

    holding_text: str
    summary_text: str
    body_preamble_text: str
    order_text: str
    reason_text: str
    unlabeled_body_text: str
    clean_body_text: str
    body_section_offsets: dict[str, dict[str, int]]
    full_text: str
    full_text_section_offsets: dict[str, dict[str, int]]


def _build_full_text(
    sections: list[tuple[str, str]],
) -> tuple[str, dict[str, dict[str, int]]]:
    parts: list[str] = []
    offsets: dict[str, dict[str, int]] = {}
    cursor = 0
    for name, text in sections:
        if not text:
            continue
        if parts:
            separator = "\n\n"
            parts.append(separator)
            cursor += len(separator)
        header = f"[{name}]\n"
        parts.append(header)
        cursor += len(header)
        start = cursor
        parts.append(text)
        cursor += len(text)
        offsets[name] = {"start": start, "end": cursor}
    return "".join(parts), offsets


def split_sections(record: dict[str, Any]) -> PreprocessedTextParts:
    """API 개별 필드와 `판례내용` 내부 구역을 중복 없이 분리합니다."""

    holding = clean_text(record.get("판시사항", ""), preserve_newlines=True)
    summary = clean_text(record.get("판결요지", ""), preserve_newlines=True)
    body = split_body_sections(record.get("판례내용", ""))

    explicit_order = clean_text(record.get("주문", ""), preserve_newlines=True)
    explicit_reason = clean_text(record.get("이유", ""), preserve_newlines=True)
    order = explicit_order or body.order_text
    reason = explicit_reason or body.reason_text
    unlabeled = body.unlabeled_body_text

    full_text, full_offsets = _build_full_text(
        [
            ("판시사항", holding),
            ("판결요지", summary),
            ("본문머리", body.preamble_text),
            ("주문", order),
            ("이유", reason),
            ("미분류본문", unlabeled),
        ]
    )

    return PreprocessedTextParts(
        holding_text=holding,
        summary_text=summary,
        body_preamble_text=body.preamble_text,
        order_text=order,
        reason_text=reason,
        unlabeled_body_text=unlabeled,
        clean_body_text=body.clean_body_text,
        body_section_offsets=body.section_offsets,
        full_text=full_text,
        full_text_section_offsets=full_offsets,
    )
