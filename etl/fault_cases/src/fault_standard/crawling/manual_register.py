"""수동 다운로드 PDF를 manifest에 등록하는 모듈.

브라우저 자동 다운로드가 실패하더라도 수집 단계가 막히면 안 된다.
사람이 PDF를 받아 raw/source_files에 넣은 뒤, 이 모듈로 manifest를 생성하면 후속 수집 검증과 전처리는 동일하게 진행된다.
"""

# Path는 로컬 PDF 경로를 다루기 위해 사용한다.
from pathlib import Path

# 설정과 상수를 가져온다.
from ..config import PipelineConfig, SOURCE_TYPE, SOURCE_RELIABILITY_SCORE

# 모델 객체와 시간 함수를 가져온다.
from ..models import ManifestRow, now_iso

# 문서유형 점수화 함수를 가져온다.
from .candidate_scorer import score_document_type

# 해시 계산 함수를 가져온다.
from .hash_utils import calculate_sha256, file_size

# manifest 기록 함수를 가져온다.
from .manifest import append_jsonl

# crawler의 ID 생성 함수를 가져온다.
from .crawler import make_collection_id


# register_manual_pdf 함수는 이미 다운로드된 PDF를 manifest에 등록한다.
def register_manual_pdf(
    config: PipelineConfig,
    pdf_path: Path,
    source_page_url: str,
    attachment_url: str,
    post_title: str,
    post_date: str | None = None,
) -> dict:
    # 필요한 폴더를 생성한다.
    config.ensure_dirs()
    # PDF 경로를 Path 객체로 통일한다.
    pdf_path = Path(pdf_path)
    # 파일이 없으면 오류를 낸다.
    if not pdf_path.exists():
        # 수동 등록할 파일이 없다는 뜻이다.
        raise FileNotFoundError(f"수동 등록 PDF를 찾을 수 없습니다: {pdf_path}")
    # 파일명과 제목으로 문서유형을 점수화한다.
    score_result = score_document_type(post_title, pdf_path.name, "")
    # 파일 SHA256을 계산한다.
    sha = calculate_sha256(pdf_path)
    # 파일 크기를 계산한다.
    size = file_size(pdf_path)
    # collection_id를 만든다.
    collection_id = make_collection_id(score_result["document_type_candidate"], source_page_url, attachment_url)
    # manifest row를 만든다.
    row = ManifestRow(
        collection_id=collection_id,
        source_type=SOURCE_TYPE,
        source_reliability_score=SOURCE_RELIABILITY_SCORE,
        seed_url=config.seed_url,
        source_page_url=source_page_url,
        attachment_url=attachment_url,
        post_title=post_title,
        post_date=post_date,
        original_filename=pdf_path.name,
        saved_filename=pdf_path.name,
        saved_path=str(pdf_path),
        document_type_candidate=score_result["document_type_candidate"],
        document_type_confidence=score_result["document_type_confidence"],
        matched_keywords=score_result["matched_keywords"],
        download_method="manual",
        status="manual_registered",
        file_size=size,
        sha256=sha,
        collected_at=now_iso(),
    ).to_dict()
    # manifest에 기록한다.
    append_jsonl(config.manifest_path, row)
    # 생성한 row를 반환한다.
    return row
