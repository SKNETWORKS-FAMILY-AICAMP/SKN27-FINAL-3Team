"""
Playwright 브라우저 방식 PDF 다운로드 파일.

역할:
- 실제 브라우저로 연구자료 페이지에 접속한다.
- 심의사례집 상세 페이지를 찾는다.
- PDF 다운로드 링크를 클릭한다.
- 다운로드 파일을 기준 PDF 경로에 저장한다.
"""

# Python 3.10 이하에서도 타입 힌트를 안전하게 쓰기 위해 annotations를 활성화한다.
from __future__ import annotations

# Path는 저장 경로 처리에 사용한다.
from pathlib import Path

# urljoin은 상대 URL을 절대 URL로 바꾸는 데 사용한다.
from urllib.parse import urljoin

# 설정 모델을 가져온다.
from ..config import CollectionConfig

# PDF 링크 정보 모델을 가져온다.
from ..models import PdfLinkInfo

# 기준 PDF 경로 함수를 가져온다.
from .file_guard import canonical_pdf_path

# 공통 유틸을 가져온다.
from .utils import contains_any, log, normalize_text


async def extract_links(page) -> list[dict]:
    """현재 페이지의 a 태그에서 text와 href를 추출한다."""

    # 브라우저 안에서 모든 a 태그를 순회해 text와 href를 가져온다.
    return await page.locator("a").evaluate_all(
        """anchors => anchors.map(a => ({
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href || a.getAttribute('href') || ''
        }))"""
    )


async def find_review_case_detail_url(page, config: CollectionConfig) -> str:
    """연구자료 목록에서 심의사례집 상세 페이지 URL을 찾는다."""

    # 현재 페이지의 링크 목록을 가져온다.
    links = await extract_links(page)

    # 링크를 하나씩 확인한다.
    for link in links:
        # 링크 텍스트를 정리한다.
        text = normalize_text(link.get("text"))

        # href를 정리한다.
        href = normalize_text(link.get("href"))

        # 비교용 문자열을 만든다.
        combined = f"{text} {href}"

        # 제외 키워드가 있으면 건너뛴다.
        if contains_any(combined, config.post_exclude_keywords):
            continue

        # 포함 키워드가 없으면 건너뛴다.
        if not contains_any(combined, config.post_include_keywords):
            continue

        # 상세 페이지 URL이 아니면 건너뛴다.
        if "research-content" not in href:
            continue

        # 상세 페이지 URL을 절대 URL로 만든다.
        detail_url = urljoin(config.seed_url, href)

        # 로그를 출력한다.
        log(f"[브라우저] 심의사례집 상세 페이지 발견: {detail_url}")

        # 찾은 URL을 반환한다.
        return detail_url

    # 못 찾으면 fallback URL을 반환한다.
    log(f"[브라우저] 목록 탐색 실패, fallback 상세 URL 사용: {config.detail_url}")

    # fallback 상세 URL을 반환한다.
    return config.detail_url


async def find_pdf_link_info(page, detail_url: str, config: CollectionConfig) -> PdfLinkInfo:
    """상세 페이지에서 심의사례 PDF 링크를 찾는다."""

    # 현재 페이지의 링크 목록을 가져온다.
    links = await extract_links(page)

    # 후보 리스트를 만든다.
    candidates: list[PdfLinkInfo] = []

    # 링크를 하나씩 검사한다.
    for link in links:
        # 링크 텍스트를 정리한다.
        text = normalize_text(link.get("text"))

        # href를 정리한다.
        href = normalize_text(link.get("href"))

        # 비교용 문자열을 만든다.
        combined = f"{text} {href}"

        # 지정한 다운로드 URL 일부가 있으면 강한 후보다.
        # 빈 문자열이면 모든 링크가 매칭되므로 반드시 값이 있을 때만 비교한다.
        has_target_url = bool(config.download_url_part) and config.download_url_part in href

        # PDF 포함 키워드 여부를 확인한다.
        has_pdf_keyword = contains_any(combined, config.pdf_include_keywords)

        # PDF 제외 키워드 여부를 확인한다.
        has_exclude = contains_any(combined, config.pdf_exclude_keywords)

        # target URL이면 후보로 추가한다.
        if has_target_url:
            candidates.append(PdfLinkInfo(attachment_url=href, link_text=text, source_page_url=detail_url))
            continue

        # target은 아니지만 심의사례 PDF로 보이면 후보로 추가한다.
        if has_pdf_keyword and not has_exclude:
            candidates.append(PdfLinkInfo(attachment_url=href, link_text=text, source_page_url=detail_url))

    # 후보가 없으면 오류를 발생시킨다.
    if not candidates:
        raise RuntimeError("심의사례 PDF 다운로드 링크를 찾지 못했습니다.")

    # 첫 번째 후보를 선택한다.
    selected = candidates[0]

    # 선택 로그를 출력한다.
    log(f"[브라우저] PDF 링크 선택: {selected.link_text} / {selected.attachment_url}")

    # 선택 후보를 반환한다.
    return selected


async def click_and_save_download(page, link_info: PdfLinkInfo, output_path: Path, timeout_ms: int) -> str:
    """PDF 링크를 클릭하고 다운로드 파일을 저장한다."""

    # href가 attachment_url과 정확히 같은 a 태그를 찾는다.
    locator = page.locator(f'a[href="{link_info.attachment_url}"]').first

    # 정확 매칭이 실패할 수 있으므로 마지막 ID 포함 조건으로 다시 찾는다.
    if await locator.count() == 0:
        locator = page.locator(f'a[href*="{link_info.attachment_url.split("/")[-1]}"]').first

    # 다운로드 이벤트를 기다리면서 링크를 클릭한다.
    async with page.expect_download(timeout=timeout_ms) as download_info:
        await locator.click()

    # 다운로드 객체를 얻는다.
    download = await download_info.value

    # 브라우저가 제안한 파일명을 얻는다.
    suggested_filename = download.suggested_filename

    # 저장 폴더를 만든다.
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 다운로드 실패 사유를 먼저 확인한다.
    failure_reason = await download.failure()

    # 실패 사유가 있으면 명확한 예외를 발생시킨다.
    if failure_reason:
        raise RuntimeError(f"브라우저 다운로드 실패: {failure_reason}")

    # 다운로드 파일을 기준 PDF 경로로 저장한다.
    await download.save_as(output_path)

    # 제안 파일명을 반환한다.
    return suggested_filename


async def download_with_browser(config: CollectionConfig) -> tuple[PdfLinkInfo, Path, str]:
    """브라우저 방식으로 PDF를 다운로드하고 결과를 반환한다."""

    # Playwright import를 시도한다.
    try:
        from playwright.async_api import async_playwright
    except ImportError as error:
        raise SystemExit(
            "[오류] playwright가 설치되어 있지 않습니다.\n"
            "설치 명령:\n"
            "pip install playwright\n"
            "python -m playwright install chromium"
        ) from error

    # 기준 PDF 저장 경로를 만든다.
    output_path = canonical_pdf_path(config)

    # 브라우저 실행 로그를 출력한다.
    log(f"[브라우저] seed_url={config.seed_url}")

    # Playwright context를 연다.
    async with async_playwright() as playwright:
        # Chromium 브라우저를 실행한다.
        browser = await playwright.chromium.launch(headless=not config.headed)

        # 다운로드 허용 context를 만든다.
        context = await browser.new_context(accept_downloads=True)

        # 새 페이지를 만든다.
        page = await context.new_page()

        # 연구자료 목록 페이지로 이동한다.
        await page.goto(config.seed_url, wait_until="domcontentloaded", timeout=config.page_timeout_ms)

        # 상세 페이지 URL을 찾는다.
        detail_url = await find_review_case_detail_url(page, config)

        # 상세 페이지로 이동한다.
        await page.goto(detail_url, wait_until="domcontentloaded", timeout=config.page_timeout_ms)

        # PDF 링크 정보를 찾는다.
        link_info = await find_pdf_link_info(page, detail_url, config)

        # 다운로드 링크를 클릭하고 파일을 저장한다.
        suggested_filename = await click_and_save_download(page, link_info, output_path, config.download_timeout_ms)

        # 브라우저를 닫는다.
        await browser.close()

    # 다운로드 결과를 반환한다.
    return link_info, output_path, suggested_filename

