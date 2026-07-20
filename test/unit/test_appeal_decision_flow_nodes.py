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
from ai.agents.appeal_decision_flow.law_refs import (
    LegalProvisionEvidenceUnavailable,
    get_merit_context,
)
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


# ── law_code_check_node (LDB_CHECK, DATA-003 §7) ────────────────────────────

class TestLawCodeCheckNode:
    @pytest.mark.parametrize("law_code", [None, ""])
    def test_law_code_없으면_조회없이_False(self, law_code):
        with patch("etl.legal.search.law_code_exists") as mock_exists:
            result = law_code_check_node({"law_code": law_code})
        mock_exists.assert_not_called()
        assert result == {"law_code_verified": False}

    def test_DB에_존재하면_True(self):
        with patch("etl.legal.search.law_code_exists", return_value=True) as mock_exists:
            result = law_code_check_node({"law_code": "도로교통법 제17조 제1항"})
        mock_exists.assert_called_once_with("도로교통법 제17조 제1항")
        assert result == {"law_code_verified": True}

    def test_DB에_없거나_조회_실패시_False(self):
        with patch("etl.legal.search.law_code_exists", return_value=False):
            result = law_code_check_node({"law_code": "존재하지 않는 법 제999조"})
        assert result == {"law_code_verified": False}


# ── reason_intake_node (ARCH-001 §9-7) ──────────────────────────────────────

class TestReasonIntakeNode:
    def test_사전통지_사유있으면_통과(self):
        state = {"notice_stage": "사전통지", "user_appeal_reason": "표지판이 안 보였습니다"}
        assert reason_intake_node(state) == {"reason_quality_insufficient": False}

    def test_사유가_짧으면_reason_quality_insufficient_True(self):
        """"그냥요"류 한두 단어 사유는 재질문 대상은 아니지만(존재 자체는 하므로), 판단
        근거가 빈약하다는 신호는 남겨야 guide_generation_node가 사실대로 안내할 수 있다
        (이의가능성_판단_에이전트_미비점_조사_2026-07-09.md 🔴2)."""
        state = {"notice_stage": "사전통지", "user_appeal_reason": "그냥요"}
        assert reason_intake_node(state) == {"reason_quality_insufficient": True}

    def test_사유_길이_임계값_경계(self):
        state_short = {"notice_stage": "사전통지", "user_appeal_reason": "a" * 9}
        state_long = {"notice_stage": "사전통지", "user_appeal_reason": "a" * 10}
        assert reason_intake_node(state_short) == {"reason_quality_insufficient": True}
        assert reason_intake_node(state_long) == {"reason_quality_insufficient": False}

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
        assert reason_intake_node(state) == {"reason_quality_insufficient": False}

    def test_1차고지서_사유만있고_수령일없어도_통과(self):
        """(v22) notice_received_date는 선택 필드 — 사유만 있으면 수령일이
        없어도 재질문하지 않고 통과시킨다."""
        state = {
            "notice_stage": "1차 고지서",
            "user_appeal_reason": "표지판이 안 보였습니다",
            "notice_received_date": None,
        }
        assert reason_intake_node(state) == {"reason_quality_insufficient": False}

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
    @pytest.fixture(autouse=True)
    def _verified_rag_results(self):
        """각 고정 참조 질의에 기대한 법령 출처의 검증된 RAG 결과를 제공한다."""
        def fake_search(*, query_text, **_kwargs):
            source_name = (
                "도로교통법 시행규칙"
                if query_text.startswith("도로교통법 시행규칙")
                else "질서위반행위규제법"
            )
            return [{
                "source_name": source_name,
                "provision_text": query_text,
                "score": 0.9,
            }]

        with patch.dict("os.environ", {"LEGAL_PROVISION_DB_ENABLED": "1"}), patch(
            "ai.agents.appeal_decision_flow.law_refs.search_law_provisions",
            side_effect=fake_search,
        ):
            yield

    def test_사전통지_컨텍스트_위반유형무관_공통조문(self):
        ctx = get_merit_context("사전통지")
        assert "제160조제4항제1호" in ctx
        assert "시행규칙 제142조" in ctx
        assert "질서위반행위규제법 제7조" in ctx
        assert "질서위반행위규제법 제8조" in ctx
        assert "질서위반행위규제법 제9조" in ctx
        assert "질서위반행위규제법 제10조" in ctx
        assert "제14조" not in ctx

    def test_1차고지서_컨텍스트_위반유형무관_공통조문(self):
        ctx = get_merit_context("1차 고지서")
        assert "제160조제4항제1호" in ctx
        assert "시행규칙 제142조" in ctx
        assert "질서위반행위규제법 제7조" in ctx
        assert "질서위반행위규제법 제8조" in ctx
        assert "질서위반행위규제법 제9조" in ctx
        assert "질서위반행위규제법 제10조" in ctx
        assert "질서위반행위규제법 제14조" in ctx

    def test_DB_조회_성공하면_RAG_매칭_원문_사용(self):
        """RAG 검색이 신뢰도 기준(evaluate_confidence)을 넘는 매칭을 반환하면, 조문번호가
        아니라 source_name 일치 여부로 폴백 대신 그 매칭 원문을 쓴다."""
        def confident_match(*, query_text, **_kwargs):
            source_name = (
                "도로교통법 시행규칙"
                if query_text.startswith("도로교통법 시행규칙")
                else "질서위반행위규제법"
            )
            return [{
                "source_name": source_name,
                "provision_text": "(DB) 실제 법령DB에서 조회된 조문 원문",
                "score": 0.9,
            }]

        with patch(
            "ai.agents.appeal_decision_flow.law_refs.search_law_provisions",
            side_effect=confident_match,
        ):
            ctx = get_merit_context("사전통지")
        assert "(DB) 실제 법령DB에서 조회된 조문 원문" in ctx
        assert "질서위반행위규제법 제7조(고의 또는 과실)" not in ctx

    def test_source_name_불일치하면_판정_중단(self):
        """검색 결과가 신뢰도는 높아도 엉뚱한 법(source_name 불일치)에 매칭됐다면
        하드코딩 원문으로 대체하지 않고 법령 근거 미확보로 판정을 중단한다."""
        wrong_source_match = [{
            "source_name": "형법",  # REQUIRED_RAG_REFERENCES에 없는 source_name이어야 진짜 불일치를 검증한다
            "provision_text": "전혀 다른 법의 조문 원문",
            "score": 0.9,
        }]
        with patch(
            "ai.agents.appeal_decision_flow.law_refs.search_law_provisions",
            return_value=wrong_source_match,
        ), pytest.raises(LegalProvisionEvidenceUnavailable) as exc_info:
            get_merit_context("사전통지")
        assert exc_info.value.reason_code == "legal_provision_low_confidence_or_not_found"


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

    def test_카테고리A가_B보다_우선(self):
        reason = "다른 사람이 운전했는데 범칙금으로 전환해주세요"
        result = risk_classification_node({"user_appeal_reason": reason})
        assert result["risk_trigger_category"] == "A_제3자운전주장"

    def test_카테고리B가_C보다_우선(self):
        reason = "범칙금으로 전환해주세요, 응급환자를 이송하다가 위반했습니다"
        result = risk_classification_node({"user_appeal_reason": reason})
        assert result["risk_trigger_category"] == "B_명시적전환요청"

    def test_2단계_LLM_마크다운코드펜스로_감싼_응답도_파싱(self):
        """LLM이 프롬프트 지시(순수 JSON만 반환)를 어기고 ```json 코드펜스로
        감싸 응답해도, 정규식 폴백으로 JSON을 추출해 정상 처리해야 한다."""
        wrapped = '```json\n{"category": "A", "confidence": "high", "rationale": "코드펜스 응답"}\n```'
        patcher = _patch_openai(wrapped)
        try:
            result = risk_classification_node({"user_appeal_reason": "동생이 잠깐 몰고 나갔었습니다"})
            assert result["risk_flag"] is True
            assert result["risk_trigger_category"] == "A_제3자운전주장"
        finally:
            patcher.stop()

    def test_2단계_LLM_category도_JSON도_전혀_없으면_예외전파_후_위험폴백(self):
        """중괄호 자체가 없어 정규식 폴백도 실패하면 예외가 그대로 올라가고,
        risk_classification_node의 최상위 except가 이를 위험 쪽으로 흡수해야 한다."""
        patcher = _patch_openai("죄송합니다, 판단할 수 없습니다.")
        try:
            result = risk_classification_node({"user_appeal_reason": "애매한 사유"})
            assert result["risk_flag"] is True
        finally:
            patcher.stop()

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
    @pytest.fixture(autouse=True)
    def _verified_law_context(self):
        """MG 자체 테스트는 법령 근거 확보가 끝난 상태에서 LLM 판정만 격리한다."""
        with patch(
            "ai.agents.appeal_decision_flow.merit_gate.get_merit_context",
            return_value="[source=도로교통법 시행규칙; provenance=legal_rag]\n시행규칙 제142조",
        ):
            yield

    def test_사전통지면_142조_컨텍스트_위반유형무관_포함(self):
        """142조는 law_code(주정차 여부)로 더 이상 라우팅되지 않고 항상 포함된다
        (law160-budeuk-hansayu-scope-analysis2.md) — 비주정차 law_code로 검증.

        법령DB 조회를 강제로 실패시켜 하드코딩 폴백 원문으로 결정론적으로 검증한다 —
        실제 DB가 응답하면 원문에 "시행규칙 제142조"라는 표제가 없어(조문 본문만 저장됨)
        이 assertion이 DB 가용 여부에 따라 흔들리기 때문.
        """
        with patch(
            "etl.legal.search.get_provision_text",
            side_effect=RuntimeError("테스트 환경 — DB 조회 불가"),
        ), patch("ai.agents.appeal_decision_flow.merit_gate._call_llm_merit") as mock_call:
            mock_call.return_value = {"merit": "강함", "merit_basis": "x"}
            merit_classification_node({
                "user_appeal_reason": "응급환자를 이송했습니다",
                "notice_stage": "사전통지", "law_code": "도로교통법 제17조",
            })
            called_context = mock_call.call_args[0][1]
            assert "시행규칙 제142조" in called_context

    def test_LLM_예외시_보류로_폴백(self):
        """LLM 호출 자체가 실패한 "보류"는 merit_judgment_failed=True로 표시돼야
        한다 — guide_generation_node가 이걸로 실제 애매함과 기술적 실패를 구분한다."""
        with patch("openai.OpenAI", side_effect=ConnectionError("네트워크 오류")):
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit"] == "보류"
            assert result["merit_basis"]
            assert result["merit_judgment_failed"] is True

    def test_정의되지_않은_merit값은_보류로_정규화(self):
        """모델이 정의되지 않은 값을 낸 경우도 사유를 실제로 검토한 결과가 아니므로
        merit_judgment_failed=True로 표시돼야 한다."""
        patcher = _patch_openai('{"merit": "매우강함", "merit_basis": "이상한 응답"}')
        try:
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit"] == "보류"
            assert result["merit_judgment_failed"] is True
        finally:
            patcher.stop()

    @pytest.mark.parametrize("merit_value", ["강함", "보류", "낮음"])
    def test_정의된_merit값은_그대로_통과(self, merit_value):
        """LLM이 정상적으로 정의된 값을 냈으면 merit_judgment_failed=False다 —
        merit="보류"여도 이건 실제로 애매하다고 판단된 정상 결과다."""
        patcher = _patch_openai(f'{{"merit": "{merit_value}", "merit_basis": "근거"}}')
        try:
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit"] == merit_value
            assert result["merit_judgment_failed"] is False
        finally:
            patcher.stop()

    @pytest.mark.parametrize("relief_value", ["면제", "감경"])
    def test_강함이면_relief_type_그대로_통과(self, relief_value):
        patcher = _patch_openai(
            f'{{"merit": "강함", "relief_type": "{relief_value}", "merit_basis": "근거"}}'
        )
        try:
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit_relief_type"] == relief_value
        finally:
            patcher.stop()

    @pytest.mark.parametrize("merit_value", ["보류", "낮음"])
    def test_강함_아니면_relief_type_모델응답과_무관하게_None(self, merit_value):
        """relief_type은 merit="강함"일 때만 의미가 있다 — 모델이 실수로 다른
        merit에 relief_type을 채워도 무시해야 한다."""
        patcher = _patch_openai(
            f'{{"merit": "{merit_value}", "relief_type": "감경", "merit_basis": "근거"}}'
        )
        try:
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit_relief_type"] is None
        finally:
            patcher.stop()

    @pytest.mark.parametrize("hedge_word", ["미약", "약간", "다소", "조금", "일부"])
    def test_relief_type_사유에_정도완화_표현이_있으면_면제여도_감경으로_재보정(self, hedge_word):
        """실측으로 확인된 문제: LLM(gpt-4o-mini)이 프롬프트 지시에도 불구하고
        "미약/다소"류 표현이 있는 사유를 계속 면제(제10조①)로 잘못 분류하는 경우가
        있었다 — 사용자 표현 자체가 정도를 낮춰 말했으면 안전한 쪽(감경)으로
        재보정해야 한다."""
        patcher = _patch_openai(
            f'{{"merit": "강함", "relief_type": "면제", '
            f'"merit_basis": "판단능력이 {hedge_word} 저하됨"}}'
        )
        try:
            result = merit_classification_node({
                "user_appeal_reason": f"그 당시 판단력이 {hedge_word} 흐려진 상태였습니다",
                "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit_relief_type"] == "감경"
        finally:
            patcher.stop()

    def test_relief_type_정도완화_표현_없으면_면제_그대로_유지(self):
        patcher = _patch_openai(
            '{"merit": "강함", "relief_type": "면제", "merit_basis": "판단능력이 전혀 없었음"}'
        )
        try:
            result = merit_classification_node({
                "user_appeal_reason": "그 당시 의식이 완전히 없는 상태였습니다",
                "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit_relief_type"] == "면제"
        finally:
            patcher.stop()

    @pytest.mark.parametrize("reason", [
        "장애인 승하차를 돕느라 다소 시간이 걸렸습니다",       # 142조5호 — 감경 개념이 없는 순수 면제형
        "표지판이 나뭇가지에 일부 가려져 있어서 몰랐습니다",   # 8조(위법성의 착오) — 마찬가지
        "제 차를 도둑맞았는데 약간 파손된 채로 발견됐습니다",  # 도난(160조4항1호) — 마찬가지
    ])
    def test_relief_type_정도완화_표현이_있어도_심신_문맥_아니면_면제_유지(self, reason):
        """142조/8조/도난처럼 애초에 "감경" 개념 자체가 없는 순수 면제형 조문은,
        사유에 "다소/일부/약간" 같은 표현이 우연히 섞여 있어도 심신·판단 관련
        문맥이 아니면 재보정하면 안 된다 — 정당한 면제 사유를 과소평가하게 된다."""
        patcher = _patch_openai(
            '{"merit": "강함", "relief_type": "면제", "merit_basis": "근거"}'
        )
        try:
            result = merit_classification_node({
                "user_appeal_reason": reason, "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit_relief_type"] == "면제"
        finally:
            patcher.stop()

    def test_relief_type_정의되지_않은_값이면_None(self):
        patcher = _patch_openai('{"merit": "강함", "relief_type": "일부면제", "merit_basis": "근거"}')
        try:
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit_relief_type"] is None
        finally:
            patcher.stop()

    def test_relief_type_정의되지_않은_값이면_relief_type_judgment_failed_True(self):
        """merit="강함"이면 참조 법조문은 항상 면제/감경 중 하나로 확정되므로,
        정의 밖의 값이 나온 시점의 None은 "구분 불필요"가 아니라 판정 실패다 —
        merit_judgment_failed와 대칭으로 플래그가 서야 한다."""
        patcher = _patch_openai('{"merit": "강함", "relief_type": "일부면제", "merit_basis": "근거"}')
        try:
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["relief_type_judgment_failed"] is True
        finally:
            patcher.stop()

    def test_LLM_예외시_relief_type도_None(self):
        with patch("openai.OpenAI", side_effect=ConnectionError("네트워크 오류")):
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit_relief_type"] is None

    @pytest.mark.parametrize("relief_value", ["면제", "감경"])
    def test_relief_type_정상_판정시_relief_type_judgment_failed_False(self, relief_value):
        patcher = _patch_openai(
            f'{{"merit": "강함", "relief_type": "{relief_value}", "merit_basis": "근거"}}'
        )
        try:
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["relief_type_judgment_failed"] is False
        finally:
            patcher.stop()

    @pytest.mark.parametrize("merit_value", ["보류", "낮음"])
    def test_강함_아니면_relief_type_judgment_failed_None(self, merit_value):
        """relief_type 호출 자체가 애초에 일어나지 않는 경우(merit != 강함)는
        "적용 대상 아님"이지 판정 실패가 아니므로 None이어야 한다."""
        patcher = _patch_openai(f'{{"merit": "{merit_value}", "merit_basis": "근거"}}')
        try:
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["relief_type_judgment_failed"] is None
        finally:
            patcher.stop()

    def test_merit_1차_호출_자체_실패시_relief_type_judgment_failed_None(self):
        """merit 판정 자체가 실패하면(merit_judgment_failed=True) relief_type
        호출까지 가지도 못했으므로, 원인은 merit_judgment_failed로 이미 드러난다 —
        relief_type_judgment_failed는 별개 실패로 이중 표시하지 않고 None을 유지한다."""
        with patch("openai.OpenAI", side_effect=ConnectionError("네트워크 오류")):
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit_judgment_failed"] is True
            assert result["relief_type_judgment_failed"] is None

    @pytest.mark.parametrize("merit_value", ["보류", "낮음"])
    def test_강함_아니면_relief_type_전용_호출_자체를_안함(self, merit_value):
        """merit·relief_type을 한 호출에서 같이 물었더니 "미약"류 표현에도
        면제로 오판하는 게 확인돼 별도 호출로 분리했다 — 다만 그 호출은
        merit="강함"일 때만 의미가 있으므로, 보류/낮음이면 API 호출 자체를
        아끼고(비용·지연시간) 곧바로 None으로 처리해야 한다."""
        with patch("openai.OpenAI") as mock_cls:
            mock_cls.return_value.chat.completions.create.return_value = _fake_llm_response(
                f'{{"merit": "{merit_value}", "merit_basis": "근거"}}'
            )
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit_relief_type"] is None
            assert mock_cls.return_value.chat.completions.create.call_count == 1

    def test_강함이면_relief_type_판단을_위해_2차_호출_발생(self):
        with patch("openai.OpenAI") as mock_cls:
            mock_cls.return_value.chat.completions.create.return_value = _fake_llm_response(
                '{"merit": "강함", "relief_type": "면제", "merit_basis": "근거"}'
            )
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit_relief_type"] == "면제"
            assert mock_cls.return_value.chat.completions.create.call_count == 2

    def test_relief_type_전용_2차_호출이_실패해도_merit은_그대로_강함_유지(self):
        """relief_type 세부 구분에만 실패한 것이지 merit(인정 가능성) 판단
        자체가 실패한 게 아니므로, merit_judgment_failed는 건드리지 않는다."""
        call_state = {"n": 0}

        def fake_create(*args, **kwargs):
            call_state["n"] += 1
            if call_state["n"] == 1:
                return _fake_llm_response('{"merit": "강함", "merit_basis": "근거"}')
            raise ConnectionError("relief_type 호출 네트워크 오류")

        with patch("openai.OpenAI") as mock_cls:
            mock_cls.return_value.chat.completions.create.side_effect = fake_create
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit"] == "강함"
            assert result["merit_judgment_failed"] is False
            assert result["merit_relief_type"] is None
            assert result["relief_type_judgment_failed"] is True

    def test_마크다운코드펜스로_감싼_응답도_파싱(self):
        """LLM이 프롬프트 지시(순수 JSON만 반환)를 어기고 ```json 코드펜스로
        감싸 응답해도, 정규식 폴백으로 JSON을 추출해 정상 처리해야 한다."""
        wrapped = '```json\n{"merit": "강함", "merit_basis": "코드펜스 응답"}\n```'
        patcher = _patch_openai(wrapped)
        try:
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit"] == "강함"
        finally:
            patcher.stop()

    def test_JSON도_전혀_없으면_예외전파_후_보류폴백(self):
        """중괄호 자체가 없어 정규식 폴백도 실패하면 예외가 그대로 올라가고,
        merit_classification_node의 최상위 except가 이를 "보류"로 흡수해야 한다."""
        patcher = _patch_openai("죄송합니다, 판단할 수 없습니다.")
        try:
            result = merit_classification_node({
                "user_appeal_reason": "사유", "notice_stage": "사전통지", "law_code": None,
            })
            assert result["merit"] == "보류"
            assert result["merit_judgment_failed"] is True
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

    def test_타임라인_과태료_notice_stage_없으면_사전통지로_취급(self):
        """_timeline_text는 `1차 고지서`만 별도 분기하고 그 외(None 포함)는 전부
        "사전통지" 취급하는 catch-all이다 — notice_stage가 비어 있어도 크래시 없이
        의견제출기한 문구로 대체된다는 현재 동작을 명시적으로 고정해둔다."""
        state = {
            "fine_type": "과태료", "notice_stage": None,
            "opinion_deadline": _iso(8), "judgment_status": "success",
        }
        result = guide_generation_node(state)
        assert "의견제출기한" in result["guide"]["timeline"]

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

    def test_disclaimer_law_code_verified_false_law_code_없음(self):
        """law_code 자체가 없는 경우(OCR이 애초에 조항을 못 읽음)는 "표기 자체를
        인식하지 못했다"는 문구를 써야 한다 — 있는데 DB에 없는 경우와 구분
        (이의가능성_판단_에이전트_미비점_조사_2026-07-09.md 🟡4)."""
        state = {
            "law_code_verified": False, "law_code": None, "judgment_status": "success",
            "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        assert "표기 자체를 인식하지 못했습니다" in result["guide"]["disclaimer"]
        assert "법령DB에서 확인되지 않았습니다" not in result["guide"]["disclaimer"]

    def test_disclaimer_law_code_verified_false_law_code_있음(self):
        """law_code는 있는데 법령DB에 없는 경우(오독·오기 가능성)는 별도 문구를
        써야 한다."""
        state = {
            "law_code_verified": False, "law_code": "존재하지 않는 법 제999조",
            "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        assert "법령DB에서 확인되지 않았습니다" in result["guide"]["disclaimer"]
        assert "표기 자체를 인식하지 못했습니다" not in result["guide"]["disclaimer"]

    def test_disclaimer_law_code_verified_none일땐_해당문구없음(self):
        state = {"law_code_verified": None, "judgment_status": "not_applicable", "fine_type": "범칙금", "notice_stage": "즉결심판"}
        result = guide_generation_node(state)
        assert "법령DB" not in result["guide"]["disclaimer"]
        assert "확인되지 않았습니다" not in result["guide"]["disclaimer"]

    def test_disclaimer_사유_부실하면_보강안내_포함(self):
        state = {
            "reason_quality_insufficient": True, "judgment_status": "success",
            "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        assert "판단 근거가 충분하지 않을 수 있습니다" in result["guide"]["disclaimer"]

    def test_disclaimer_사유_충분하면_보강안내_없음(self):
        state = {
            "reason_quality_insufficient": False, "judgment_status": "success",
            "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        assert "판단 근거가 충분하지 않을 수 있습니다" not in result["guide"]["disclaimer"]

    @pytest.mark.parametrize("fine_type,notice_stage", [
        ("과태료", "사전통지"), ("범칙금", "즉결심판"), ("과태료", "1차 고지서"),
    ])
    def test_disclaimer_알려진_스키마값이면_경고없음(self, fine_type, notice_stage):
        state = {
            "judgment_status": "success", "fine_type": fine_type, "notice_stage": notice_stage,
        }
        result = guide_generation_node(state)
        assert "예상된 형식과 달라" not in result["guide"]["disclaimer"]

    @pytest.mark.parametrize("fine_type,notice_stage", [
        ("과태료 ", "사전통지"),   # 공백 오타
        ("과태료", "1챠 고지서"),  # 오탈자
        (None, "사전통지"),        # 누락
        ("과태료", None),
    ])
    def test_disclaimer_알려지지않은_스키마값이면_경고문구_포함(self, fine_type, notice_stage):
        """오탈자·공백·None 같은 예상 밖 값이 와도 판정 자체는 그대로 진행하되
        (하드 블로커 없음), 침묵하는 오분류가 아니라 명시적 경고를 남겨야 한다
        (이의가능성_판단_에이전트_미비점_조사_2026-07-09.md 🟡5)."""
        state = {
            "judgment_status": "success", "fine_type": fine_type, "notice_stage": notice_stage,
        }
        result = guide_generation_node(state)
        assert "예상된 형식과 달라" in result["guide"]["disclaimer"]

    def test_next_actions_스키마값_예상밖이면_재확인_권장_추가(self):
        state = {"judgment_status": "success", "fine_type": "과태료", "notice_stage": "오탈자단계"}
        result = guide_generation_node(state)
        next_actions = result["agent_results"]["appeal_judgment"]["next_actions"]
        assert any("OCR 결과" in action for action in next_actions)

    def test_structured_result_schema_fields_unrecognized_노출(self):
        state = {"judgment_status": "success", "fine_type": "범칙금", "notice_stage": "오탈자단계"}
        result = guide_generation_node(state)
        structured = result["agent_results"]["appeal_judgment"]["structured_result"]
        assert structured["schema_fields_unrecognized"] == ["notice_stage"]

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

    def test_disclaimer_강함_감경이면_처분취소아님_문구_포함(self):
        """merit=강함이어도 relief_type=감경이면 "처분 자체가 없어지는 게 아니라
        금액만 줄어든다"는 정정 문구가 붙어야 한다 (예: 질서법 제10조②)."""
        state = {
            "merit": "강함", "merit_relief_type": "감경", "risk_flag": False,
            "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        disclaimer = result["guide"]["disclaimer"]
        assert "처분 자체가 없어지는 게 아니라" in disclaimer
        assert "안심하고 진행" in disclaimer  # 기존 강함 톤도 그대로 이어붙음

    @pytest.mark.parametrize("relief_type", ["면제", None])
    def test_disclaimer_강함_면제거나_구분없으면_감경문구_없음(self, relief_type):
        state = {
            "merit": "강함", "merit_relief_type": relief_type, "risk_flag": False,
            "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        assert "처분 자체가 없어지는 게 아니라" not in result["guide"]["disclaimer"]

    def test_disclaimer_보류나_낮음은_relief_type_있어도_감경문구_없음(self):
        """relief_type은 merit="강함"일 때만 의미 있다 — 다른 merit엔 감경 문구를
        붙이지 않는다(방어적: 애초에 merit_gate가 이 조합을 안 만들지만 이중 확인)."""
        state = {
            "merit": "보류", "merit_relief_type": "감경", "risk_flag": False,
            "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        assert "처분 자체가 없어지는 게 아니라" not in result["guide"]["disclaimer"]

    def test_disclaimer_merit_판정실패시_애매함과_구분되는_안내(self):
        """merit_judgment_failed=True면 "판단이 애매하다"가 아니라 "판단을
        못 했다, 재시도하면 다를 수 있다"는 별도 안내가 톤 앞에 붙어야 한다."""
        state = {
            "merit": "보류", "merit_judgment_failed": True, "risk_flag": False,
            "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        disclaimer = result["guide"]["disclaimer"]
        assert "기술 오류로 완료되지 못해" in disclaimer
        assert "포기하지 마시고" in disclaimer
        assert "증거를 보강" in disclaimer  # 기존 "보류" 톤도 그대로 이어붙음

    def test_disclaimer_merit_판정성공한_보류는_실패안내_없음(self):
        """merit_judgment_failed=False(정상적으로 애매하다고 판단된 "보류")면
        기술 실패 안내 문구가 붙지 않아야 한다."""
        state = {
            "merit": "보류", "merit_judgment_failed": False, "risk_flag": False,
            "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        assert "기술 오류로 완료되지 못해" not in result["guide"]["disclaimer"]

    def test_disclaimer_relief_type_판정실패시_감경문구와_구분되는_안내(self):
        """relief_type_judgment_failed=True면 확정된 "감경" 문구가 아니라 "면제/감경
        구분이 기술 오류로 확정되지 못했다"는 별도 안내가 붙어야 한다."""
        state = {
            "merit": "강함", "merit_relief_type": None, "relief_type_judgment_failed": True,
            "risk_flag": False, "judgment_status": "success", "fine_type": "과태료",
            "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        disclaimer = result["guide"]["disclaimer"]
        assert "면제(처분 자체 불가)인지 감경(금액만 축소)인지" in disclaimer
        assert "처분 자체가 없어지는 게 아니라" not in disclaimer  # 확정된 감경 문구는 아님
        assert "안심하고 진행" in disclaimer  # 기존 강함 톤도 그대로 이어붙음

    def test_disclaimer_relief_type_판정성공시_실패안내_없음(self):
        state = {
            "merit": "강함", "merit_relief_type": "면제", "relief_type_judgment_failed": False,
            "risk_flag": False, "judgment_status": "success", "fine_type": "과태료",
            "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        assert "기술 오류로 완료되지 못했습니다" not in result["guide"]["disclaimer"]

    def test_disclaimer_merit_강함_아니면_relief_type_판정실패여도_안내없음(self):
        """relief_type은 merit="강함"일 때만 의미 있다 — merit_gate가 이 조합을
        만들지 않지만, guide 쪽에서도 방어적으로 merit 조건을 확인해야 한다."""
        state = {
            "merit": "보류", "relief_type_judgment_failed": True, "risk_flag": False,
            "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        assert "기술 오류로 완료되지 못했습니다" not in result["guide"]["disclaimer"]

    def test_next_actions_merit_판정실패시_재호출_권장_추가(self):
        state = {
            "merit": "보류", "merit_judgment_failed": True, "risk_flag": False,
            "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        next_actions = result["agent_results"]["appeal_judgment"]["next_actions"]
        assert any("다시 질문" in action for action in next_actions)

    def test_next_actions_relief_type_판정실패시_재호출_권장_추가(self):
        state = {
            "merit": "강함", "relief_type_judgment_failed": True, "risk_flag": False,
            "judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지",
        }
        result = guide_generation_node(state)
        next_actions = result["agent_results"]["appeal_judgment"]["next_actions"]
        assert any("면제/감경" in action and "다시 시도" in action for action in next_actions)

    def test_next_actions_merit_판정실패_아니면_재호출문구_없음(self):
        state = {"judgment_status": "success", "fine_type": "과태료", "notice_stage": "사전통지"}
        result = guide_generation_node(state)
        next_actions = result["agent_results"]["appeal_judgment"]["next_actions"]
        assert not any("다시 질문" in action for action in next_actions)

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
