"""Unit tests: appeal_decision_flow 노드 함수 — GPT 호출은 목(mock) 처리

설계문서 참고:
    01_아키텍처_설계서.md §3, §9  (노드 구성·순서 수정 근거)
    02_데이터모델_설계서.md §5, §6, §8  (MG 매핑표, 기한 계산, RG 분류 규칙)
    이의가능성_판단_에이전트_설계정리.md v19~v22 (도난 예외, 순서 수정, notice_received_date 완화)
"""
import datetime
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from ai.agents.appeal_decision_flow.deadline import deadline_gate_node
from ai.agents.appeal_decision_flow.guide import guide_generation_node
from ai.agents.appeal_decision_flow.law_code_check import law_code_check_node
from ai.agents.appeal_decision_flow.law_refs import get_merit_context, is_parking_violation
from ai.agents.appeal_decision_flow.merit_gate import merit_classification_node
from ai.agents.appeal_decision_flow.reason_intake import reason_intake_node
from ai.agents.appeal_decision_flow.risk_gate import risk_classification_node
from ai.agents.appeal_decision_flow.verdict import verdict_node

TODAY = datetime.date.today()


def _iso(days_from_today: int) -> str:
    return (TODAY + datetime.timedelta(days=days_from_today)).isoformat()


def _fake_llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


def _patch_openai(content: str):
    """openai.OpenAI() 호출을 목 처리해 주어진 content를 반환하도록 한다."""
    patcher = patch("openai.OpenAI")
    mock_client_cls = patcher.start()
    mock_client_cls.return_value.chat.completions.create.return_value = _fake_llm_response(content)
    return patcher


# ── deadline_gate_node (DATA-003 §6, ARCH-001 §9-7) ─────────────────────────

class TestDeadlineGateNode:
    def test_사전통지는_opinion_deadline_그대로_사용(self):
        state = {"notice_stage": "사전통지", "opinion_deadline": _iso(5)}
        result = deadline_gate_node(state)
        assert result["computed_deadline"] == _iso(5)
        assert result["deadline_passed"] is False

    def test_1차고지서는_수령일_60일_계산(self):
        state = {"notice_stage": "1차 고지서", "notice_received_date": _iso(-10)}
        result = deadline_gate_node(state)
        expected = (TODAY - datetime.timedelta(days=10) + datetime.timedelta(days=60)).isoformat()
        assert result["computed_deadline"] == expected

    def test_핵심함정_인쇄기한과_법정기한이_다르면_법정기한을_따른다(self):
        """opinion_deadline(인쇄된 납부기한)이 이미 지났어도, 수령일+60일 법정
        기한이 안 지났으면 deadline_passed=False 여야 한다."""
        state = {
            "notice_stage": "1차 고지서",
            "opinion_deadline": _iso(-5),          # 인쇄된 납부기한: 이미 지남
            "notice_received_date": _iso(-10),      # 수령일 10일 전 → 법정기한은 50일 남음
        }
        result = deadline_gate_node(state)
        assert result["deadline_passed"] is False
        assert result["computed_deadline"] != state["opinion_deadline"]

    def test_1차고지서_법정기한_60일_초과시_경과(self):
        state = {"notice_stage": "1차 고지서", "notice_received_date": _iso(-65)}
        result = deadline_gate_node(state)
        assert result["deadline_passed"] is True

    def test_기한_당일이면_아직_미경과(self):
        state = {"notice_stage": "사전통지", "opinion_deadline": TODAY.isoformat()}
        result = deadline_gate_node(state)
        assert result["deadline_passed"] is False

    def test_1차고지서_수령일_없으면_방어적_None(self):
        state = {"notice_stage": "1차 고지서", "notice_received_date": None}
        result = deadline_gate_node(state)
        assert result == {"computed_deadline": None, "deadline_passed": None}

    def test_사전통지_opinion_deadline_없으면_방어적_None(self):
        state = {"notice_stage": "사전통지", "opinion_deadline": None}
        result = deadline_gate_node(state)
        assert result == {"computed_deadline": None, "deadline_passed": None}

    def test_잘못된_날짜형식은_방어적_None(self):
        state = {"notice_stage": "사전통지", "opinion_deadline": "이건 날짜가 아님"}
        result = deadline_gate_node(state)
        assert result == {"computed_deadline": None, "deadline_passed": None}


# ── law_code_check_node (MVP 스텁, ARCH-001 §9-1) ───────────────────────────

class TestLawCodeCheckNode:
    @pytest.mark.parametrize("law_code", ["도로교통법 제17조 제1항", None, ""])
    def test_항상_True_스텁(self, law_code):
        result = law_code_check_node({"law_code": law_code})
        assert result == {"law_code_verified": True}


# ── reason_intake_node (ARCH-001 §9-7) ──────────────────────────────────────

class TestReasonIntakeNode:
    def test_사전통지_사유있으면_통과(self):
        state = {"notice_stage": "사전통지", "user_appeal_reason": "표지판이 안 보였습니다"}
        assert reason_intake_node(state) == {}

    def test_사전통지_사유없으면_input_required(self):
        state = {"notice_stage": "사전통지", "user_appeal_reason": None, "fine_type": "과태료"}
        result = reason_intake_node(state)
        assert result["judgment_status"] == "input_required"
        env = result["agent_results"]["appeal_judgment"]
        assert "user_appeal_reason" in env["missing_fields"]
        assert "notice_received_date" not in env["missing_fields"]

    def test_사전통지_공백사유는_누락으로_처리(self):
        state = {"notice_stage": "사전통지", "user_appeal_reason": "   ", "fine_type": "과태료"}
        result = reason_intake_node(state)
        assert result["judgment_status"] == "input_required"

    def test_사전통지_input_required에_computed_deadline_포함(self):
        """사전통지는 deadline_gate_node가 이미 실행된 뒤라 partial_result에
        computed_deadline·law_code_verified를 함께 실을 수 있어야 한다."""
        state = {
            "notice_stage": "사전통지", "fine_type": "과태료", "user_appeal_reason": None,
            "computed_deadline": _iso(5), "deadline_passed": False, "law_code_verified": True,
        }
        result = reason_intake_node(state)
        partial = result["agent_results"]["appeal_judgment"]["structured_result"]
        assert partial["computed_deadline"] == _iso(5)
        assert partial["law_code_verified"] is True

    def test_1차고지서_사유수령일_둘다있으면_통과(self):
        state = {
            "notice_stage": "1차 고지서",
            "user_appeal_reason": "표지판이 안 보였습니다",
            "notice_received_date": _iso(-10),
        }
        assert reason_intake_node(state) == {}

    def test_1차고지서_사유만있고_수령일없어도_통과(self):
        """(v22) notice_received_date는 선택 필드 — 사유만 있으면 수령일이
        없어도 재질문하지 않고 통과시킨다."""
        state = {
            "notice_stage": "1차 고지서",
            "user_appeal_reason": "표지판이 안 보였습니다",
            "notice_received_date": None,
        }
        assert reason_intake_node(state) == {}

    @pytest.mark.parametrize(
        "reason,received,expected_missing",
        [
            (None, None, {"user_appeal_reason", "notice_received_date"}),
            (None, "2026-05-01", {"user_appeal_reason"}),
        ],
    )
    def test_1차고지서_누락조합(self, reason, received, expected_missing):
        state = {
            "notice_stage": "1차 고지서", "fine_type": "과태료",
            "user_appeal_reason": reason, "notice_received_date": received,
        }
        result = reason_intake_node(state)
        env = result["agent_results"]["appeal_judgment"]
        assert set(env["missing_fields"]) == expected_missing

    def test_1차고지서_input_required에도_computed_deadline_포함(self):
        """(v22) deadline_gate_node가 notice_stage 무관하게 항상 먼저 실행되므로
        computed_deadline·law_code_verified는 1차 고지서의 input_required 응답에도
        이미 계산된 값으로 포함돼야 한다 (v20 시절의 예외는 되돌려짐)."""
        state = {
            "notice_stage": "1차 고지서", "fine_type": "과태료",
            "user_appeal_reason": None, "notice_received_date": None,
            "law_code_verified": True, "computed_deadline": None, "deadline_passed": None,
        }
        result = reason_intake_node(state)
        partial = result["agent_results"]["appeal_judgment"]["structured_result"]
        assert "computed_deadline" in partial
        assert partial["computed_deadline"] is None
        assert partial["law_code_verified"] is True

    def test_사전통지_안내문구는_의견제출(self):
        state = {"notice_stage": "사전통지", "user_appeal_reason": None, "fine_type": "과태료"}
        result = reason_intake_node(state)
        env = result["agent_results"]["appeal_judgment"]
        assert "의견제출" in env["next_actions"][0]
        assert "이의신청" not in env["next_actions"][0]

    def test_1차고지서_안내문구는_이의신청(self):
        state = {
            "notice_stage": "1차 고지서", "fine_type": "과태료",
            "user_appeal_reason": None, "notice_received_date": None,
        }
        result = reason_intake_node(state)
        env = result["agent_results"]["appeal_judgment"]
        assert "이의신청" in env["next_actions"][0]


# ── law_refs (DATA-003 §5, §9) ───────────────────────────────────────────────

class TestLawRefs:
    @pytest.mark.parametrize("law_code", [
        "도로교통법 제32조 제1항", "도로교통법 제33조", "도로교통법 제34조 제2항",
    ])
    def test_주정차_조항_판별_True(self, law_code):
        assert is_parking_violation(law_code) is True

    @pytest.mark.parametrize("law_code", [
        "도로교통법 제17조 제1항", "도로교통법 제5조", "도로교통법 제132조",
    ])
    def test_비주정차_조항_판별_False(self, law_code):
        assert is_parking_violation(law_code) is False

    def test_law_code_none이면_비주정차로_안전폴백(self):
        assert is_parking_violation(None) is False
        assert is_parking_violation("") is False

    def test_사전통지_주정차_컨텍스트(self):
        ctx = get_merit_context("사전통지", "도로교통법 제32조 제1항")
        assert "제160조제4항제1호" in ctx
        assert "시행규칙 제142조" in ctx
        assert "제14조" not in ctx
        assert "제7조" not in ctx

    def test_사전통지_비주정차_컨텍스트(self):
        ctx = get_merit_context("사전통지", "도로교통법 제17조 제1항")
        assert "질서위반행위규제법 제7조" in ctx
        assert "제142조" not in ctx
        assert "제14조" not in ctx

    def test_1차고지서_주정차_컨텍스트(self):
        ctx = get_merit_context("1차 고지서", "도로교통법 제32조 제1항")
        assert "제160조제4항제1호" in ctx
        assert "시행규칙 제142조" in ctx
        assert "질서위반행위규제법 제14조" in ctx

    def test_1차고지서_비주정차_컨텍스트(self):
        ctx = get_merit_context("1차 고지서", "도로교통법 제17조 제1항")
        assert "질서위반행위규제법 제7조" in ctx
        assert "질서위반행위규제법 제14조" in ctx
        assert "제142조" not in ctx


# ── risk_classification_node (DATA-003 §8) ──────────────────────────────────

class TestRiskClassificationNode:
    @pytest.mark.parametrize("reason", [
        "제 차를 도둑맞아서 도둑이 운전하다가 위반했습니다",
        "차가 도난당했었습니다",
        "누가 훔쳐서 몰고 나갔어요",
    ])
    def test_0단계_도난_키워드는_안전처리(self, reason):
        result = risk_classification_node({"user_appeal_reason": reason})
        assert result["risk_flag"] is False
        assert result["risk_stage_matched"] == "keyword"
        assert result["risk_trigger_category"] is None

    def test_1단계_카테고리A_제3자운전주장(self):
        result = risk_classification_node({"user_appeal_reason": "다른 사람이 운전했습니다"})
        assert result["risk_flag"] is True
        assert result["risk_trigger_category"] == "A_제3자운전주장"
        assert result["risk_stage_matched"] == "keyword"

    def test_1단계_카테고리B_명시적전환요청(self):
        result = risk_classification_node({"user_appeal_reason": "범칙금으로 전환해주세요"})
        assert result["risk_flag"] is True
        assert result["risk_trigger_category"] == "B_명시적전환요청"

    def test_1단계_카테고리C_본인운전인정형(self):
        result = risk_classification_node({"user_appeal_reason": "응급환자를 이송하다가 위반했습니다"})
        assert result["risk_flag"] is True
        assert result["risk_trigger_category"] == "C_본인운전인정형"

    def test_카테고리A가_C보다_우선(self):
        reason = "다른 사람이 운전했는데 응급환자를 이송하던 중이었습니다"
        result = risk_classification_node({"user_appeal_reason": reason})
        assert result["risk_trigger_category"] == "A_제3자운전주장"

    def test_2단계_LLM_category있으면_위험(self):
        patcher = _patch_openai('{"category": "A", "confidence": "high", "rationale": "x"}')
        try:
            result = risk_classification_node({"user_appeal_reason": "동생이 잠깐 몰고 나갔었습니다"})
            assert result["risk_flag"] is True
            assert result["risk_stage_matched"] == "llm"
            assert result["risk_trigger_category"] == "A_제3자운전주장"
        finally:
            patcher.stop()

    def test_2단계_LLM_category없으면_안전(self):
        patcher = _patch_openai('{"category": null, "confidence": "low", "rationale": "무관"}')
        try:
            result = risk_classification_node({"user_appeal_reason": "그냥 급해서 그랬습니다"})
            assert result["risk_flag"] is False
            assert result["risk_trigger_category"] is None
        finally:
            patcher.stop()

    def test_2단계_confidence_low면_안전(self):
        patcher = _patch_openai('{"category": "C", "confidence": "low", "rationale": "애매"}')
        try:
            result = risk_classification_node({"user_appeal_reason": "애매한 사유"})
            assert result["risk_flag"] is False
        finally:
            patcher.stop()

    def test_2단계_confidence_예상밖값이면_위험쪽폴백(self):
        """category가 있는데 confidence가 'low'가 아닌 이상한 값이면,
        재현율 우선 원칙에 따라 안전이 아니라 위험 쪽으로 처리해야 한다."""
        patcher = _patch_openai('{"category": "A", "confidence": "매우높음", "rationale": "이상함"}')
        try:
            result = risk_classification_node({"user_appeal_reason": "애매한 사유"})
            assert result["risk_flag"] is True
        finally:
            patcher.stop()

    def test_LLM_예외시_위험쪽으로_보수적_폴백(self):
        with patch("openai.OpenAI", side_effect=ConnectionError("네트워크 오류")):
            result = risk_classification_node({"user_appeal_reason": "애매한 사유"})
            assert result["risk_flag"] is True
            assert result["risk_confidence"] is None


# ── merit_classification_node (DATA-003 §5) ─────────────────────────────────

class TestMeritClassificationNode:
    def test_주정차_사전통지면_142조_컨텍스트로_LLM_호출(self):
        with patch("ai.agents.appeal_decision_flow.merit_gate._call_llm_merit") as mock_call:
            mock_call.return_value = {"merit": "강함", "merit_basis": "x"}
            merit_classification_node({
                "user_appeal_reason": "응급환자를 이송했습니다",
                "notice_stage": "사전통지", "law_code": "도로교통법 제32조",
            })
            called_context = mock_call.call_args[0][1]
            assert "시행규칙 제142조" in called_context

    def test_LLM_예외시_보류로_폴백(self):
        with patch("openai.OpenAI", side_effect=ConnectionError("네트워크 오류")):
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit"] == "보류"
            assert result["merit_basis"]

    def test_정의되지_않은_merit값은_보류로_정규화(self):
        patcher = _patch_openai('{"merit": "매우강함", "merit_basis": "이상한 응답"}')
        try:
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit"] == "보류"
        finally:
            patcher.stop()

    @pytest.mark.parametrize("merit_value", ["강함", "보류", "낮음"])
    def test_정의된_merit값은_그대로_통과(self, merit_value):
        patcher = _patch_openai(f'{{"merit": "{merit_value}", "merit_basis": "근거"}}')
        try:
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit"] == merit_value
        finally:
            patcher.stop()


# ── verdict_node (DATA-003 §4) ───────────────────────────────────────────────

class TestVerdictNode:
    def test_사전통지_라벨(self):
        result = verdict_node({"notice_stage": "사전통지"})
        assert result["overall_possibility"] == "의견_제출시_인정가능"
        assert result["judgment_status"] == "success"

    def test_1차고지서_라벨(self):
        result = verdict_node({"notice_stage": "1차 고지서"})
        assert result["overall_possibility"] == "이의제기_인용가능"


# ── guide_generation_node (API-004 §3) ───────────────────────────────────────

class TestGuideGenerationNode:
    def test_타임라인_과태료_1차고지서(self):
        state = {
            "fine_type": "과태료", "notice_stage": "1차 고지서",
            "opinion_deadline": _iso(-5), "computed_deadline": _iso(45),
            "judgment_status": "success",
        }
        result = guide_generation_node(state)
        assert "법정 이의제기 마감" in result["guide"]["timeline"]
        assert _iso(45) in result["guide"]["timeline"]

    def test_타임라인_과태료_사전통지(self):
        state = {
            "fine_type": "과태료", "notice_stage": "사전통지",
            "opinion_deadline": _iso(8), "judgment_status": "success",
        }
        result = guide_generation_node(state)
        assert "의견제출기한" in result["guide"]["timeline"]

    def test_타임라인_즉결심판(self):
        state = {
            "fine_type": "범칙금", "notice_stage": "즉결심판",
            "opinion_deadline": _iso(10), "judgment_status": "not_applicable",
        }
        result = guide_generation_node(state)
        assert "출석 예정일시" in result["guide"]["timeline"]

    def test_타임라인_범칙금_사전통지(self):
        state = {
            "fine_type": "범칙금", "notice_stage": "사전통지",
            "opinion_deadline": _iso(10), "payment_deadline_2nd": _iso(30),
            "judgment_status": "not_applicable",
        }
        result = guide_generation_node(state)
        assert "1차 납부기한" in result["guide"]["timeline"]
        assert "2차 납부기한" in result["guide"]["timeline"]

    def test_disclaimer_law_code_verified_true(self):
        state = {"law_code_verified": True, "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지"}
        result = guide_generation_node(state)
        assert "법령DB로 확인됐습니다" in result["guide"]["disclaimer"]

    def test_disclaimer_law_code_verified_false(self):
        state = {"law_code_verified": False, "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지"}
        result = guide_generation_node(state)
        assert "확인되지 않았습니다" in result["guide"]["disclaimer"]

    def test_disclaimer_law_code_verified_none일땐_해당문구없음(self):
        state = {"law_code_verified": None, "judgment_status": "not_applicable", "fine_type": "범칙금", "notice_stage": "즉결심판"}
        result = guide_generation_node(state)
        assert "법령DB" not in result["guide"]["disclaimer"]
        assert "확인되지 않았습니다" not in result["guide"]["disclaimer"]

    def test_disclaimer_강함_카테고리C는_조건부위험문구(self):
        """merit=강함일 때만 카테고리 C의 조건부 프레이밍이 적용된다."""
        state = {
            "merit": "강함", "risk_flag": True, "risk_trigger_category": "C_본인운전인정형",
            "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        disclaimer = result["guide"]["disclaimer"]
        assert "조건부 위험입니다" in disclaimer
        assert "받아들여지면" in disclaimer and "받아들여지지 않으면" in disclaimer

    @pytest.mark.parametrize("category", ["A_제3자운전주장", "B_명시적전환요청"])
    def test_disclaimer_강함_카테고리AB는_무조건위험문구(self, category):
        state = {
            "merit": "강함", "risk_flag": True, "risk_trigger_category": category,
            "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        assert "성공·실패와 무관하게" in result["guide"]["disclaimer"]

    @pytest.mark.parametrize("merit_value,expected_snippet", [
        ("보류", "가장 신중한 접근"),
        ("낮음", "진행 자체를 재고"),
    ])
    def test_disclaimer_보류_낮음_위험이면_강함과_다른_톤(self, merit_value, expected_snippet):
        """DATA-003 §4 매트릭스: merit=보류/낮음이면 카테고리와 무관하게
        "강함×위험" 전용 문구(조건부/무조건)가 아니라 별도 톤이 나와야 한다."""
        state = {
            "merit": merit_value, "risk_flag": True, "risk_trigger_category": "A_제3자운전주장",
            "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        disclaimer = result["guide"]["disclaimer"]
        assert expected_snippet in disclaimer
        assert "성공·실패와 무관하게" not in disclaimer
        assert "조건부 위험입니다" not in disclaimer

    @pytest.mark.parametrize("merit_value,expected_snippet", [
        ("강함", "안심하고 진행"),
        ("보류", "증거를 보강"),
        ("낮음", "기대치를 낮춰서"),
    ])
    def test_disclaimer_risk_false면_merit별_안전톤(self, merit_value, expected_snippet):
        """DATA-003 §4 매트릭스: risk_flag=False인 3칸도 merit별로 다른 톤이 나와야 한다."""
        state = {
            "merit": merit_value, "risk_flag": False,
            "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        disclaimer = result["guide"]["disclaimer"]
        assert expected_snippet in disclaimer
        assert "조건부 위험입니다" not in disclaimer
        assert "신원을 특정하는 진술" not in disclaimer

    def test_disclaimer_merit_없으면_매트릭스_톤_생략(self):
        """not_applicable/denied 경로처럼 MG가 실행되지 않아 merit이 없으면
        매트릭스 톤 문단 자체를 붙이지 않는다 (크래시 없이 조용히 생략)."""
        state = {"judgment_status": "not_applicable", "fine_type": "범칙금", "notice_stage": "즉결심판"}
        result = guide_generation_node(state)
        disclaimer = result["guide"]["disclaimer"]
        assert "안심하고 진행" not in disclaimer
        assert "재고해보시길" not in disclaimer

    def test_disclaimer_잔여리스크는_risk_flag_false여도_항상포함(self):
        state = {"risk_flag": False, "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지"}
        result = guide_generation_node(state)
        assert "법원의 사실관계 조사로 이어질 수 있으며" in result["guide"]["disclaimer"]

    def test_envelope_구조_확인(self):
        state = {"judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지"}
        result = guide_generation_node(state)
        env = result["agent_results"]["appeal_judgment"]
        assert env["node_code"] == "appeal_judgment"
        assert env["status"] == "success"
        assert set(result["guide"].keys()) == {
            "timeline", "expectation", "channel", "withdrawal", "penalty_myth", "disclaimer",
        }

    @pytest.mark.parametrize("status,expected_action_snippet", [
        ("success", "판정 결과"),
        ("denied", "기한 경과"),
        ("not_applicable", "이의신청서 생성 불가"),
    ])
    def test_next_actions_judgment_status별(self, status, expected_action_snippet):
        state = {"judgment_status": status, "fine_type": "과태료", "notice_stage": "사전통지"}
        result = guide_generation_node(state)
        env = result["agent_results"]["appeal_judgment"]
        assert any(expected_action_snippet in a for a in env["next_actions"])

    def test_fine_type_없어도_크래시_없이_미확인으로_표시(self):
        state = {"judgment_status": "success"}
        result = guide_generation_node(state)
        env = result["agent_results"]["appeal_judgment"]
        assert "미확인" in env["summary"]
