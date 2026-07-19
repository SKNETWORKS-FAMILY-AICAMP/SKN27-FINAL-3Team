"""HTML parsing helpers for the fault standard collection pipeline."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup as bs

from ..config import DEFAULT_STANDARD_FILENAME
from ..models import AttachmentCandidate, StandardPostCandidate
from .candidate_scorer import score_document_type


FILE_DOWN_PATTERN = re.compile(
    r"fileDown\s*\(\s*['\"]?([^,'\")]+)['\"]?\s*,\s*['\"]([^'\"]+?\.pdf)['\"]",
    flags=re.IGNORECASE,
)


def normalize_spaces(text: str) -> str:
    text = text or ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_file_down(raw_value: str) -> tuple[str, str] | None:
    match = FILE_DOWN_PATTERN.search(raw_value or "")
    if not match:
        return None
    return match.group(1).strip(), normalize_spaces(match.group(2))


def make_file_down_url(file_id: str, filename: str) -> str:
    return f"javascript:fileDown('{file_id}','{filename}')"


def extract_date_tokens(text: str) -> set[str]:
    """Extract generic year/date tokens without document-specific hardcoding."""

    text = text or ""
    tokens = set(re.findall(r"20\d{2}", text))
    for compact_date in re.findall(r"(?<!\d)(\d{6})(?!\d)", text):
        tokens.add(compact_date)
        if compact_date[:2] in {"20", "21", "22", "23", "24", "25", "26", "27", "28", "29"}:
            tokens.add(f"20{compact_date[:2]}")
    return tokens


def is_attachment_consistent_with_post(post_title: str, original_filename: str) -> bool:
    """Reject only clear date contradictions between a post and an attachment."""

    post_dates = extract_date_tokens(post_title)
    file_dates = extract_date_tokens(original_filename)
    if post_dates and file_dates and post_dates.isdisjoint(file_dates):
        return False
    return True


def iter_pdf_attachment_sources(soup: bs) -> list[tuple[str, str]]:
    """Extract PDF download targets from href and onclick/fileDown patterns."""

    sources: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_source(raw_url: str, filename: str) -> None:
        raw_url = normalize_spaces(raw_url)
        filename = normalize_spaces(filename)
        if not raw_url or not filename:
            return
        key = (raw_url, filename)
        if key in seen:
            return
        seen.add(key)
        sources.append(key)

    for anchor in soup.find_all("a"):
        href = anchor.get("href") or ""
        onclick = anchor.get("onclick") or ""
        link_text = normalize_spaces(anchor.get_text(" ", strip=True))

        parsed = parse_file_down(href) or parse_file_down(onclick)
        if parsed:
            file_id, filename = parsed
            add_source(href or make_file_down_url(file_id, filename), filename)
            continue

        if ".pdf" in href.lower() or ".pdf" in link_text.lower() or "file-manager" in href:
            add_source(href, link_text or href.split("/")[-1] or DEFAULT_STANDARD_FILENAME)

    for tag in soup.find_all(onclick=True):
        onclick = tag.get("onclick") or ""
        parsed = parse_file_down(onclick)
        if not parsed:
            continue
        file_id, filename = parsed
        add_source(make_file_down_url(file_id, filename), filename)

    return sources


def parse_standard_posts(html: str, base_url: str, page_no: int = 1) -> list[StandardPostCandidate]:
    soup = bs(html, "html.parser")
    candidates: list[StandardPostCandidate] = []

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href") or ""
        if "standard-content" not in href:
            continue

        title = normalize_spaces(anchor.get_text(" ", strip=True))
        if len(title) < 5:
            continue

        detail_url = urljoin(base_url, href)
        parent_row = anchor.find_parent("tr")
        row_text = normalize_spaces(parent_row.get_text(" ", strip=True)) if parent_row else title
        date_match = re.search(r"(20\d{2}-\d{2}-\d{2})", row_text)
        post_date = date_match.group(1) if date_match else None
        no_match = re.search(r"^\s*(\d+)", row_text)
        list_no = no_match.group(1) if no_match else None

        candidates.append(
            StandardPostCandidate(
                post_title=title,
                post_date=post_date,
                source_page_url=detail_url,
                list_no=list_no,
                page_no=page_no,
                list_text=row_text,
            )
        )

    unique: dict[str, StandardPostCandidate] = {}
    for candidate in candidates:
        unique[candidate.source_page_url] = candidate
    return list(unique.values())


def parse_pdf_attachments(html: str, base_url: str, post: StandardPostCandidate) -> list[AttachmentCandidate]:
    soup = bs(html, "html.parser")
    detail_text = normalize_spaces(soup.get_text(" ", strip=True))
    attachments: list[AttachmentCandidate] = []

    for raw_url, original_filename in iter_pdf_attachment_sources(soup):
        if not is_attachment_consistent_with_post(post.post_title, original_filename):
            continue

        attachment_url = raw_url if raw_url.lower().startswith("javascript:") else urljoin(base_url, raw_url)
        score_result = score_document_type(post.post_title, original_filename, detail_text)
        if not score_result["document_type_candidate"]:
            continue

        attachments.append(
            AttachmentCandidate(
                source_page_url=post.source_page_url,
                post_title=post.post_title,
                post_date=post.post_date,
                attachment_url=attachment_url,
                original_filename=original_filename,
                document_type_candidate=score_result["document_type_candidate"],
                document_type_confidence=score_result["document_type_confidence"],
                matched_keywords=score_result["matched_keywords"],
            )
        )

    return attachments