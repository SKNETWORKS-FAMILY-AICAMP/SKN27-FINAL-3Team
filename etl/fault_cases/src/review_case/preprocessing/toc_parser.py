from __future__ import annotations

import re
from collections import defaultdict

from ..models import PageText, ReviewCaseDocument, ReviewCaseTocCaseLink, ReviewCaseTocItem


TOC_LINE_RE = re.compile(
    r"(?P<chart>\d{3})(?:-(?P<sub>\d+))?\s+(?P<title>.+?)\s+(?P<page>\d{1,4})$"
)
TOC_DOTTED_LINE_RE = re.compile(r"(?P<title>.+?)\.{3,}\s*(?P<page>\d{3})$")
FAULT_WORDS = ("기본과실", "수정과실", "준용")


def _chart_key(chart: str | None, sub: str | None) -> str | None:
    if not chart:
        return None
    return f"{chart}-{sub}" if sub else chart


def parse_toc_items(pages: list[PageText], source_type: str, max_pages: int = 12) -> list[ReviewCaseTocItem]:
    items: list[ReviewCaseTocItem] = []
    chapter: str | None = None
    large: str | None = None
    middle: str | None = None
    for page in pages[:max_pages]:
        for line in page.clean_text.splitlines():
            line = re.sub(r"\s+", " ", line.strip())
            if not line:
                continue
            if re.match(r"제\d+장", line):
                chapter = line
                continue
            if line.startswith(("1.", "2.", "3.", "4.", "5.")):
                large = line
                continue
            if line.startswith(("가.", "나.", "다.", "라.", "마.", "바.", "사.")):
                middle = line
                continue
            match = TOC_LINE_RE.search(line)
            dotted_match = TOC_DOTTED_LINE_RE.search(line)
            if not match and not dotted_match:
                continue
            if match:
                title = match.group("title").strip(" .")
                chart_no = match.group("chart")
                sub_no = match.group("sub")
                book_page = int(match.group("page"))
            else:
                title = dotted_match.group("title").strip(" .") if dotted_match else ""
                chart_no = None
                sub_no = None
                book_page = int(dotted_match.group("page")) if dotted_match else None
            if not any(word in title for word in FAULT_WORDS):
                continue
            key = _chart_key(chart_no, sub_no)
            fault_type = next((word for word in FAULT_WORDS if word in title), None)
            items.append(
                ReviewCaseTocItem(
                    toc_item_id=f"toc_{len(items) + 1:04d}",
                    chapter_title=chapter,
                    large_category=large,
                    middle_category=middle,
                    chart_no=chart_no,
                    chart_sub_no=sub_no,
                    chart_key=key,
                    case_title=title,
                    case_condition=None,
                    fault_type=fault_type,
                    book_page_no=book_page,
                    toc_pdf_page_no=page.page_no,
                    source_type=source_type,
                    parse_status="valid",
                    quality_flags=[],
                )
            )
    return items


def link_toc_items(documents: list[ReviewCaseDocument], toc_items: list[ReviewCaseTocItem]) -> list[ReviewCaseTocCaseLink]:
    by_chart: dict[str, list[ReviewCaseTocItem]] = defaultdict(list)
    by_page: dict[int, list[ReviewCaseTocItem]] = defaultdict(list)
    for item in toc_items:
        if item.chart_key:
            by_chart[item.chart_key].append(item)
        if item.book_page_no is not None:
            by_page[item.book_page_no].append(item)

    links: list[ReviewCaseTocCaseLink] = []
    for doc in documents:
        item: ReviewCaseTocItem | None = None
        reason = "not_matched"
        if doc.reference_chart_key and by_chart.get(doc.reference_chart_key):
            item = by_chart[doc.reference_chart_key][0]
            reason = "chart_key"
        elif doc.book_page_start is not None and by_page.get(doc.book_page_start):
            item = by_page[doc.book_page_start][0]
            reason = "book_page"

        links.append(
            ReviewCaseTocCaseLink(
                link_id=f"toc_link_{len(links) + 1:04d}",
                toc_item_id=item.toc_item_id if item else None,
                review_case_id=doc.review_case_id,
                review_no=doc.review_no,
                chart_key=doc.reference_chart_key,
                document_reference_chart_key=doc.reference_chart_key,
                toc_chart_key=item.chart_key if item else None,
                toc_case_title=item.case_title if item else None,
                toc_case_condition=item.case_condition if item else None,
                chart_key_relation="same" if item and item.chart_key == doc.reference_chart_key else None,
                toc_book_page_no=item.book_page_no if item else None,
                case_book_page_start=doc.book_page_start,
                match_status="matched" if item else "unmatched",
                match_reason=reason,
                quality_flags=[] if item else ["toc_link_unmatched"],
            )
        )
    return links
