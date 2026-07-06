"""KNIA 기준정보 게시판 수집 모듈.

이 모듈은 기준정보 게시판 1페이지에서 게시글 후보를 찾고, 상세 페이지에서 PDF 첨부파일 후보를 찾는다.
다운로드는 browser_downloader.py가 담당하고, 이 모듈은 후보 탐색, 중복 방지, 다운로드 대상 선별, manifest row 조립을 담당한다.
"""

# asyncio는 Playwright 비동기 실행에 필요하다.
import asyncio

# hashlib는 안정적인 collection_id를 만들기 위해 사용한다.
import hashlib

# urljoin은 상대 URL을 절대 URL로 바꾸기 위해 사용한다.
from urllib.parse import urljoin

# Path는 중복 파일 삭제 시 저장 경로를 안전하게 다루기 위해 사용한다.
from pathlib import Path

# Playwright 비동기 API를 사용한다.
from playwright.async_api import async_playwright

# 설정값과 상수를 가져온다.
from ..config import COLLECTION_ID_PREFIX, MAX_DOCUMENTS, PipelineConfig, SOURCE_TYPE, SOURCE_RELIABILITY_SCORE, UNKNOWN_DOCUMENT_TYPE

# 데이터 모델을 가져온다.
from ..models import StandardPostCandidate, AttachmentCandidate, ManifestRow, now_iso

# HTML 파싱 함수를 가져온다.
from .html_parser import parse_standard_posts, parse_pdf_attachments

# 문서유형 점수화 함수를 가져온다.
from .candidate_scorer import score_document_type

# 브라우저 다운로드 함수를 가져온다.
from .browser_downloader import download_attachment_with_browser

# manifest 기록 함수를 가져온다.
from .manifest import append_jsonl, read_jsonl

# 숫자 파일명 판별 함수를 가져온다.
from ..paths import looks_like_numeric_pdf_name


# log 함수는 verbose 설정이 켜져 있을 때만 터미널에 진행 상황을 출력한다.
def log(config: PipelineConfig, message: str) -> None:
    # 사용자가 조용한 실행을 원할 때는 출력하지 않는다.
    if config.verbose:
        # flush=True로 출력 버퍼를 바로 비워서 PowerShell에서 실시간으로 보이게 한다.
        print(message, flush=True)


# make_collection_id 함수는 문서유형과 URL을 기반으로 안정적인 수집 ID를 만든다.
def make_collection_id(document_type: str | None, source_page_url: str, attachment_url: str) -> str:
    # 문서유형이 없으면 unknown을 사용한다.
    prefix = document_type or UNKNOWN_DOCUMENT_TYPE
    # URL 조합을 해시 입력값으로 만든다.
    raw_key = f"{source_page_url}|{attachment_url}"
    # 해시 앞 12자리를 사용해 너무 긴 ID를 피한다.
    short_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:12]
    # 최종 collection_id를 반환한다.
    return f"{COLLECTION_ID_PREFIX}_{prefix}_{short_hash}"


def get_existing_success_page_urls(existing_rows: list[dict]) -> set[str]:
    success_page_urls: set[str] = set()
    # 기존 manifest row를 순회한다.
    for row in existing_rows:
        # 수집 상태를 가져온다.
        status = row.get("status")
        # 성공 또는 수동등록 상태가 아니면 건너뛴다.
        if status not in {"downloaded_browser", "downloaded_direct", "manual_registered", "duplicate"}:
            # 실패 row는 정상 수집으로 보지 않는다.
            continue
        # 저장 경로 문자열을 가져온다.
        saved_path = row.get("saved_path")
        # 저장 경로가 없으면 건너뛴다.
        if not saved_path:
            # 실제 파일이 없으면 정상 수집이 아니다.
            continue
        # 저장 파일이 실제로 존재하면 정상 수집된 문서유형으로 인정한다.
        if Path(saved_path).exists():
            source_page_url = row.get("source_page_url")
            if source_page_url:
                success_page_urls.add(source_page_url)
    return success_page_urls


# choose_best_attachment 함수는 한 게시글 안에서 실제 다운로드할 PDF 1개를 고른다.
def choose_best_attachment(attachments: list[AttachmentCandidate]) -> AttachmentCandidate | None:
    # 첨부 후보가 없으면 None을 반환한다.
    if not attachments:
        # 다운로드할 파일이 없다.
        return None
    # 후보 품질 점수를 계산하는 내부 함수를 정의한다.
    def quality_key(item: AttachmentCandidate) -> tuple:
        # 105815.pdf처럼 숫자 파일명인지 확인한다.
        is_numeric = looks_like_numeric_pdf_name(item.original_filename)
        # 숫자 파일명은 사람이 읽기 어려우므로 후순위로 둔다.
        meaningful_name_score = 0 if is_numeric else 1
        # 매칭 키워드 수를 계산한다.
        keyword_count = len(item.matched_keywords or [])
        # 파일명 길이는 너무 짧은 링크보다 실제 파일명 후보를 선호하기 위한 보조 점수다.
        filename_length = len(item.original_filename or "")
        # 최종 정렬 키를 반환한다.
        return (meaningful_name_score, item.document_type_confidence, keyword_count, filename_length)
    # 품질 점수가 가장 높은 후보를 선택한다.
    return sorted(attachments, key=quality_key, reverse=True)[0]


# collect_post_candidates 함수는 기준정보 목록에서 게시글 후보를 찾는다.
async def collect_post_candidates(config: PipelineConfig) -> list[StandardPostCandidate]:
    # 결과 후보를 담을 리스트를 만든다.
    candidates: list[StandardPostCandidate] = []
    # Playwright 컨텍스트 매니저를 시작한다.
    async with async_playwright() as playwright:
        # Chromium 브라우저를 실행한다.
        browser = await playwright.chromium.launch(headless=config.headless)
        # 브라우저 컨텍스트를 만든다.
        context = await browser.new_context(user_agent=config.user_agent)
        # 새 페이지를 만든다.
        page = await context.new_page()
        # 기본 timeout을 설정한다.
        page.set_default_timeout(config.timeout_ms)
        # 접속 시작 로그를 출력한다.
        log(config, f"[collect] 기준정보 페이지 접속: {config.seed_url}")
        # 기준정보 게시판으로 이동한다.
        await page.goto(config.seed_url, wait_until="domcontentloaded")
        # 페이지 제목을 가져온다. 강사님 예제의 page.title() 흐름을 유지한 것이다.
        title = await page.title()
        # 페이지 제목이 비어 있으면 사이트 로딩 실패 가능성이 있으므로 오류를 낸다.
        if not title:
            # 제목이 없으면 정상 페이지가 아닐 수 있다.
            raise RuntimeError("기준정보 페이지 제목을 가져오지 못했습니다.")
        # 페이지 제목을 출력한다.
        log(config, f"[collect] 페이지 제목: {title}")
        # 렌더링된 페이지 HTML을 가져온다.
        html = await page.content()
        # BeautifulSoup 파서로 기준정보 게시글 후보를 추출한다.
        candidates = parse_standard_posts(html, config.seed_url, page_no=1)
        # 브라우저를 닫는다.
        await browser.close()
    # 중복 상세 URL을 제거한다.
    unique = {}
    # 후보들을 순회한다.
    for item in candidates:
        # 상세 URL 기준으로 마지막 후보를 저장한다.
        unique[item.source_page_url] = item
    # 중복 제거된 후보 목록을 만든다.
    unique_candidates = list(unique.values())
    # 후보 개수를 출력한다.
    log(config, f"[collect] 목록에서 발견한 게시글 후보 수: {len(unique_candidates)}")
    # 중복 제거된 후보 목록을 반환한다.
    return unique_candidates


# collect_attachments_from_post 함수는 상세 페이지에서 PDF 첨부파일 후보를 찾는다.
async def collect_attachments_from_post(config: PipelineConfig, post: StandardPostCandidate) -> list[AttachmentCandidate]:
    # 첨부 후보를 담을 리스트를 만든다.
    attachments: list[AttachmentCandidate] = []
    # Playwright 컨텍스트 매니저를 시작한다.
    async with async_playwright() as playwright:
        # Chromium 브라우저를 실행한다.
        browser = await playwright.chromium.launch(headless=config.headless)
        # 브라우저 컨텍스트를 만든다.
        context = await browser.new_context(user_agent=config.user_agent)
        # 새 페이지를 만든다.
        page = await context.new_page()
        # 기본 timeout을 설정한다.
        page.set_default_timeout(config.timeout_ms)
        # 상세 페이지 접속 로그를 출력한다.
        log(config, f"[collect] 상세 페이지 확인: {post.post_title}")
        # 상세 페이지로 이동한다.
        await page.goto(post.source_page_url, wait_until="domcontentloaded")
        # 렌더링된 상세 페이지 HTML을 가져온다.
        html = await page.content()
        # BeautifulSoup 파서로 PDF 첨부 후보를 추출한다.
        attachments = parse_pdf_attachments(html, post.source_page_url, post)
        # 브라우저를 닫는다.
        await browser.close()
    # 첨부 후보 수를 출력한다.
    log(config, f"[collect] 첨부 후보 수: {len(attachments)}")
    # 첨부 후보 목록을 반환한다.
    return attachments


# run_collect_async 함수는 게시글 후보 탐색부터 다운로드와 manifest 기록까지 실행한다.
async def run_collect_async(config: PipelineConfig) -> list[dict]:
    # 필요한 산출물 폴더를 생성한다.
    config.ensure_dirs()
    # 기존 manifest를 읽는다.
    existing_rows = read_jsonl(config.manifest_path)
    # 기존 SHA256을 set으로 만든다.
    existing_hashes = {row.get("sha256") for row in existing_rows if row.get("sha256")}
    # 기존에 정상 수집된 상세 페이지 URL을 찾는다.
    existing_success_page_urls = get_existing_success_page_urls(existing_rows)
    # 이번 실행에서 이미 처리한 첨부 URL을 담는다.
    seen_attachment_urls: set[str] = set()
    # 이번 실행에서 이미 다운로드한 상세 페이지 URL을 담는다.
    downloaded_page_urls_this_run: set[str] = set()
    # 이번 실행 결과를 담을 리스트를 만든다.
    output_rows: list[dict] = []
    # 시작 로그를 출력한다.
    log(config, "[collect] 수집 시작")
    # 기존 정상 수집 상세 페이지 수를 출력한다.
    if existing_success_page_urls and not config.force_download:
        # 이미 받은 문서는 기본적으로 다시 받지 않는다.
        log(config, f"[collect] 기존 정상 수집 상세 페이지 수: {len(existing_success_page_urls)}")
    # 기준정보 목록에서 게시글 후보를 수집한다.
    posts = await collect_post_candidates(config)
    # 게시글 후보들을 순회한다.
    for post in posts:
        # 게시글 제목과 목록 텍스트로 먼저 문서유형을 점수화한다.
        post_score = score_document_type(post.post_title, "", post.list_text)
        # 게시글 기준 문서유형 후보를 가져온다.
        post_document_type = post_score.get("document_type_candidate")
        # 기준 PDF 후보가 아니면 상세 페이지까지 들어가지 않는다.
        if not post_document_type:
            # 불필요한 게시글을 건너뛰는 이유를 출력한다.
            log(config, f"[skip] 기준 PDF 후보 아님: {post.post_title}")
            # 다음 게시글로 넘어간다.
            continue
        # 이미 정상 수집된 상세 페이지이고 강제 재수집이 아니면 건너뛴다.
        if (post.source_page_url in existing_success_page_urls) and not config.force_download:
            # 중복 다운로드 방지 로그를 출력한다.
            log(config, f"[skip] 이미 수집된 게시글: {post.post_title}")
            # 다음 게시글로 넘어간다.
            continue
        # 이번 실행에서 이미 받은 상세 페이지면 건너뛴다.
        if post.source_page_url in downloaded_page_urls_this_run:
            # 같은 문서유형을 한 번 더 받지 않도록 로그를 출력한다.
            log(config, f"[skip] 이번 실행에서 이미 처리한 게시글: {post.post_title}")
            # 다음 게시글로 넘어간다.
            continue
        # 각 게시글 상세 페이지에서 첨부파일 후보를 찾는다.
        attachments = await collect_attachments_from_post(config, post)
        # 기준 PDF 후보 첨부만 남긴다.
        attachments = [item for item in attachments if item.document_type_candidate]
        # 이미 본 첨부 URL은 제거한다.
        fresh_attachments = []
        # 첨부 후보를 순회한다.
        for attachment in attachments:
            # 절대 URL로 정규화한다.
            absolute_url = urljoin(attachment.source_page_url, attachment.attachment_url)
            # 이미 처리한 URL이면 건너뛴다.
            if absolute_url in seen_attachment_urls:
                # 같은 첨부 URL 중복 다운로드를 막는다.
                log(config, f"[skip] 중복 첨부 URL: {absolute_url}")
                # 다음 첨부로 넘어간다.
                continue
            # 처음 보는 URL이면 set에 추가한다.
            seen_attachment_urls.add(absolute_url)
            # fresh 후보에 넣는다.
            fresh_attachments.append(attachment)
        # 한 게시글 안에서 가장 좋은 PDF 후보 1개만 고른다.
        attachment = choose_best_attachment(fresh_attachments)
        # 선택된 첨부가 없으면 건너뛴다.
        if not attachment:
            # 첨부가 없음을 출력한다.
            log(config, f"[skip] 다운로드할 PDF 첨부 없음: {post.post_title}")
            # 다음 게시글로 넘어간다.
            continue
        # 숫자 파일명이더라도 저장은 표준 파일명으로 바뀐다는 점을 출력한다.
        if looks_like_numeric_pdf_name(attachment.original_filename):
            # 사이트 내부 파일 ID 이름을 발견했음을 알린다.
            log(config, f"[info] 원본 링크명은 숫자형이지만 표준 파일명으로 저장 예정: {attachment.original_filename}")
        # 브라우저 방식으로 PDF를 다운로드한다.
        result = await download_attachment_with_browser(config, attachment)
        # 같은 sha256이 이미 있으면 duplicate로 상태를 바꾼다.
        is_duplicate = bool(result.sha256 and result.sha256 in existing_hashes)
        # 중복이면 duplicate 상태로 둔다.
        status = "duplicate" if is_duplicate else result.status
        # 중복 파일을 남기지 않는 설정이면 새로 받은 파일을 삭제한다.
        if is_duplicate and result.saved_path and not config.keep_duplicate_files:
            # 삭제 대상 경로를 만든다.
            duplicate_path = Path(result.saved_path)
            # 파일이 존재하면 삭제한다.
            if duplicate_path.exists():
                # 실제 중복 PDF 파일을 삭제한다.
                duplicate_path.unlink()
                # 삭제 로그를 출력한다.
                log(config, f"[cleanup] 중복 PDF 삭제: {duplicate_path}")
            # 삭제된 파일을 manifest에 정상 입력으로 남기지 않기 위해 저장 경로를 비운다.
            result.saved_path = None
            # 삭제된 파일명도 비운다.
            result.saved_filename = None
        # 수집 ID를 만든다.
        collection_id = make_collection_id(
            attachment.document_type_candidate,
            attachment.source_page_url,
            attachment.attachment_url,
        )
        # manifest row 객체를 만든다.
        row = ManifestRow(
            collection_id=collection_id,
            source_type=SOURCE_TYPE,
            source_reliability_score=SOURCE_RELIABILITY_SCORE,
            seed_url=config.seed_url,
            source_page_url=attachment.source_page_url,
            attachment_url=attachment.attachment_url,
            post_title=attachment.post_title,
            post_date=attachment.post_date,
            original_filename=attachment.original_filename,
            saved_filename=result.saved_filename,
            saved_path=result.saved_path,
            document_type_candidate=attachment.document_type_candidate,
            document_type_confidence=attachment.document_type_confidence,
            matched_keywords=attachment.matched_keywords,
            download_method=result.download_method,
            status=status,
            file_size=result.file_size,
            sha256=result.sha256,
            collected_at=now_iso(),
            error_message=result.error_message,
        ).to_dict()
        # 중복 삭제 row가 아니라면 manifest에 한 줄 추가한다.
        append_jsonl(config.manifest_path, row)
        # 실행 결과 리스트에도 추가한다.
        output_rows.append(row)
        # 새 해시를 기존 해시 set에 추가한다.
        if result.sha256:
            # 같은 실행 내 중복도 감지하기 위해 추가한다.
            existing_hashes.add(result.sha256)
        # 다운로드가 성공했으면 이번 실행 처리 문서유형에 추가한다.
        if status in {"downloaded_browser", "downloaded_direct", "manual_registered", "duplicate"}:
            # 같은 상세 페이지를 반복 다운로드하지 않는다.
            downloaded_page_urls_this_run.add(attachment.source_page_url)
        # 설정한 최대 문서 수만큼 확보되면 조기 종료한다.
        collected_count = len(existing_success_page_urls.union(downloaded_page_urls_this_run))
        if not config.force_download and collected_count >= MAX_DOCUMENTS:
            # 목록에서 필요한 개수만큼 찾았음을 출력한다.
            log(config, f"[collect] 기준 PDF 후보 {MAX_DOCUMENTS}개가 확보되어 수집을 종료합니다.")
            # 반복문을 종료한다.
            break
    # 종료 로그를 출력한다.
    log(config, f"[collect] 이번 실행 manifest 추가 row 수: {len(output_rows)}")
    # 결과 row 목록을 반환한다.
    return output_rows


# run_collect 함수는 CLI에서 쉽게 호출할 수 있는 동기 wrapper다.
def run_collect(config: PipelineConfig) -> list[dict]:
    # asyncio.run으로 비동기 수집 함수를 실행한다.
    return asyncio.run(run_collect_async(config))
