"""Playwright 브라우저 기반 PDF 다운로드 모듈.

강사님 Playwright 예제의 흐름을 최대한 활용했다.
핵심 흐름은 async_playwright 실행 → chromium.launch → new_context → new_page → goto → locator/click → download.save_as → browser.close 순서다.
"""

# asyncio는 비동기 함수를 실행하기 위해 사용한다.
import asyncio

# Path는 저장 경로를 다루기 위해 사용한다.
from pathlib import Path

# urljoin은 상대 URL을 절대 URL로 바꾸기 위해 사용한다.
from urllib.parse import urljoin

# Playwright 비동기 API를 가져온다.
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# 설정 객체를 가져온다.
from ..config import PipelineConfig

# 모델 객체를 가져온다.
from ..models import AttachmentCandidate, DownloadResult

# 파일명 정리 함수를 가져온다.
from ..paths import canonical_filename_for_document_type, ensure_unique_path

# 해시 계산 함수를 가져온다.
from .hash_utils import calculate_sha256, file_size


# download_attachment_with_browser 함수는 상세 페이지에서 첨부 PDF를 브라우저 방식으로 다운로드한다.
async def download_attachment_with_browser(config: PipelineConfig, attachment: AttachmentCandidate) -> DownloadResult:
    # 저장 폴더를 미리 생성한다.
    config.raw_source_dir.mkdir(parents=True, exist_ok=True)
    # 사이트의 원본 파일명이 105815.pdf처럼 내부 파일 ID일 수 있으므로 문서유형 기준 표준 파일명을 우선 사용한다.
    safe_name = canonical_filename_for_document_type(
        attachment.document_type_candidate,
        attachment.original_filename,
        fallback_title=attachment.post_title,
    )
    # 저장 경로를 만든다.
    save_path = config.raw_source_dir / safe_name
    # 터미널에서 어떤 PDF를 받는지 바로 볼 수 있게 출력한다.
    if config.verbose:
        # 문서유형과 저장 예정 파일명을 함께 보여준다.
        print(f"[download] 준비: {attachment.document_type_candidate} -> {safe_name}", flush=True)
    # 같은 이름이 있으면 번호를 붙여 중복 저장 충돌을 피한다.
    save_path = ensure_unique_path(save_path)
    # Playwright 컨텍스트 매니저를 시작한다.
    async with async_playwright() as playwright:
        # Chromium 브라우저를 실행한다.
        browser = await playwright.chromium.launch(headless=config.headless)
        # 다운로드 허용 컨텍스트를 만든다.
        context = await browser.new_context(
            accept_downloads=config.accept_downloads,
            user_agent=config.user_agent,
        )
        # 새 탭을 만든다.
        page = await context.new_page()
        # 기본 timeout을 설정한다.
        page.set_default_timeout(config.timeout_ms)
        # 상세 페이지로 이동한다.
        await page.goto(attachment.source_page_url, wait_until="domcontentloaded")
        # 첨부 URL이 상대경로일 수도 있으므로 절대 URL로 바꾼다.
        absolute_attachment_url = urljoin(attachment.source_page_url, attachment.attachment_url)
        # 다운로드 링크 후보 locator를 만든다.
        link_locator = page.locator(f'a[href="{absolute_attachment_url}"], a[href*="{attachment.attachment_url}"]').first
        # 링크가 정확히 안 잡히는 경우를 대비해 파일명 텍스트로도 locator를 만든다.
        filename_locator = page.get_by_text(attachment.original_filename, exact=False).first
        # 다운로드 시도 중 생기는 오류 메시지를 담기 위한 변수다.
        error_message = None
        # 첫 번째 방식은 expect_download 이벤트를 기다리며 클릭하는 것이다.
        try:
            # 다운로드 이벤트 대기를 시작한다.
            async with page.expect_download(timeout=config.timeout_ms) as download_info:
                # href locator가 있으면 그 링크를 클릭한다.
                if await link_locator.count() > 0:
                    # 정확한 링크를 클릭한다.
                    await link_locator.click()
                # href locator가 없으면 파일명 텍스트를 클릭한다.
                else:
                    # 파일명 텍스트 링크를 클릭한다.
                    await filename_locator.click()
            # 다운로드 객체를 가져온다.
            download = await download_info.value
            # 브라우저가 받은 파일을 지정 경로로 저장한다.
            await download.save_as(save_path)
            # 다운로드 이벤트 방식으로 저장됐음을 출력한다.
            if config.verbose:
                # 저장 경로를 출력해 VSCode 탐색기에서 바로 확인할 수 있게 한다.
                print(f"[download] 저장 완료: {save_path}", flush=True)
        # 다운로드 이벤트가 안 뜨면 context.request 방식으로 한 번 더 시도한다.
        except PlaywrightTimeoutError as error:
            # timeout 오류 메시지를 저장한다.
            error_message = f"browser download event timeout: {error}"
            # 브라우저 세션의 request 객체로 파일 URL을 가져온다.
            response = await context.request.get(absolute_attachment_url, timeout=config.timeout_ms)
            # 응답이 실패하면 예외를 낸다.
            if not response.ok:
                # HTTP 오류 상태를 포함해 실패를 알린다.
                raise RuntimeError(f"첨부파일 다운로드 실패: {response.status} {absolute_attachment_url}")
            # 응답 body를 바이너리로 받는다.
            content = await response.body()
            # 받은 내용을 파일로 저장한다.
            save_path.write_bytes(content)
            # fallback 방식으로 저장됐음을 출력한다.
            if config.verbose:
                # fallback은 다운로드 이벤트가 안 잡힌 경우다.
                print(f"[download] fallback 저장 완료: {save_path}", flush=True)
        # 마지막에는 브라우저를 닫는다.
        finally:
            # 브라우저 자원을 해제한다.
            await browser.close()
    # 파일이 실제로 저장됐는지 확인한다.
    if not save_path.exists():
        # 파일이 없으면 실패 결과를 반환한다.
        return DownloadResult(
            status="failed_download",
            download_method="browser",
            saved_path=None,
            saved_filename=None,
            file_size=None,
            sha256=None,
            error_message=error_message or "파일 저장 실패",
        )
    # 저장된 파일의 크기를 계산한다.
    size = file_size(save_path)
    # 저장된 파일의 SHA256을 계산한다.
    sha = calculate_sha256(save_path)
    # 성공 결과를 반환한다.
    return DownloadResult(
        status="downloaded_browser",
        download_method="browser",
        saved_path=str(save_path),
        saved_filename=save_path.name,
        file_size=size,
        sha256=sha,
        error_message=error_message,
    )


# download_attachment_sync 함수는 CLI에서 쉽게 부를 수 있도록 비동기 함수를 동기 실행한다.
def download_attachment_sync(config: PipelineConfig, attachment: AttachmentCandidate) -> DownloadResult:
    # asyncio.run으로 비동기 다운로드 함수를 실행한다.
    return asyncio.run(download_attachment_with_browser(config, attachment))
