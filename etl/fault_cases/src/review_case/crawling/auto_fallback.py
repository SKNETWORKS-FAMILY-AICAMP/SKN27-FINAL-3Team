"""
엔터 입력 없는 자동 브라우저 fallback 모듈.

역할:
1. Playwright 자동 다운로드가 canceled 되었을 때 프로그램을 멈추지 않는다.
2. 기본 브라우저로 PDF 직접 URL을 연다.
3. 설정된 다운로드 후보 폴더와 원본 PDF 폴더를 주기적으로 감시한다.
4. 정상 크기의 심의사례 PDF가 생기면 기준 파일명으로 복사한다.
5. 사용자가 Enter를 누르지 않아도 지정 시간 동안 자동으로 기다린다.

중요:
- 이 방식은 사용자가 엔터를 누르는 수동 fallback이 아니다.
- 다만 서버가 끝까지 파일을 주지 않으면 어떤 코드도 성공을 보장할 수는 없다.
- 그래도 프로그램은 자동으로 대기, 탐색, 복사까지 수행한다.
"""

from __future__ import annotations

import shutil
import time
import webbrowser
from pathlib import Path

from ..config import CollectionConfig
from ..paths import raw_pdf_dir
from .file_guard import canonical_pdf_path
from .utils import contains_any, log


def candidate_search_dirs(config: CollectionConfig) -> list[Path]:
    """완료된 PDF 후보를 찾을 폴더 목록을 반환한다."""

    # 후보 폴더 목록을 만든다.
    dirs: list[Path] = []

    # 파이프라인 원본 PDF 폴더를 먼저 본다.
    dirs.append(raw_pdf_dir(config.output_root))

    # 설정된 브라우저 다운로드 폴더를 본다.
    dirs.extend(config.browser_download_dirs)

    # 중복을 제거하고 존재하는 폴더만 반환한다.
    unique_dirs: list[Path] = []
    seen: set[Path] = set()
    for folder in dirs:
        resolved = folder.expanduser().resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        unique_dirs.append(resolved)
    return unique_dirs


def is_incomplete_browser_file(path: Path) -> bool:
    """브라우저가 아직 다운로드 중인 임시 파일인지 확인한다."""

    # Chrome/Edge 임시 다운로드 확장자다.
    if path.suffix.lower() == ".crdownload":
        return True

    # 기타 브라우저/도구의 임시 확장자다.
    if path.suffix.lower() in {".part", ".tmp"}:
        return True

    # 임시 파일이 아니면 False다.
    return False


def find_completed_pdf_candidate(config: CollectionConfig) -> Path | None:
    """다운로드 폴더에서 완료된 심의사례 PDF 후보를 찾는다."""

    # 후보 파일 목록을 만든다.
    candidates: list[Path] = []

    # 검색 대상 폴더를 순회한다.
    for folder in candidate_search_dirs(config):
        # PDF 파일만 본다.
        for path in folder.glob("*.pdf"):
            # 파일이 아니면 건너뛴다.
            if not path.is_file():
                continue

            # 임시 파일이면 건너뛴다.
            if is_incomplete_browser_file(path):
                continue

            # 최소 크기보다 작으면 실패/불완전 파일일 가능성이 크다.
            if path.stat().st_size < config.min_valid_pdf_bytes:
                continue

            # 파일명에 심의사례 키워드가 있으면 후보로 인정한다.
            if contains_any(path.name, config.pdf_include_keywords):
                candidates.append(path)

            # 파일명이 애매해도 기본 target PDF와 크기가 충분히 크면 후보로 인정한다.
            elif path.stat().st_size >= config.min_valid_pdf_bytes and "과실" in path.name:
                candidates.append(path)

    # 후보가 없으면 None을 반환한다.
    if not candidates:
        return None

    # 가장 최근에 수정된 파일을 우선 사용한다.
    return max(candidates, key=lambda path: path.stat().st_mtime)


def has_active_download(config: CollectionConfig) -> bool:
    """다운로드 폴더에 아직 진행 중인 임시 다운로드가 있는지 확인한다."""

    # 검색 대상 폴더를 순회한다.
    for folder in candidate_search_dirs(config):
        # Chrome/Edge 임시 다운로드 파일을 확인한다.
        for pattern in ["*.crdownload", "*.part", "*.tmp"]:
            # 하나라도 있으면 진행 중으로 본다.
            if any(folder.glob(pattern)):
                return True

    # 진행 중인 임시 파일이 없으면 False다.
    return False


def install_candidate_as_canonical(config: CollectionConfig, candidate: Path) -> Path:
    """후보 PDF를 기준 파일명으로 복사한다."""

    # 기준 PDF 경로를 만든다.
    canonical = canonical_pdf_path(config)

    # 기준 PDF 폴더를 만든다.
    canonical.parent.mkdir(parents=True, exist_ok=True)

    # 후보가 이미 기준 경로라면 그대로 반환한다.
    if candidate.resolve() == canonical.resolve():
        return canonical

    # 기존 기준 파일이 있으면 삭제한다.
    canonical.unlink(missing_ok=True)

    # 후보 파일을 기준 위치로 복사한다.
    shutil.copy2(candidate, canonical)

    # 기준 파일 경로를 반환한다.
    return canonical


def open_download_in_default_browser(url: str) -> None:
    """기본 브라우저로 PDF 다운로드 URL을 연다."""

    # 브라우저로 URL을 열면 Chrome/Edge의 일반 다운로드 흐름을 사용한다.
    webbrowser.open(url)


def wait_until_candidate_appears(config: CollectionConfig, wait_seconds: int, poll_seconds: int) -> Path:
    """지정 시간 동안 완료 PDF가 생기는지 자동 감시한다."""

    # 시작 시간을 기록한다.
    start_time = time.time()

    # 마지막 로그 출력 시간을 기록한다.
    last_log_time = 0.0

    # 제한 시간까지 반복한다.
    while True:
        # 완료된 PDF 후보를 찾는다.
        candidate = find_completed_pdf_candidate(config)

        # 후보가 있으면 기준 파일명으로 복사하고 반환한다.
        if candidate is not None:
            canonical = install_candidate_as_canonical(config, candidate)
            log(f"[자동대기] 완료 PDF 발견: {candidate}")
            log(f"[자동대기] 기준 파일로 복사 완료: {canonical}")
            return canonical

        # 경과 시간을 계산한다.
        elapsed = time.time() - start_time

        # 제한 시간을 넘으면 실패한다.
        if elapsed >= wait_seconds:
            raise RuntimeError(
                f"자동 대기 시간 초과: {wait_seconds}초 동안 완료 PDF를 찾지 못했습니다. "
                f"검색 폴더={candidate_search_dirs(config)}"
            )

        # 10초에 한 번 정도 상태 로그를 출력한다.
        if time.time() - last_log_time >= 10:
            last_log_time = time.time()
            active_text = "진행 중 임시파일 있음" if has_active_download(config) else "진행 중 임시파일 없음"
            log(f"[자동대기] PDF 완료 대기 중... {int(elapsed)}초 경과 / {active_text}")

        # 지정된 polling 간격만큼 기다린다.
        time.sleep(poll_seconds)


def auto_browser_download_fallback(
    config: CollectionConfig,
    attachment_url: str,
    wait_seconds: int | None = None,
    poll_seconds: int | None = None,
) -> Path:
    """기본 브라우저를 열고 완료 PDF가 생길 때까지 자동으로 기다린다."""

    # 설정값을 확정한다.
    resolved_wait_seconds = wait_seconds if wait_seconds is not None else config.fallback_wait_seconds
    resolved_poll_seconds = poll_seconds if poll_seconds is not None else config.fallback_poll_seconds

    # 안내 로그를 출력한다.
    log("[자동대기] Playwright 다운로드가 실패하여 기본 브라우저 fallback을 시작합니다.")
    log("[자동대기] Enter 입력은 필요 없습니다.")
    log(f"[자동대기] URL: {attachment_url}")
    log("[자동대기] 상세 페이지가 열리면 첨부파일 PDF를 한 번 클릭해 주세요.")
    log("[자동대기] 이후 다운로드 완료 파일은 자동으로 감지해 기준 파일로 복사합니다.")

    # 기본 브라우저로 상세 페이지 또는 다운로드 URL을 연다.
    open_download_in_default_browser(attachment_url)

    # 완료 PDF가 생길 때까지 기다린다.
    return wait_until_candidate_appears(
        config=config,
        wait_seconds=resolved_wait_seconds,
        poll_seconds=resolved_poll_seconds,
    )

