"""requests 기반 직접 다운로드 보조 모듈.

이 모듈은 3순위 보조 수단이다.
기본 다운로드는 Playwright 브라우저 방식이고, 직접 다운로드는 파일이 작거나 브라우저 다운로드가 필요 없을 때만 사용한다.
"""

# requests는 HTTP 직접 다운로드에 사용한다.
import requests

# Path는 저장 경로 처리를 위해 사용한다.
from pathlib import Path

# urljoin은 상대 URL을 절대 URL로 바꾸기 위해 사용한다.
from urllib.parse import urljoin

# 설정 객체를 가져온다.
from ..config import PipelineConfig

# 모델 객체를 가져온다.
from ..models import AttachmentCandidate, DownloadResult

# 파일명 정리 함수를 가져온다.
from ..paths import canonical_filename_for_document_type, ensure_unique_path

# 해시 계산 함수를 가져온다.
from .hash_utils import calculate_sha256, file_size


# download_attachment_direct 함수는 requests로 PDF를 직접 다운로드한다.
def download_attachment_direct(config: PipelineConfig, attachment: AttachmentCandidate) -> DownloadResult:
    # 저장 폴더를 미리 생성한다.
    config.raw_source_dir.mkdir(parents=True, exist_ok=True)
    # 원본 파일명을 안전한 파일명으로 바꾼다.
    safe_name = canonical_filename_for_document_type(
        attachment.document_type_candidate,
        attachment.original_filename,
        fallback_title=attachment.post_title,
    )
    # 저장 경로를 만든다.
    save_path = config.raw_source_dir / safe_name
    # 같은 이름이 있으면 번호를 붙인다.
    save_path = ensure_unique_path(save_path)
    # 상대 URL을 절대 URL로 변환한다.
    absolute_url = urljoin(attachment.source_page_url, attachment.attachment_url)
    # 일반 브라우저처럼 보이도록 header를 구성한다.
    headers = {"User-Agent": config.user_agent, "Referer": attachment.source_page_url}
    # HTTP GET 요청을 보낸다.
    response = requests.get(absolute_url, headers=headers, stream=True, timeout=30)
    # 응답 상태가 오류면 예외를 발생시킨다.
    response.raise_for_status()
    # 파일을 바이너리 쓰기 모드로 연다.
    with save_path.open("wb") as file:
        # 응답을 1MB 단위로 저장한다.
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            # 빈 chunk는 건너뛴다.
            if not chunk:
                # 빈 chunk면 다음으로 넘어간다.
                continue
            # 실제 파일에 chunk를 쓴다.
            file.write(chunk)
    # 파일 크기를 계산한다.
    size = file_size(save_path)
    # 파일 SHA256을 계산한다.
    sha = calculate_sha256(save_path)
    # 성공 결과를 반환한다.
    return DownloadResult(
        status="downloaded_direct",
        download_method="direct",
        saved_path=str(save_path),
        saved_filename=save_path.name,
        file_size=size,
        sha256=sha,
    )
