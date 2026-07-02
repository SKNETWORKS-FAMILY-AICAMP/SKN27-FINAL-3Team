"""
원클릭 수집 오케스트레이터.

이 파일의 목표:
- 사용자가 여러 명령을 따로 실행하지 않게 한다.
- python run_collect.py 한 번으로 아래를 모두 수행한다.

실행 흐름:
1. 필요한 폴더 생성
2. 기존 실패 파일(.part) 삭제
3. 중복 PDF(_001, _002) 정리
4. 기준 PDF가 이미 있으면 다운로드 스킵
5. 기준 PDF가 없거나 force-download면 브라우저 다운로드
6. 다운로드 후 다시 정리
7. collection_manifest.jsonl을 깨끗하게 생성
8. collection_quality_report.jsonl을 깨끗하게 생성
"""

# Python 3.10 이하에서도 타입 힌트를 안전하게 쓰기 위해 annotations를 활성화한다.
from __future__ import annotations

# argparse는 터미널 옵션을 받기 위해 사용한다.
import argparse

# asyncio는 브라우저 다운로드 비동기 함수를 실행하기 위해 사용한다.
import asyncio

# Path는 경로 처리에 사용한다.
from pathlib import Path

# 설정 객체를 가져온다.
from ..config import CollectionConfig

# manifest row 모델을 가져온다.
from ..models import CollectionManifestRow, PdfLinkInfo

# 경로 생성 함수를 가져온다.
from ..paths import ensure_all_pipeline_dirs, collection_manifest_path, collection_quality_report_path

# 브라우저 다운로드 함수를 가져온다.
from .browser_downloader import download_with_browser

# 수집 검증 함수를 가져온다.
from .collection_validator import validate_canonical_pdf, log_validation_result

# 파일 정리/중복 방지 함수를 가져온다.
from .file_guard import cleanup_source_files, has_valid_canonical_pdf, canonical_pdf_path, log_canonical_pdf

# manifest 저장 함수를 가져온다.
from .manifest import write_collection_manifest, write_collection_quality

# 자동 다운로드 실패 시 엔터 입력 없는 기본 브라우저 fallback을 가져온다.
from .auto_fallback import auto_browser_download_fallback

# 공통 유틸을 가져온다.
from .utils import log, matched_keywords, now_iso, sha256_file


def make_collection_id(config: CollectionConfig, file_hash: str | None) -> str:
    """설정된 prefix와 파일 해시로 수집 ID를 만든다."""

    if file_hash:
        return f"{config.collection_id_prefix}_{file_hash[:12]}"
    return f"{config.collection_id_prefix}_missing"


def resolve_fallback_attachment_url(config: CollectionConfig) -> str:
    """기본 브라우저 fallback에서 열 URL을 결정한다.

    주의:
    - KNIA file-manager 직접 URL은 브라우저 밖에서 열면 403 또는 /about 리다이렉트가 날 수 있다.
    - fallback에서는 직접 파일 URL보다 상세 페이지를 여는 편이 안전하다.
    - 사용자가 열린 상세 페이지에서 첨부 PDF를 클릭하면, 자동대기 로직이 다운로드 폴더를 감시해 기준 PDF로 복사한다.
    """

    if config.detail_url.startswith(("http://", "https://")):
        log("[원클릭] fallback은 직접 파일 URL이 아니라 상세 페이지를 엽니다.")
        return config.detail_url

    if config.download_url_part.startswith(("http://", "https://")):
        log("[원클릭] 상세 페이지 URL이 없어 다운로드 URL을 fallback으로 엽니다.")
        return config.download_url_part

    raise RuntimeError(
        "fallback으로 열 수 있는 URL이 없습니다. "
        "--detail-url 또는 --download-url-part에 http(s) URL을 넣어 주세요."
    )


def build_manifest_from_existing_pdf(config: CollectionConfig, status: str) -> CollectionManifestRow:
    """이미 존재하는 기준 PDF를 기준으로 manifest row를 만든다."""

    # 기준 PDF 경로를 가져온다.
    pdf_path = canonical_pdf_path(config)

    # 파일 크기를 읽는다.
    file_size = pdf_path.stat().st_size

    # SHA-256 해시를 계산한다.
    file_hash = sha256_file(pdf_path)

    # collection_id를 만든다.
    collection_id = make_collection_id(config, file_hash)

    # link_info 역할을 하는 값들을 구성한다.
    attachment_url = config.download_url_part

    # 파일명 기반으로 매칭 키워드를 계산한다.
    keywords = matched_keywords(pdf_path.name, config.pdf_include_keywords)

    # manifest row를 반환한다.
    return CollectionManifestRow(
        collection_id=collection_id,
        seed_url=config.seed_url,
        source_page_url=config.detail_url,
        attachment_url=attachment_url,
        original_filename=pdf_path.name,
        saved_filename=pdf_path.name,
        saved_path=str(pdf_path),
        file_size=file_size,
        sha256=file_hash,
        matched_keywords=keywords,
        status=status,
        collection_method="existing_pdf_guarded",
        source_type=config.source_type,
        source_reliability_score=config.source_reliability_score,
        collected_at=now_iso(),
    )


def build_manifest_from_download(config: CollectionConfig, link_info: PdfLinkInfo, suggested_filename: str) -> CollectionManifestRow:
    """브라우저 다운로드 결과로 manifest row를 만든다."""

    # 기준 PDF 경로를 가져온다.
    pdf_path = canonical_pdf_path(config)

    # 파일 크기를 읽는다.
    file_size = pdf_path.stat().st_size

    # SHA-256 해시를 계산한다.
    file_hash = sha256_file(pdf_path)

    # collection_id를 만든다.
    collection_id = make_collection_id(config, file_hash)

    # 키워드 매칭 대상 문자열을 만든다.
    keyword_text = f"{link_info.link_text} {suggested_filename} {pdf_path.name}"

    # 매칭 키워드를 계산한다.
    keywords = matched_keywords(keyword_text, config.pdf_include_keywords)

    # manifest row를 반환한다.
    return CollectionManifestRow(
        collection_id=collection_id,
        seed_url=config.seed_url,
        source_page_url=link_info.source_page_url,
        attachment_url=link_info.attachment_url,
        original_filename=suggested_filename or link_info.link_text or pdf_path.name,
        saved_filename=pdf_path.name,
        saved_path=str(pdf_path),
        file_size=file_size,
        sha256=file_hash,
        matched_keywords=keywords,
        status="downloaded",
        collection_method="browser_playwright",
        source_type=config.source_type,
        source_reliability_score=config.source_reliability_score,
        collected_at=now_iso(),
    )


async def run_one_click_collect(config: CollectionConfig) -> None:
    """원클릭 수집 전체 흐름을 실행한다."""

    # 전체 산출물 폴더를 만든다.
    ensure_all_pipeline_dirs(config.output_root)

    # 시작 로그를 출력한다.
    log("[원클릭] 수집 시작")

    # 현재 기준 PDF 상태를 출력한다.
    log_canonical_pdf(config)

    # 실행 시작 전에 실패 파일과 중복 후보를 정리한다.
    cleanup_source_files(config)

    # cleanup만 요청한 경우 여기서 종료한다.
    if config.cleanup_only:
        log("[원클릭] cleanup_only=True 이므로 정리만 수행하고 종료합니다.")
        return

    # 기준 PDF가 이미 있고 강제 다운로드가 아니면 다운로드를 스킵한다.
    if has_valid_canonical_pdf(config) and not config.force_download:
        # 스킵 로그를 출력한다.
        log("[원클릭] 기준 PDF가 이미 있으므로 다운로드를 스킵합니다.")

        # 기존 PDF 기반 manifest를 만든다.
        manifest_row = build_manifest_from_existing_pdf(config, status="already_exists")

    else:
        # 강제 다운로드면 기존 기준 PDF를 삭제한다.
        if config.force_download:
            # 기준 PDF 경로를 가져온다.
            pdf_path = canonical_pdf_path(config)

            # 기존 파일을 삭제한다.
            pdf_path.unlink(missing_ok=True)

            # 삭제 로그를 출력한다.
            log(f"[원클릭] force_download=True 기존 기준 PDF 삭제: {pdf_path}")

        try:
            # 브라우저 다운로드를 실행한다.
            link_info, output_path, suggested_filename = await download_with_browser(config)

            # 다운로드 후 다시 정리한다.
            cleanup_source_files(config)

            # 다운로드 결과 기반 manifest를 만든다.
            manifest_row = build_manifest_from_download(config, link_info, suggested_filename)

        except Exception as download_error:
            # 자동 다운로드 실패 원인을 출력한다.
            log(f"[원클릭] 자동 브라우저 다운로드 실패: {download_error}")

            # 기본 브라우저 다운로드 fallback을 실행한다.
            # Enter 입력 없이 다운로드 폴더를 자동 감시한다.
            auto_browser_download_fallback(
                config=config,
                attachment_url=resolve_fallback_attachment_url(config),
                wait_seconds=config.fallback_wait_seconds,
                poll_seconds=config.fallback_poll_seconds,
            )

            # 자동 fallback 확보 후 다시 정리한다.
            cleanup_source_files(config)

            # 기존 PDF 기반 manifest를 만든다.
            manifest_row = build_manifest_from_existing_pdf(config, status="auto_browser_fallback_registered")

    # manifest를 깨끗하게 저장한다.
    manifest_file = write_collection_manifest(config.output_root, manifest_row, rewrite=config.rewrite_reports)

    # manifest 저장 로그를 출력한다.
    log(f"[원클릭] manifest 저장: {manifest_file}")

    # 수집 검증을 실행한다.
    if config.validate_after_collect:
        # 기준 PDF를 검증한다.
        quality_row = validate_canonical_pdf(config)

        # 검증 결과를 출력한다.
        log_validation_result(quality_row)

        # quality report를 깨끗하게 저장한다.
        quality_file = write_collection_quality(config.output_root, quality_row, rewrite=config.rewrite_reports)

        # quality report 저장 로그를 출력한다.
        log(f"[원클릭] quality report 저장: {quality_file}")

    # 마지막 기준 PDF 상태를 출력한다.
    log_canonical_pdf(config)

    # 완료 로그를 출력한다.
    log("[원클릭] 수집 완료")


def parse_args() -> CollectionConfig:
    """터미널 옵션을 CollectionConfig로 변환한다."""

    defaults = CollectionConfig()

    # ArgumentParser를 만든다.
    parser = argparse.ArgumentParser(description="심의사례 PDF 원클릭 수집기")

    # 연구자료 목록 URL을 받는다.
    parser.add_argument("--seed-url", default=defaults.seed_url)

    # 상세 페이지 URL을 받는다.
    parser.add_argument("--detail-url", default=defaults.detail_url)

    # 다운로드 URL 일부를 받는다.
    parser.add_argument("--download-url-part", default=defaults.download_url_part)

    # 산출물 root를 받는다.
    parser.add_argument("--output-root", default=str(defaults.output_root))

    # 기준 PDF 저장 파일명을 받는다.
    parser.add_argument("--output-name", default=defaults.output_name)

    # 정상 PDF로 인정할 최소 byte 크기를 받는다.
    parser.add_argument("--min-valid-pdf-bytes", type=int, default=defaults.min_valid_pdf_bytes)

    # fallback 감시 대상 다운로드 폴더를 받는다. 여러 번 줄 수 있다.
    parser.add_argument(
        "--browser-download-dir",
        action="append",
        default=None,
        help="fallback에서 감시할 다운로드 폴더. 여러 번 지정할 수 있습니다.",
    )

    # fallback 대기 시간을 받는다.
    parser.add_argument("--fallback-wait-seconds", type=int, default=defaults.fallback_wait_seconds)

    # fallback polling 간격을 받는다.
    parser.add_argument("--fallback-poll-seconds", type=int, default=defaults.fallback_poll_seconds)

    # collection_id prefix를 받는다.
    parser.add_argument("--collection-id-prefix", default=defaults.collection_id_prefix)

    # 브라우저 창 표시 여부를 받는다.
    parser.add_argument("--headed", action="store_true")

    # 기존 파일이 있어도 다시 다운로드할지 여부를 받는다.
    parser.add_argument("--force-download", action="store_true")

    # 정리만 할지 여부를 받는다.
    parser.add_argument("--cleanup-only", action="store_true")

    # 검증을 생략할지 여부를 받는다.
    parser.add_argument("--skip-validation", action="store_true")

    # manifest/quality report를 append할지 여부를 받는다.
    parser.add_argument("--append-reports", action="store_true")

    # 페이지 timeout을 받는다.
    parser.add_argument("--page-timeout-ms", type=int, default=defaults.page_timeout_ms)

    # 다운로드 timeout을 받는다.
    parser.add_argument("--download-timeout-ms", type=int, default=defaults.download_timeout_ms)

    # 인자를 파싱한다.
    args = parser.parse_args()

    # 다운로드 폴더 CLI 옵션이 있으면 그것을 사용하고, 없으면 기본 설정을 유지한다.
    browser_download_dirs = [Path(path).expanduser() for path in args.browser_download_dir] if args.browser_download_dir else defaults.browser_download_dirs

    # CollectionConfig를 만들어 반환한다.
    return CollectionConfig(
        seed_url=args.seed_url,
        detail_url=args.detail_url,
        download_url_part=args.download_url_part,
        output_root=Path(args.output_root).expanduser(),
        output_name=args.output_name,
        headed=args.headed,
        force_download=args.force_download,
        cleanup_only=args.cleanup_only,
        validate_after_collect=not args.skip_validation,
        rewrite_reports=not args.append_reports,
        min_valid_pdf_bytes=args.min_valid_pdf_bytes,
        page_timeout_ms=args.page_timeout_ms,
        download_timeout_ms=args.download_timeout_ms,
        fallback_wait_seconds=args.fallback_wait_seconds,
        fallback_poll_seconds=args.fallback_poll_seconds,
        browser_download_dirs=browser_download_dirs,
        collection_id_prefix=args.collection_id_prefix,
    )

def main() -> None:
    """명령행 실행 진입점이다."""

    # 설정 객체를 만든다.
    config = parse_args()

    # 원클릭 비동기 수집을 실행한다.
    asyncio.run(run_one_click_collect(config))


# 직접 실행 시 main을 호출한다.
if __name__ == "__main__":
    main()

