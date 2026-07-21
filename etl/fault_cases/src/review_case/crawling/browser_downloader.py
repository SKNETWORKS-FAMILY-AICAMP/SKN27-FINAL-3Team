"""Download the review case PDF with Playwright."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin

from ..config import CollectionConfig
from ..models import PdfLinkInfo
from .file_guard import canonical_pdf_path
from .utils import contains_any, log, normalize_text


async def extract_links(page) -> list[dict]:
    """Return text and href values from all anchors on the current page."""

    return await page.locator("a").evaluate_all(
        """anchors => anchors.map(a => ({
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href || a.getAttribute('href') || ''
        }))"""
    )


async def find_review_case_detail_url(page, config: CollectionConfig) -> str:
    """Find the target detail page from the research listing page."""

    links = await extract_links(page)
    for link in links:
        text = normalize_text(link.get("text"))
        href = normalize_text(link.get("href"))
        combined = f"{text} {href}"

        if contains_any(combined, config.post_exclude_keywords):
            continue
        if not contains_any(combined, config.post_include_keywords):
            continue
        if "research-content" not in href:
            continue

        detail_url = urljoin(config.seed_url, href)
        log(f"[browser] review case detail page found: {detail_url}")
        return detail_url

    log(f"[browser] listing search failed; using fallback detail URL: {config.detail_url}")
    return config.detail_url


def _target_url_matches(href: str, absolute_href: str, target_url: str) -> bool:
    if not target_url:
        return False
    target_without_scheme = target_url.removeprefix("https:").removeprefix("http:")
    return (
        target_url in absolute_href
        or target_without_scheme in href
        or target_without_scheme in absolute_href
    )


async def find_pdf_link_info(page, detail_url: str, config: CollectionConfig) -> PdfLinkInfo:
    """Find the real review case PDF link on the detail page."""

    links = await extract_links(page)
    target_url = normalize_text(config.download_url_part)
    candidates: list[tuple[int, PdfLinkInfo]] = []

    for link in links:
        text = normalize_text(link.get("text"))
        href = normalize_text(link.get("href"))
        if not href:
            continue

        absolute_href = urljoin(detail_url, href)
        combined = f"{text} {href} {absolute_href}"
        has_target_url = _target_url_matches(href, absolute_href, target_url)
        has_pdf_keyword = contains_any(combined, config.pdf_include_keywords)
        has_exclude = contains_any(combined, config.pdf_exclude_keywords)
        looks_like_download = "file-manager" in absolute_href or ".pdf" in absolute_href.lower()

        if has_target_url:
            candidates.append((0, PdfLinkInfo(attachment_url=href, link_text=text, source_page_url=detail_url)))
            continue

        if looks_like_download and has_pdf_keyword and not has_exclude:
            candidates.append((1, PdfLinkInfo(attachment_url=href, link_text=text, source_page_url=detail_url)))

    if not candidates and target_url:
        candidates.append((2, PdfLinkInfo(attachment_url=target_url, link_text=target_url, source_page_url=detail_url)))

    if not candidates:
        raise RuntimeError("Could not find a review case PDF download link.")

    selected = sorted(candidates, key=lambda item: item[0])[0][1]
    log(f"[browser] PDF link selected: {selected.link_text} / {selected.attachment_url}")
    return selected


async def click_and_save_download(page, link_info: PdfLinkInfo, output_path: Path, timeout_ms: int) -> str:
    """Click the PDF link and save the resulting browser download."""

    locator = page.locator(f'a[href="{link_info.attachment_url}"]').first
    if await locator.count() == 0:
        locator = page.locator(f'a[href*="{link_info.attachment_url.split("/")[-1]}"]').first
    if await locator.count() == 0:
        raise RuntimeError(f"Could not locate selected PDF link: {link_info.attachment_url}")

    async with page.expect_download(timeout=timeout_ms) as download_info:
        await locator.click()

    download = await download_info.value
    suggested_filename = download.suggested_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    failure_reason = await download.failure()
    if failure_reason:
        raise RuntimeError(f"Browser download failed: {failure_reason}")

    await download.save_as(output_path)
    return suggested_filename


async def download_with_browser(config: CollectionConfig) -> tuple[PdfLinkInfo, Path, str]:
    """Download the PDF through a browser session and return download metadata."""

    try:
        from playwright.async_api import async_playwright
    except ImportError as error:
        raise SystemExit(
            "[error] playwright is not installed.\n"
            "Install with:\n"
            "pip install playwright\n"
            "python -m playwright install chromium"
        ) from error

    output_path = canonical_pdf_path(config)
    log(f"[browser] seed_url={config.seed_url}")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=not config.headed)
        try:
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()

            await page.goto(config.seed_url, wait_until="domcontentloaded", timeout=config.page_timeout_ms)
            detail_url = await find_review_case_detail_url(page, config)
            await page.goto(detail_url, wait_until="domcontentloaded", timeout=config.page_timeout_ms)

            link_info = await find_pdf_link_info(page, detail_url, config)
            suggested_filename = await click_and_save_download(page, link_info, output_path, config.download_timeout_ms)
        finally:
            await browser.close()

    return link_info, output_path, suggested_filename
