"""BeautifulSoup 기반 HTML 파싱 모듈.

강사님 BeautifulSoup 예제의 `BeautifulSoup(html, "html.parser")`, `find_all()` 흐름을 수집 코드에 맞게 모듈화했다.
Playwright는 동적 페이지를 여는 역할을 하고, BeautifulSoup은 열린 페이지 HTML에서 링크와 텍스트를 안정적으로 추출하는 역할을 한다.
"""

# re는 등록일과 목록 번호를 정규표현식으로 찾기 위해 사용한다.
import re

# urljoin은 상대 URL을 절대 URL로 바꾸기 위해 사용한다.
from urllib.parse import urljoin

# BeautifulSoup은 HTML 문서를 파싱하기 위해 사용한다.
from bs4 import BeautifulSoup as bs

# 게시글 후보 모델을 가져온다.
from ..models import StandardPostCandidate, AttachmentCandidate
from ..config import DEFAULT_STANDARD_FILENAME

# 문서유형 점수화 함수를 가져온다.
from .candidate_scorer import score_document_type


# normalize_spaces 함수는 HTML에서 추출한 여러 공백과 줄바꿈을 정리한다.
def normalize_spaces(text: str) -> str:
    # None이 들어오면 빈 문자열로 바꾼다.
    text = text or ""
    # 연속된 공백과 줄바꿈을 하나의 공백으로 줄인다.
    text = re.sub(r"\s+", " ", text)
    # 앞뒤 공백을 제거해 반환한다.
    return text.strip()


# parse_standard_posts 함수는 기준정보 목록 HTML에서 standard-content 게시글 링크를 추출한다.
def parse_standard_posts(html: str, base_url: str, page_no: int = 1) -> list[StandardPostCandidate]:
    # BeautifulSoup 객체를 만든다.
    soup = bs(html, "html.parser")
    # 결과 후보를 담을 리스트를 만든다.
    candidates: list[StandardPostCandidate] = []
    # href에 standard-content가 들어간 a 태그를 모두 찾는다.
    for anchor in soup.find_all("a", href=True):
        # href 값을 가져온다.
        href = anchor.get("href") or ""
        # 기준정보 상세 링크가 아니면 건너뛴다.
        if "standard-content" not in href:
            # 메뉴 링크나 다른 링크는 수집 후보가 아니다.
            continue
        # 링크 텍스트를 게시글 제목 후보로 가져온다.
        title = normalize_spaces(anchor.get_text(" ", strip=True))
        # 제목이 너무 짧으면 게시글 후보가 아닐 수 있다.
        if len(title) < 5:
            # 의미 있는 게시글 제목이 아니므로 건너뛴다.
            continue
        # 상세 URL을 절대 URL로 만든다.
        detail_url = urljoin(base_url, href)
        # 부모 tr이 있으면 row 전체 텍스트를 가져온다.
        parent_row = anchor.find_parent("tr")
        # tr이 없으면 부모 li 또는 현재 anchor 텍스트를 사용한다.
        row_text = normalize_spaces(parent_row.get_text(" ", strip=True)) if parent_row else title
        # row_text에서 등록일을 찾는다.
        date_match = re.search(r"(20\d{2}-\d{2}-\d{2})", row_text)
        # 날짜가 있으면 post_date에 넣는다.
        post_date = date_match.group(1) if date_match else None
        # row_text 앞쪽에서 목록 번호를 찾는다.
        no_match = re.search(r"^\s*(\d+)", row_text)
        # 목록 번호가 있으면 list_no에 넣는다.
        list_no = no_match.group(1) if no_match else None
        # 게시글 후보 객체를 만든다.
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
    # 상세 URL 기준 중복 제거용 dict를 만든다.
    unique = {}
    # 후보를 순회한다.
    for candidate in candidates:
        # 같은 상세 URL이면 마지막 값을 남긴다.
        unique[candidate.source_page_url] = candidate
    # 중복 제거된 후보 목록을 반환한다.
    return list(unique.values())


# parse_pdf_attachments 함수는 기준정보 상세 HTML에서 PDF 첨부 링크를 추출한다.
def parse_pdf_attachments(html: str, base_url: str, post: StandardPostCandidate) -> list[AttachmentCandidate]:
    # BeautifulSoup 객체를 만든다.
    soup = bs(html, "html.parser")
    # 상세페이지 전체 텍스트를 만든다.
    detail_text = normalize_spaces(soup.get_text(" ", strip=True))
    # 첨부 후보를 담을 리스트를 만든다.
    attachments: list[AttachmentCandidate] = []
    # 모든 a 태그를 순회한다.
    for anchor in soup.find_all("a", href=True):
        # href 값을 가져온다.
        href = anchor.get("href") or ""
        # 링크 텍스트를 가져온다.
        link_text = normalize_spaces(anchor.get_text(" ", strip=True))
        # pdf 링크 또는 file-manager 링크가 아니면 건너뛴다.
        if ".pdf" not in href.lower() and ".pdf" not in link_text.lower() and "file-manager" not in href:
            # 첨부 PDF 후보가 아니다.
            continue
        # 첨부 URL을 절대 URL로 변환한다.
        attachment_url = urljoin(base_url, href)
        # 파일명 후보는 링크 텍스트를 우선하고 없으면 URL 마지막 조각을 쓴다.
        original_filename = link_text or attachment_url.split("/")[-1] or DEFAULT_STANDARD_FILENAME
        # 게시글 제목, 파일명, 본문으로 문서유형 점수를 계산한다.
        score_result = score_document_type(post.post_title, original_filename, detail_text)
        # 문서유형 후보가 없으면 낮은 품질 후보이므로 건너뛴다.
        if not score_result["document_type_candidate"]:
            # 기준 PDF가 아닐 가능성이 높다.
            continue
        # 첨부 후보 객체를 만든다.
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
    # 첨부 후보 목록을 반환한다.
    return attachments
