import base64
import datetime
import json
import re
from typing import Optional

import fitz        # pymupdf
import openai

from .evaluator import evaluate_ocr
from .masking import mask_field, mask_personal_info
from .prompts import NOTICE_EXTRACTION_PROMPT
from .state import FineNoticeState
from .utils import make_envelope, update_agent_results

_ALLOWED_FLAT_FIELDS = {
    "ocr_status", "ocr_error", "fine_type", "notice_stage",
    "law_code", "violation_text", "violation_datetime", "violation_location",
    "fine_amount", "prepayment_amount", "opinion_deadline", "payment_deadline_2nd",
    "additional_amount", "issuing_authority", "vehicle_number",
    "demerit_points_base", "demerit_points_accumulated", "charge_number",
    "court_venue", "missing_fields",
}


# ── 내부 유틸 ──────────────────────────────────────────────────────────────────

def _pdf_to_images(pdf_bytes: bytes) -> list[tuple[str, str]]:
    """PDF → [(base64, mime)] 리스트. 10페이지 초과 시 ValueError (R-08)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if len(doc) > 10:
        raise ValueError("PDF 페이지 초과")
    pages = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        b64 = base64.b64encode(pix.tobytes("png")).decode()
        pages.append((b64, "image/png"))
    return pages


def _build_image_blocks(pages: list[tuple[str, str]]) -> list[dict]:
    """(base64, mime_type) → GPT image_url 블록 리스트."""
    return [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
        for b64, mime in pages
    ]


def _classify_fine_type(title: str, authority: str, has_demerit: bool) -> Optional[str]:
    """우선순위 7단계 키워드 매칭. 미매칭 시 None."""
    t, a = title or "", authority or ""
    if "즉결심판" in t and "과태료" not in t:  return "범칙금"  # P-0
    if "검찰" in a:                             return "벌금"    # P-1
    if "약식명령" in t or "벌과금" in t:        return "벌금"    # P-2
    if "범칙금" in t:                           return "범칙금"  # P-3
    if "과태료" in t:                           return "과태료"  # P-4
    if has_demerit:                             return "범칙금"  # P-5
    if any(kw in a for kw in ("구청", "시청")): return "과태료"  # P-6
    return None


def _parse_date(value) -> Optional[str]:
    """날짜 파싱 → YYYY-MM-DD. 실패 시 None (R-04)."""
    if not value:
        return None
    try:
        s = str(value)[:10]
        datetime.date.fromisoformat(s)
        return s
    except (ValueError, TypeError):
        return None


def _call_gpt(image_blocks: list[dict]) -> dict:
    """GPT-4o Vision 호출 → R-11 마스킹 → JSON 파싱."""
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [{"type": "text", "text": NOTICE_EXTRACTION_PROMPT}] + image_blocks,
        }],
    )
    raw = response.choices[0].message.content.strip()
    raw = mask_personal_info(raw)   # R-11: JSON 파싱 전 즉시 마스킹
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise


# ── ocr_node ──────────────────────────────────────────────────────────────────

def ocr_node(state: FineNoticeState) -> dict:
    notice_image     = state.get("notice_image")
    notice_mime_type = state.get("notice_mime_type") or "image/jpeg"

    # ── 이미지 없음 ────────────────────────────────────────────────────
    if not notice_image:
        structured = {"ocr_status": "failed", "ocr_error": "이미지 없음"}
        env = make_envelope("failed", structured, [], ["이미지 재업로드 요청"])
        return {
            "ocr_status":    "failed",
            "ocr_error":     "이미지 없음",
            "notice_image":  None,
            "agent_results": update_agent_results(state, env),
        }

    # ── base64 디코딩 ─────────────────────────────────────────────────
    try:
        raw_bytes = base64.b64decode(notice_image)
    except Exception:
        err = "이미지 디코딩 실패 — 올바른 파일을 다시 업로드해 주세요."
        env = make_envelope("failed", {"ocr_status": "failed", "ocr_error": err}, [], ["이미지 재업로드 요청"])
        return {"ocr_status": "failed", "ocr_error": err, "notice_image": None,
                "agent_results": update_agent_results(state, env)}

    # ── PDF 변환 ───────────────────────────────────────────────────────
    if notice_mime_type == "application/pdf":
        try:
            pages = _pdf_to_images(raw_bytes)
        except ValueError:
            err = "PDF 페이지 초과"
            env = make_envelope("failed", {"ocr_status": "failed", "ocr_error": err}, [], ["이미지 재업로드 요청"])
            return {"ocr_status": "failed", "ocr_error": err, "notice_image": None,
                    "agent_results": update_agent_results(state, env)}
        except Exception:
            err = "PDF 파일이 손상되었습니다. 다시 업로드해 주세요."
            env = make_envelope("failed", {"ocr_status": "failed", "ocr_error": err}, [], ["이미지 재업로드 요청"])
            return {"ocr_status": "failed", "ocr_error": err, "notice_image": None,
                    "agent_results": update_agent_results(state, env)}
        if not pages:
            err = "PDF 변환 결과 페이지 없음"
            env = make_envelope("failed", {"ocr_status": "failed", "ocr_error": err}, [], ["이미지 재업로드 요청"])
            return {"ocr_status": "failed", "ocr_error": err, "notice_image": None,
                    "agent_results": update_agent_results(state, env)}
        image_blocks = _build_image_blocks(pages)
    else:
        image_blocks = _build_image_blocks([(notice_image, notice_mime_type)])

    # ── GPT 호출 ───────────────────────────────────────────────────────
    try:
        result = _call_gpt(image_blocks)
    except Exception:
        err = "GPT 응답 파싱 실패"
        env = make_envelope("failed", {"ocr_status": "failed", "ocr_error": err}, [], ["이미지 재업로드 요청"])
        return {"ocr_status": "failed", "ocr_error": err, "notice_image": None,
                "agent_results": update_agent_results(state, env)}

    # ── fine_type 분류 ────────────────────────────────────────────────
    fine_type = _classify_fine_type(
        result.get("document_title", ""),
        result.get("issuing_authority", ""),
        bool(result.get("demerit_points_base")),
    )
    if fine_type in (None, "벌금"):
        reason = (
            "벌금(형사처벌)은 서비스 범위 외입니다."
            if fine_type == "벌금"
            else "고지서를 인식할 수 없습니다. 과태료 또는 범칙금 고지서 이미지를 다시 업로드해 주세요."
        )
        structured = {"ocr_status": "rejected", "ocr_error": reason, "fine_type": fine_type}
        env = make_envelope("rejected", structured, [], ["서비스 범위 외 안내"])
        return {"ocr_status": "rejected", "fine_type": fine_type, "notice_image": None,
                "agent_results": update_agent_results(state, env)}

    # ── 이중 마스킹 (R-11 코드 레벨) ─────────────────────────────────
    result["vehicle_number"] = mask_field(result.get("vehicle_number"))

    # ── 날짜 파싱 (R-04) ──────────────────────────────────────────────
    result["opinion_deadline"]     = _parse_date(result.get("opinion_deadline"))
    result["payment_deadline_2nd"] = _parse_date(result.get("payment_deadline_2nd"))

    notice_stage = result.get("notice_stage")

    # ── evaluate_ocr ──────────────────────────────────────────────────
    ocr_status, missing_fields = evaluate_ocr(result, fine_type, notice_stage)

    # ── flat dict 조립 (R-03) ─────────────────────────────────────────
    flat: dict = {k: result.get(k) for k in _ALLOWED_FLAT_FIELDS}
    flat["fine_type"]      = fine_type
    flat["notice_stage"]   = notice_stage
    flat["ocr_status"]     = ocr_status
    flat["ocr_error"]      = result.get("ocr_error")   # R-03: 성공 시 None
    flat["missing_fields"] = missing_fields

    # ── partial 즉시 반환 ─────────────────────────────────────────────
    if ocr_status == "partial":
        summary = f"{fine_type} {notice_stage or ''} OCR partial — critical 필드 누락"
        env = make_envelope("partial", flat, missing_fields, ["이미지 재업로드 요청"], summary)
        return {**flat, "notice_image": None, "agent_results": update_agent_results(state, env)}

    return {**flat, "notice_image": None}
