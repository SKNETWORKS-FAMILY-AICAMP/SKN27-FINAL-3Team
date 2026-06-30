"""Integration tests: 서식문서 PDF → fine_notice_analysis graph

실제 GPT-4o Vision을 호출하는 통합 테스트입니다.
빈 양식(서식)을 입력하므로 fine_type / notice_stage 분류만 검증하고,
필드 미입력으로 인한 partial/degraded ocr_status는 정상으로 허용합니다.

실행:
    OPENAI_API_KEY=sk-... pytest test/test_fine_notice_ocr.py -v -s
"""
import base64
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).parents[1]
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT))

# 의존성 누락 시 수집 단계 오류 방지 — import 실패는 skip으로 처리
try:
    from ai.agents.fine_notice_analysis.graph import graph  # noqa: E402
    _GRAPH_AVAILABLE = True
except ImportError as _exc:  # noqa: F841
    graph = None  # type: ignore[assignment]
    _GRAPH_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY") or not _GRAPH_AVAILABLE,
    reason="OPENAI_API_KEY not set or 의존성 누락 — 통합 테스트 건너뜀",
)

FORMS_DIR = ROOT / "서식문서"

# (pdf 파일명, 기대 fine_type, 기대 notice_stage)
# notice_stage: 빈 서식 제목에서 GPT가 추론 가능한 값
CASES = [
    (
        "[별지 제151호서식] 과태료납부고지서 및 영수증(납부자용)(도로교통법 시행규칙).pdf",
        "과태료", "1차 고지서",
    ),
    (
        "[별지 제152호서식] 과태료 납부고지서 원부(운전자)(도로교통법 시행규칙).pdf",
        "과태료", "1차 고지서",
    ),
    (
        "[별지 제154호서식] 위반사실 통지 및 과태료부과 사전통지서(도로교통법 시행규칙).pdf",
        "과태료", "사전통지",
    ),
    (
        "[별지 제155호의2서식] 과태료부과 사전통지서(도로교통법 시행규칙) (1).pdf",
        "과태료", "사전통지",
    ),
    (
        "[별지 제159호의2서식] 범칙금 납부통고서(도로교통법 시행규칙) (1).pdf",
        "범칙금", "사전통지",
    ),
    (
        "[별지 제162호서식] 범칙금납부고지서(운전자)(도로교통법 시행규칙).pdf",
        "범칙금", "사전통지",
    ),
    (
        "[별지 제163호서식] 범칙금납부고지서(보행자 등)(도로교통법 시행규칙).pdf",
        "범칙금", "사전통지",
    ),
    (
        "[별지 제168호서식] 즉결심판출석통지서(도로교통법 시행규칙).pdf",
        "범칙금", "즉결심판",
    ),
]

CASE_IDS = [
    "151-과태료납부고지서",
    "152-과태료납부고지서원부",
    "154-과태료사전통지서",
    "155-과태료사전통지서2",
    "159-범칙금납부통고서",
    "162-범칙금납부고지서-운전자",
    "163-범칙금납부고지서-보행자",
    "168-즉결심판출석통지서",
]

VALID_OCR_STATUSES = {"success", "degraded", "partial"}


def _load_pdf_as_b64(filename: str) -> str:
    path = FORMS_DIR / filename
    return base64.b64encode(path.read_bytes()).decode()


@pytest.mark.parametrize("filename,expected_fine_type,expected_notice_stage", CASES, ids=CASE_IDS)
def test_ocr_classifies_fine_type_and_stage(filename, expected_fine_type, expected_notice_stage):
    """fine_type·notice_stage 분류가 서식 제목과 일치하는지 확인."""
    notice_image = _load_pdf_as_b64(filename)

    result = graph.invoke({
        "notice_image": notice_image,
        "notice_mime_type": "application/pdf",
    })

    # 디버그 출력 (-s 옵션으로 확인)
    print(f"\n[{filename[:30]}...]")
    print(f"  ocr_status  : {result.get('ocr_status')}")
    print(f"  fine_type   : {result.get('fine_type')}")
    print(f"  notice_stage: {result.get('notice_stage')}")
    print(f"  missing     : {result.get('missing_fields')}")
    print(f"  format_err  : {result.get('format_errors')}")

    ocr_status = result.get("ocr_status")

    # PDF 변환·GPT 호출 자체는 성공해야 함 (failed / rejected 는 오류)
    assert ocr_status in VALID_OCR_STATUSES, (
        f"ocr_status='{ocr_status}' — PDF 변환 또는 GPT 호출 실패. "
        f"ocr_error: {result.get('ocr_error')}"
    )

    assert result.get("fine_type") == expected_fine_type, (
        f"fine_type 불일치: got '{result.get('fine_type')}', expected '{expected_fine_type}'"
    )

    assert result.get("notice_stage") == expected_notice_stage, (
        f"notice_stage 불일치: got '{result.get('notice_stage')}', expected '{expected_notice_stage}'"
    )


_EXPECTED_NEXT_ACTIONS = {
    "과태료": "법률 근거 검색 노드 호출",
    "범칙금": "OCR 결과만 반환 — 이의신청 불가",
}


@pytest.mark.parametrize("filename,expected_fine_type,expected_notice_stage", CASES, ids=CASE_IDS)
def test_ocr_agent_result_envelope_present(filename, expected_fine_type, expected_notice_stage):
    """agent_results 봉투 구조 및 next_actions 확인."""
    notice_image = _load_pdf_as_b64(filename)

    result = graph.invoke({
        "notice_image": notice_image,
        "notice_mime_type": "application/pdf",
    })

    ocr_status = result.get("ocr_status")
    envelope = result.get("agent_results", {}).get("fine_notice_analysis", {})

    assert envelope, "agent_results.fine_notice_analysis 봉투 없음"
    assert isinstance(envelope.get("missing_fields"), list)

    # partial: ocr_node에서 즉시 반환 — confidence_verification 미통과
    if ocr_status == "partial":
        assert envelope.get("status") == "partial"
        assert "이미지 재업로드 요청" in (envelope.get("next_actions") or [])
        return

    # success / degraded: confidence_verification_node 통과
    assert envelope.get("status") in ("success", "degraded", "partial")
    assert "structured_result" in envelope

    # success 시 fine_type별 next_actions 검증 (ENV_OK_KT vs ENV_OK_BJ)
    if ocr_status == "success":
        expected_action = _EXPECTED_NEXT_ACTIONS[expected_fine_type]
        assert expected_action in (envelope.get("next_actions") or []), (
            f"next_actions 불일치: got {envelope.get('next_actions')}, "
            f"expected '{expected_action}' for fine_type='{expected_fine_type}'"
        )


def test_ocr_rejects_missing_image():
    """이미지 없을 때 failed 반환 확인 (GPT 호출 불필요)."""
    result = graph.invoke({"notice_image": None, "notice_mime_type": "application/pdf"})
    assert result["ocr_status"] == "failed"
    assert result["ocr_error"] == "이미지 없음"


def test_ocr_rejects_invalid_base64_pdf():
    """잘못된 base64 (PDF) → failed envelope 반환 (GPT 호출 불필요)."""
    result = graph.invoke({"notice_image": "!!!invalid-base64!!!", "notice_mime_type": "application/pdf"})
    assert result["ocr_status"] == "failed"
    assert "재업로드" in (result.get("ocr_error") or "")
    envelope = result.get("agent_results", {}).get("fine_notice_analysis", {})
    assert "이미지 재업로드 요청" in (envelope.get("next_actions") or [])


def test_ocr_rejects_invalid_base64_jpeg():
    """잘못된 base64 (JPEG) → failed envelope 반환 (GPT 호출 불필요)."""
    result = graph.invoke({"notice_image": "!!!invalid-base64!!!", "notice_mime_type": "image/jpeg"})
    assert result["ocr_status"] == "failed"
    assert "재업로드" in (result.get("ocr_error") or "")
    envelope = result.get("agent_results", {}).get("fine_notice_analysis", {})
    assert "이미지 재업로드 요청" in (envelope.get("next_actions") or [])


def test_ocr_rejects_corrupted_pdf():
    """손상된 PDF 바이트 → failed envelope 반환 (GPT 호출 불필요)."""
    import base64 as _b64
    bad_pdf = _b64.b64encode(b"not a real pdf content").decode()
    result = graph.invoke({"notice_image": bad_pdf, "notice_mime_type": "application/pdf"})
    assert result["ocr_status"] == "failed"
    assert "재업로드" in (result.get("ocr_error") or "")
    envelope = result.get("agent_results", {}).get("fine_notice_analysis", {})
    assert "이미지 재업로드 요청" in (envelope.get("next_actions") or [])
