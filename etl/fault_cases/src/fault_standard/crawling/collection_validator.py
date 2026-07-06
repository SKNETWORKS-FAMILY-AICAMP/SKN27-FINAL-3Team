"""수집 검증 모듈.

이 모듈은 설정된 manifest에 기록된 PDF가 실제 전처리에 들어갈 수 있는 상태인지 확인한다.
검증은 단순히 파일이 있는지 보는 것이 아니라, PDF 파일 자체 검증과 문서유형 검증을 함께 수행한다.

검증 흐름은 다음과 같다.
1. manifest row를 읽는다.
2. saved_path 파일 존재 여부를 확인한다.
3. 확장자, 파일 크기, PDF 헤더를 확인한다.
4. PyMuPDF가 있으면 PDF를 실제로 열어 page_count와 sample_text를 추출한다.
5. PDF sample_text로 문서유형을 다시 판별한다.
6. manifest의 document_type_candidate와 PDF 내부 판별 결과가 맞는지 비교한다.
7. SHA256 중복 여부와 source_reliability_score=4 여부를 확인한다.
8. 설정된 품질 리포트 경로에 검증 결과를 저장한다.
"""

# Path는 파일 경로를 다루기 위해 사용한다.
from pathlib import Path

# Optional은 값이 없을 수 있는 반환 타입을 표현하기 위해 사용한다.
from typing import Optional

# 설정 객체와 신뢰도 점수를 가져온다.
from ..config import PipelineConfig, SOURCE_RELIABILITY_SCORE

# 후보 점수화 함수를 가져와 PDF sample_text 기반 문서유형 재판별에 사용한다.
from .candidate_scorer import score_document_type

# manifest 읽기/쓰기 함수를 가져온다.
from .manifest import read_jsonl, write_jsonl


# PDF_SAMPLE_PAGE_LIMIT는 PDF 내부 문서유형 확인에 사용할 최대 페이지 수다.
PDF_SAMPLE_PAGE_LIMIT = 10


# promote_status 함수는 현재 상태보다 더 강한 상태가 필요할 때 상태를 올려준다.
def promote_status(current_status: str, new_status: str) -> str:
    # 상태의 심각도 순서를 정의한다.
    severity = {
        # valid는 문제가 없다는 뜻이다.
        "valid": 0,
        # review_required는 사람 확인 또는 추가 보완이 필요하다는 뜻이다.
        "review_required": 1,
        # duplicate는 같은 SHA256이 이미 있다는 뜻이다.
        "duplicate": 2,
        # excluded는 전처리 입력으로 쓰기 어렵다는 뜻이다.
        "excluded": 3,
    }
    # 새 상태가 현재 상태보다 심각하면 새 상태를 반환한다.
    if severity.get(new_status, 0) > severity.get(current_status, 0):
        # 더 심각한 상태를 사용한다.
        return new_status
    # 현재 상태가 더 심각하면 현재 상태를 유지한다.
    return current_status


# looks_like_pdf 함수는 파일 앞부분이 PDF 헤더인지 확인한다.
def looks_like_pdf(path: Path) -> bool:
    # 파일 읽기 중 오류가 나면 PDF가 아닌 것으로 처리한다.
    try:
        # 파일을 바이너리 읽기 모드로 연다.
        with path.open("rb") as file:
            # PDF 파일은 보통 첫 5바이트가 %PDF-다.
            header = file.read(5)
        # 헤더가 PDF 형식이면 True를 반환한다.
        return header == b"%PDF-"
    # 파일 열기 자체가 실패하면 False를 반환한다.
    except OSError:
        # 파일 접근 실패는 PDF 확인 실패로 본다.
        return False


# get_file_size 함수는 파일 크기를 안전하게 가져온다.
def get_file_size(path: Path) -> Optional[int]:
    # stat 호출이 실패할 수 있으므로 예외를 처리한다.
    try:
        # 파일 크기를 바이트 단위로 반환한다.
        return path.stat().st_size
    # 파일이 없거나 접근할 수 없으면 None을 반환한다.
    except OSError:
        # 파일 크기 확인 실패를 표현한다.
        return None


# extract_pdf_sample 함수는 PyMuPDF로 PDF를 열고 앞쪽 페이지 텍스트를 추출한다.
def extract_pdf_sample(path: Path, max_pages: int = PDF_SAMPLE_PAGE_LIMIT) -> dict:
    # PyMuPDF 설치 여부를 확인한다.
    try:
        # fitz는 PyMuPDF의 import 이름이다.
        import fitz  # type: ignore
    # PyMuPDF가 설치되어 있지 않으면 검증 일부를 건너뛴다.
    except ImportError:
        # 설치 누락 정보를 반환한다.
        return {
            "pdf_open_ok": None,
            "page_count": None,
            "sample_text": "",
            "sample_text_length": 0,
            "text_extract_ok": None,
            "extractor": "pymupdf_not_installed",
            "error_message": "PyMuPDF가 설치되어 있지 않아 PDF 내부 검증을 수행하지 못했습니다.",
        }
    # PDF 열기와 텍스트 추출 중 오류가 날 수 있으므로 예외를 처리한다.
    try:
        # PDF 문서를 연다.
        doc = fitz.open(str(path))
        # 전체 페이지 수를 가져온다.
        page_count = len(doc)
        # 샘플 텍스트를 담을 리스트를 만든다.
        sample_parts: list[str] = []
        # 실제로 읽을 페이지 수를 정한다.
        read_page_count = min(page_count, max_pages)
        # 앞쪽 페이지를 순회한다.
        for page_index in range(read_page_count):
            # 현재 페이지 객체를 가져온다.
            page = doc[page_index]
            # 페이지 텍스트를 추출한다.
            page_text = page.get_text("text") or ""
            # 페이지 번호를 함께 붙여 나중에 추적 가능하게 한다.
            sample_parts.append(f"\n[PAGE {page_index + 1}]\n{page_text}")
        # PDF 문서를 닫는다.
        doc.close()
        # 샘플 텍스트를 하나로 합친다.
        sample_text = "\n".join(sample_parts).strip()
        # 텍스트가 조금이라도 있으면 추출 성공으로 본다.
        text_extract_ok = len(sample_text) > 0
        # PDF 내부 진단 결과를 반환한다.
        return {
            "pdf_open_ok": True,
            "page_count": page_count,
            "sample_text": sample_text,
            "sample_text_length": len(sample_text),
            "text_extract_ok": text_extract_ok,
            "extractor": "pymupdf",
            "error_message": None,
        }
    # PDF 열기 또는 텍스트 추출 실패를 잡는다.
    except Exception as exc:
        # 실패 정보를 반환한다.
        return {
            "pdf_open_ok": False,
            "page_count": None,
            "sample_text": "",
            "sample_text_length": 0,
            "text_extract_ok": False,
            "extractor": "pymupdf",
            "error_message": str(exc),
        }


# detect_document_type_from_pdf_sample 함수는 PDF 내부 샘플 텍스트로 문서유형을 재판별한다.
def detect_document_type_from_pdf_sample(row: dict, sample_text: str) -> dict:
    # 게시글 제목을 가져온다.
    title = row.get("post_title") or ""
    # 원본 파일명을 가져온다.
    filename = row.get("original_filename") or row.get("saved_filename") or ""
    # 제목, 파일명, PDF 샘플 텍스트를 함께 넣어 점수화한다.
    scored = score_document_type(title=title, filename=filename, detail_text=sample_text)
    # 점수화 결과를 반환한다.
    return scored


# validate_collection 함수는 manifest를 읽고 수집 품질 리포트를 만든다.
def validate_collection(config: PipelineConfig) -> list[dict]:
    # 필요한 폴더를 생성한다.
    config.ensure_dirs()
    # manifest row를 읽는다.
    rows = read_jsonl(config.manifest_path)
    # 검증 결과를 담을 리스트를 만든다.
    reports: list[dict] = []
    # 중복 해시 탐지를 위한 set을 만든다.
    seen_hashes: set[str] = set()
    # manifest row를 순회한다.
    for row in rows:
        # 품질 플래그 목록을 만든다.
        flags: list[str] = []
        # 기본 상태는 valid로 둔다.
        status = "valid"
        # 저장 경로 문자열을 가져온다.
        saved_path_value = row.get("saved_path")
        # PDF 내부 진단 기본값을 준비한다.
        pdf_diag = {
            "pdf_open_ok": None,
            "page_count": None,
            "sample_text": "",
            "sample_text_length": 0,
            "text_extract_ok": None,
            "extractor": None,
            "error_message": None,
        }
        # 저장 경로가 없으면 파일 누락 플래그를 단다.
        if not saved_path_value:
            # 저장 경로가 없으면 수집 실패로 본다.
            flags.append("missing_saved_path")
            # 전처리 입력으로 사용할 수 없으므로 excluded다.
            status = promote_status(status, "excluded")
            # Path 객체는 만들 수 없으므로 None으로 둔다.
            path = None
        else:
            # 저장 경로를 Path 객체로 변환한다.
            path = Path(saved_path_value)
            # 파일 존재 여부를 확인한다.
            if not path.exists():
                # 파일이 실제로 없으면 플래그를 단다.
                flags.append("file_not_found")
                # 전처리 입력으로 사용할 수 없으므로 excluded다.
                status = promote_status(status, "excluded")
            # 파일이 존재하면 파일 검증을 계속한다.
            else:
                # 확장자가 pdf인지 확인한다.
                if path.suffix.lower() != ".pdf":
                    # 확장자가 pdf가 아니면 플래그를 단다.
                    flags.append("not_pdf_extension")
                    # 확장자 문제는 사람이 확인해야 하므로 review로 둔다.
                    status = promote_status(status, "review_required")
                # 파일 크기를 가져온다.
                size = get_file_size(path)
                # 파일 크기를 가져오지 못하면 플래그를 단다.
                if size is None:
                    # 크기 확인 실패를 기록한다.
                    flags.append("file_size_check_failed")
                    # 파일 상태 확인이 불완전하므로 review로 둔다.
                    status = promote_status(status, "review_required")
                # 파일 크기가 0이면 실패다.
                elif size <= 0:
                    # 0바이트 플래그를 단다.
                    flags.append("zero_byte_file")
                    # 전처리 입력으로 사용할 수 없으므로 excluded다.
                    status = promote_status(status, "excluded")
                # PDF 헤더인지 확인한다.
                if not looks_like_pdf(path):
                    # PDF 헤더가 아니면 HTML 오류 파일일 수 있다.
                    flags.append("invalid_pdf_header")
                    # PDF가 아니면 전처리 입력으로 위험하므로 excluded로 둔다.
                    status = promote_status(status, "excluded")
                # PDF 헤더가 맞으면 내부 열기 검증을 수행한다.
                else:
                    # PyMuPDF로 PDF를 열고 샘플 텍스트를 추출한다.
                    pdf_diag = extract_pdf_sample(path)
                    # PyMuPDF가 설치되어 있지 않으면 내부 검증을 완료하지 못한다.
                    if pdf_diag.get("extractor") == "pymupdf_not_installed":
                        # 설치 누락 플래그를 단다.
                        flags.append("pymupdf_not_installed")
                        # 내부 검증을 못 했으므로 review로 둔다.
                        status = promote_status(status, "review_required")
                    # PDF 열기가 실패하면 제외한다.
                    elif pdf_diag.get("pdf_open_ok") is False:
                        # PDF 열기 실패 플래그를 단다.
                        flags.append("pdf_open_failed")
                        # 깨진 PDF일 가능성이 높으므로 excluded다.
                        status = promote_status(status, "excluded")
                    # 페이지 수가 없거나 1보다 작으면 제외한다.
                    elif not pdf_diag.get("page_count"):
                        # 페이지 수 이상 플래그를 단다.
                        flags.append("invalid_page_count")
                        # 전처리 입력으로 사용할 수 없으므로 excluded다.
                        status = promote_status(status, "excluded")
                    # 텍스트 추출 결과가 비어 있으면 review로 둔다.
                    elif not pdf_diag.get("text_extract_ok"):
                        # 텍스트 추출 실패 플래그를 단다.
                        flags.append("empty_pdf_sample_text")
                        # 스캔 PDF이거나 추출기 문제일 수 있으므로 review다.
                        status = promote_status(status, "review_required")
        # source_reliability_score가 4인지 확인한다.
        if row.get("source_reliability_score") != SOURCE_RELIABILITY_SCORE:
            # 신뢰도 점수 오류 플래그를 단다.
            flags.append("invalid_source_reliability_score")
            # 점수 오류는 수정 필요하므로 review로 둔다.
            status = promote_status(status, "review_required")
        # manifest의 문서유형 후보를 가져온다.
        manifest_document_type = row.get("document_type_candidate")
        # 문서유형 후보가 있는지 확인한다.
        if not manifest_document_type:
            # 문서유형이 없으면 플래그를 단다.
            flags.append("unknown_document_type_candidate")
            # 문서유형 미확정은 review가 맞다.
            status = promote_status(status, "review_required")
        # PDF 샘플 텍스트가 있으면 내부 문서유형을 다시 판정한다.
        sample_detection = detect_document_type_from_pdf_sample(row, pdf_diag.get("sample_text") or "")
        # PDF 샘플 기준 문서유형 후보를 가져온다.
        sample_document_type = sample_detection.get("document_type_candidate")
        # PDF 내부에서도 문서유형이 잡히지 않으면 review로 둔다.
        if not sample_document_type:
            # 내부 문서유형 미확정 플래그를 단다.
            flags.append("sample_document_type_unknown")
            # 사람이 확인해야 하므로 review로 둔다.
            status = promote_status(status, "review_required")
        # manifest 문서유형과 내부 문서유형이 서로 다르면 review로 둔다.
        elif manifest_document_type and sample_document_type != manifest_document_type:
            # 문서유형 불일치 플래그를 단다.
            flags.append("document_type_mismatch_manifest_vs_pdf_sample")
            # 문서유형이 뒤집히면 parser 라우팅이 틀어지므로 review다.
            status = promote_status(status, "review_required")
        # sha256을 가져온다.
        sha = row.get("sha256")
        # sha가 없으면 플래그를 단다.
        if not sha:
            # 해시가 없으면 중복/개정 감지가 어렵다.
            flags.append("missing_sha256")
            # review로 둔다.
            status = promote_status(status, "review_required")
        # sha가 이미 등장했다면 중복이다.
        elif sha in seen_hashes:
            # 중복 해시 플래그를 단다.
            flags.append("duplicate_sha256")
            # 제외가 아니라 중복 상태로 둔다.
            status = promote_status(status, "duplicate")
        else:
            # 처음 본 해시를 set에 추가한다.
            seen_hashes.add(sha)
        # 리포트 row를 만든다.
        report = {
            # 수집 ID를 기록한다.
            "collection_id": row.get("collection_id"),
            # manifest 기준 문서유형을 기록한다.
            "document_type_candidate": manifest_document_type,
            # PDF 샘플 기준 문서유형을 기록한다.
            "sample_document_type_candidate": sample_document_type,
            # PDF 샘플 기준 문서유형 신뢰도를 기록한다.
            "sample_document_type_confidence": sample_detection.get("document_type_confidence"),
            # 저장 경로를 기록한다.
            "saved_path": row.get("saved_path"),
            # SHA256을 기록한다.
            "sha256": row.get("sha256"),
            # 파일 크기를 기록한다.
            "file_size": row.get("file_size"),
            # PDF 열기 성공 여부를 기록한다.
            "pdf_open_ok": pdf_diag.get("pdf_open_ok"),
            # PDF 페이지 수를 기록한다.
            "page_count": pdf_diag.get("page_count"),
            # PDF 샘플 텍스트 길이를 기록한다.
            "sample_text_length": pdf_diag.get("sample_text_length"),
            # 텍스트 추출 성공 여부를 기록한다.
            "text_extract_ok": pdf_diag.get("text_extract_ok"),
            # 검증 상태를 기록한다.
            "status": status,
            # 품질 플래그를 기록한다.
            "quality_flags": flags,
            # 신뢰도 점수를 기록한다.
            "source_reliability_score": row.get("source_reliability_score"),
            # PDF 내부 검증 오류 메시지를 기록한다.
            "error_message": pdf_diag.get("error_message"),
        }
        # 리포트 목록에 추가한다.
        reports.append(report)
    # 검증 리포트를 JSONL로 저장한다.
    write_jsonl(config.quality_report_path, reports)
    # 검증 결과를 반환한다.
    return reports
