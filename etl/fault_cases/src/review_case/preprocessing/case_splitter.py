from __future__ import annotations

import re

from ..models import PageText, ReviewCaseText


REVIEW_NO_RE = re.compile(r"심의번호\s*(\d{4}-\d{6})")


def _extract_layout_argument(pages: list[PageText], label: str) -> str | None:
    values = [getattr(page, label) for page in pages if getattr(page, label)]
    return "\n".join(values).strip() if values else None


def split_cases(pages: list[PageText]) -> list[ReviewCaseText]:
    markers: list[tuple[str, int, int]] = []
    for page_index, page in enumerate(pages):
        for match in REVIEW_NO_RE.finditer(page.clean_text):
            markers.append((match.group(1), page_index, match.start()))

    cases: list[ReviewCaseText] = []
    for marker_index, (review_no, page_index, start_offset) in enumerate(markers):
        next_page_index = markers[marker_index + 1][1] if marker_index + 1 < len(markers) else len(pages)
        selected = pages[page_index:next_page_index + 1 if next_page_index == page_index else next_page_index]
        if not selected:
            continue

        texts = []
        raw_texts = []
        for local_index, page in enumerate(selected):
            clean = page.clean_text
            raw = page.raw_text
            if local_index == 0:
                clean = clean[max(0, start_offset - 1500):]
                raw = raw[max(0, start_offset - 1500):]
            if marker_index + 1 < len(markers) and page_index + local_index == markers[marker_index + 1][1]:
                clean = clean[: markers[marker_index + 1][2]]
                raw = raw[: markers[marker_index + 1][2]]
            texts.append(clean)
            raw_texts.append(raw)

        first = selected[0]
        last = selected[-1]
        cases.append(
            ReviewCaseText(
                review_no=review_no,
                page_start=first.page_no,
                page_end=last.page_no,
                raw_text="\n".join(raw_texts).strip(),
                clean_text="\n".join(texts).strip(),
                extractor=first.extractor,
                pdf_page_start=first.page_no,
                pdf_page_end=last.page_no,
                book_page_start=first.book_page_no,
                book_page_end=last.book_page_no,
                layout_claimant_argument=_extract_layout_argument(selected, "layout_claimant_argument"),
                layout_respondent_argument=_extract_layout_argument(selected, "layout_respondent_argument"),
            )
        )
    return cases
