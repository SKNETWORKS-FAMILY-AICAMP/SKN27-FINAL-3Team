"""Unit tests: evaluate_ocr() 및 confidence_verification_node — GPT 호출 없음"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from ai.agents.fine_notice_analysis.evaluator import evaluate_ocr
from ai.agents.fine_notice_analysis.verification import confidence_verification_node

# ── evaluate_ocr ────────────────────────────────────────────────────────────

class TestEvaluateOcr:
    def test_success_과태료_all_fields(self):
        fields = {
            "law_code": "도로교통법 제32조",
            "violation_text": "주정차 위반",
            "notice_stage": "1차 고지서",
            "fine_amount": 120000,
            "opinion_deadline": "2026-06-25",
            "issuing_authority": "서울경찰청",
            "charge_number": "2026-001",
        }
        status, missing = evaluate_ocr(fields, "과태료", "1차 고지서")
        assert status == "success"
        assert missing == []

    def test_success_범칙금_all_fields(self):
        fields = {
            "law_code": "도로교통법 제5조",
            "violation_text": "신호위반",
            "notice_stage": "사전통지",
            "fine_amount": 60000,
            "opinion_deadline": "2026-06-25",
            "vehicle_number": "12가3456",
            "violation_datetime": "2026-06-01 10:00",
            "violation_location": "서울시 강남구",
        }
        status, missing = evaluate_ocr(fields, "범칙금", "사전통지")
        assert status == "success"
        assert missing == []

    def test_partial_missing_critical(self):
        # critical 필드(law_code) 누락 → partial
        fields = {"violation_text": "신호위반", "notice_stage": "1차 고지서"}
        status, missing = evaluate_ocr(fields, "과태료", "1차 고지서")
        assert status == "partial"
        assert "law_code" in missing

    def test_degraded_missing_important_only(self):
        # critical 필드 있고 important(fine_amount) 누락 → degraded
        fields = {
            "law_code": "도로교통법 제32조",
            "violation_text": "주정차 위반",
            "notice_stage": "1차 고지서",
            "issuing_authority": "서울경찰청",
            "charge_number": "2026-001",
        }
        status, missing = evaluate_ocr(fields, "과태료", "1차 고지서")
        assert status == "degraded"
        assert "fine_amount" in missing

    def test_즉결심판_structural_absent(self):
        # ④ 즉결심판: law_code·vehicle_number 없어도 success 가능
        fields = {
            "violation_text": "신호위반",
            "notice_stage": "즉결심판",
            "fine_amount": 60000,
            "opinion_deadline": "2026-06-25",
            "violation_datetime": "2026-06-01",
            "violation_location": "서울시",
        }
        status, _ = evaluate_ocr(fields, "범칙금", "즉결심판")
        assert status in ("success", "degraded")

    def test_empty_fields_returns_partial(self):
        status, missing = evaluate_ocr({}, "과태료", "1차 고지서")
        assert status == "partial"
        assert len(missing) > 0

    def test_unknown_fine_type_returns_success_no_fields(self):
        # 알 수 없는 fine_type → critical/important 필드 없음 → success
        status, missing = evaluate_ocr({}, "벌금", None)
        assert status == "success"
        assert missing == []


# ── confidence_verification_node ────────────────────────────────────────────

def _make_state(**kwargs) -> dict:
    base = {
        "notice_image": "dummy",
        "notice_mime_type": "application/pdf",
        "fine_type": "과태료",
        "notice_stage": "1차 고지서",
        "law_code": "도로교통법 제32조",
        "violation_text": "주정차 위반",
        "fine_amount": 120000,
        "ocr_status": "success",
        "missing_fields": [],
        "format_errors": [],
        "agent_results": {},
    }
    base.update(kwargs)
    return base


class TestConfidenceVerificationNode:
    def test_과태료_success_next_action(self):
        state = _make_state(fine_type="과태료", notice_stage="1차 고지서", ocr_status="success")
        result = confidence_verification_node(state)
        env = result["agent_results"]["fine_notice_analysis"]
        assert "법률 근거 검색 노드 호출 (승인 후)" in env["next_actions"]

    def test_범칙금_success_next_action(self):
        state = _make_state(fine_type="범칙금", notice_stage="사전통지", ocr_status="success")
        result = confidence_verification_node(state)
        env = result["agent_results"]["fine_notice_analysis"]
        assert "OCR 결과만 반환 — 이의신청 불가" in env["next_actions"]

    def test_invalid_combination_forces_partial(self):
        # (과태료, 즉결심판) → VALID_COMBINATIONS 밖 → format_errors → partial
        state = _make_state(fine_type="과태료", notice_stage="즉결심판", ocr_status="success")
        result = confidence_verification_node(state)
        assert result["ocr_status"] == "partial"
        assert "이미지 재업로드 요청" in result["agent_results"]["fine_notice_analysis"]["next_actions"]

    def test_negative_fine_amount_forces_partial(self):
        state = _make_state(fine_amount=-1, ocr_status="success")
        result = confidence_verification_node(state)
        assert result["ocr_status"] == "partial"
        assert any("fine_amount" in e for e in result["format_errors"])

    def test_invalid_law_code_format_forces_partial(self):
        state = _make_state(law_code="잘못된형식", ocr_status="success")
        result = confidence_verification_node(state)
        assert result["ocr_status"] == "partial"

    def test_degraded_status_routes_to_reupload(self):
        state = _make_state(ocr_status="degraded")
        result = confidence_verification_node(state)
        env = result["agent_results"]["fine_notice_analysis"]
        assert "이미지 재업로드 요청" in env["next_actions"]

    def test_envelope_always_present(self):
        state = _make_state()
        result = confidence_verification_node(state)
        env = result["agent_results"].get("fine_notice_analysis")
        assert env is not None
        assert "status" in env
        assert "next_actions" in env
        assert "structured_result" in env
        assert isinstance(env["missing_fields"], list)

    def test_structured_result_carries_confirmation_fields(self):
        # requires_confirmation/unconfirmed_fields는 Supervisor 경계를 넘는
        # structured_result(envelope)에도 실려야 한다 — top-level 반환값에만
        # 남으면 appeal_decision_flow 등 다른 에이전트가 이 값을 못 받는다.
        state = _make_state(fine_type="과태료", notice_stage="1차 고지서", ocr_status="success")
        result = confidence_verification_node(state)
        structured = result["agent_results"]["fine_notice_analysis"]["structured_result"]
        assert structured["requires_confirmation"] == result["requires_confirmation"]
        assert structured["unconfirmed_fields"] == result["unconfirmed_fields"]

    def test_unconfirmed_fields_lists_missing_critical_fields(self):
        state = _make_state(
            ocr_status="degraded",
            missing_fields=["fine_amount", "opinion_deadline"],
        )
        result = confidence_verification_node(state)
        assert result["unconfirmed_fields"] == ["fine_amount", "opinion_deadline"]
        assert result["requires_confirmation"] is True
