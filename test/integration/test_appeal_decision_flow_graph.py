"""Integration tests: appeal_decision_flow 그래프 — 플로우차트 v22 분기별 검증

GPT 호출은 목(mock) 처리하여 결정론적으로 실행한다 (LLM 응답 품질 자체는
test_appeal_decision_flow_real_llm.py의 실제 API 테스트가 다룬다).

설계문서 참고: 이의가능성_판단_에이전트_설계정리.md "전체 흐름도 (v22)"
    A --> B{fine_type}
    B --범칙금--> D(not_applicable)
    B --과태료--> DL(기한 계산: 사전통지=opinion_deadline, 1차고지서=notice_received_date+60일
                     또는 값 없으면 계산 생략) --> DCHK --경과--> DENY
                                                        --남음/계산불가--> LDB_CHECK
    LDB_CHECK --> CHK_REASON --없음--> INPUT_REQ (1차고지서면 수령일도 선택적으로 함께 요청)
                              --있음--> PARALLEL --> RG ∥ MG --> E --> G

notice_stage(사전통지/1차 고지서) 무관하게 단일 순서를 따른다 — v20에서 있던 1차 고지서
전용 분기(순서 반전)는 notice_received_date가 선택 필드로 완화되며 v22에서 제거됐다.
"""
import datetime
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from ai.agents.appeal_decision_flow.graph import graph

TODAY = datetime.date.today()


@pytest.fixture(autouse=True)
def _mock_law_code_db_lookup():
    """LDB_CHECK가 하는 실제 Postgres 조회를 목 처리한다.

    그래프 흐름 테스트는 law_code_verified 값이 각 분기에 올바르게 전파되는지만
    검증하면 되고, 법령DB(law_chunks)가 실제로 채워져 있는지는 관심사가 아니다.
    """
    with patch("etl.legal.search.law_code_exists", return_value=True):
        yield


def _iso(days_from_today: int) -> str:
    return (TODAY + datetime.timedelta(days=days_from_today)).isoformat()


def _fake_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


def _mocked_llm(risk_json: str = None, merit_json: str = None):
    """RISK/MERIT 프롬프트를 구분해 서로 다른 응답을 주는 openai.OpenAI 목."""
    risk_json = risk_json or '{"category": null, "confidence": "low", "rationale": "무관"}'
    merit_json = merit_json or '{"merit": "낮음", "merit_basis": "무관"}'

    def fake_create(*args, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        if "신원노출" in prompt:
            return _fake_response(risk_json)
        return _fake_response(merit_json)

    patcher = patch("openai.OpenAI")
    mock_cls = patcher.start()
    mock_cls.return_value.chat.completions.create.side_effect = fake_create
    return patcher


def _envelope(result: dict) -> dict:
    return result["agent_results"]["appeal_judgment"]


def _structured(result: dict) -> dict:
    return _envelope(result)["structured_result"]


# ── B: fine_type 분기 → 범칙금은 즉시 not_applicable ────────────────────────

class TestFineTypeBranch:
    def test_범칙금은_RG_MG_생략하고_즉시_not_applicable(self):
        patcher = _mocked_llm()
        try:
            result = graph.invoke({
                "fine_type": "범칙금", "notice_stage": "즉결심판",
                "opinion_deadline": _iso(5),
            })
        finally:
            patcher.stop()

        sr = _structured(result)
        assert sr["judgment_status"] == "not_applicable"
        assert sr["merit"] is None
        assert sr["risk_flag"] is None
        assert "출석 예정일시" in sr["guide"]["timeline"]

    def test_범칙금은_LLM_호출_자체가_없음(self):
        with patch("openai.OpenAI") as mock_cls:
            graph.invoke({
                "fine_type": "범칙금", "notice_stage": "사전통지",
                "opinion_deadline": _iso(5), "payment_deadline_2nd": _iso(15),
            })
            mock_cls.assert_not_called()


# ── DCHK_A / DCHK_B: 기한도과 하드게이트 ─────────────────────────────────────

class TestDeadlineGateBranch:
    def test_사전통지_기한경과시_denied_RG_MG_생략(self):
        with patch("openai.OpenAI") as mock_cls:
            result = graph.invoke({
                "fine_type": "과태료", "notice_stage": "사전통지",
                "opinion_deadline": _iso(-3),
                "user_appeal_reason": "표지판이 안 보였습니다",
            })
            mock_cls.assert_not_called()

        sr = _structured(result)
        assert sr["judgment_status"] == "denied"
        assert sr["deadline_passed"] is True
        # 사전통지 경과 경로는 LDB_CHECK 자체를 안 거치므로 law_code_verified가 없다
        assert sr["law_code_verified"] is None

    def test_1차고지서_법정기한_핵심함정_인쇄기한_남았어도_법정기한_지나면_denied(self):
        """opinion_deadline(인쇄된 납부기한)은 미래인데, 실제 수령일 기준
        법정 이의제기 마감(60일)은 이미 지난 시나리오."""
        with patch("openai.OpenAI") as mock_cls:
            result = graph.invoke({
                "fine_type": "과태료", "notice_stage": "1차 고지서",
                "opinion_deadline": _iso(5),                 # 인쇄기한: 아직 안 지남
                "notice_received_date": _iso(-65),            # 하지만 법정기한은 지남
                "law_code": "도로교통법 제17조 제1항",
                "user_appeal_reason": "사유",
            })
            mock_cls.assert_not_called()

        sr = _structured(result)
        assert sr["judgment_status"] == "denied"
        assert sr["computed_deadline"] != _iso(5)
        # (v22) deadline_gate_node가 notice_stage 무관하게 항상 맨 먼저 실행되므로,
        # 기한도과로 denied되면 law_code_check_node 자체를 거치지 않는다 —
        # 사전통지 경로(TestDeadlineGateBranch 위쪽 테스트)와 동일한 동작으로 재통일됐다.
        assert sr["law_code_verified"] is None

    def test_1차고지서_법정기한_안지나면_denied_아님(self):
        patcher = _mocked_llm()
        try:
            result = graph.invoke({
                "fine_type": "과태료", "notice_stage": "1차 고지서",
                "opinion_deadline": _iso(45),
                "notice_received_date": _iso(-10),
                "law_code": "도로교통법 제17조 제1항",
                "user_appeal_reason": "사유",
            })
        finally:
            patcher.stop()
        assert _structured(result)["judgment_status"] == "success"


# ── CHK_REASON / CHK_FIELDS: input_required 분기 (사전통지 vs 1차고지서) ────

class TestInputRequiredBranch:
    def test_사전통지_사유없으면_input_required_이미계산된_타임라인_포함(self):
        with patch("openai.OpenAI") as mock_cls:
            result = graph.invoke({
                "fine_type": "과태료", "notice_stage": "사전통지",
                "opinion_deadline": _iso(8),
                "law_code": "도로교통법 제32조 제1항",
                "user_appeal_reason": None,
            })
            mock_cls.assert_not_called()

        env = _envelope(result)
        assert env["status"] == "input_required"
        assert "user_appeal_reason" in env["missing_fields"]
        sr = env["structured_result"]
        assert sr["computed_deadline"] == _iso(8)
        assert sr["law_code_verified"] is True

    @pytest.mark.parametrize("reason,received,expected_missing", [
        (None, None, {"user_appeal_reason", "notice_received_date"}),
        (None, _iso(-5), {"user_appeal_reason"}),
    ])
    def test_1차고지서_사유누락시_input_required(self, reason, received, expected_missing):
        """(v22) user_appeal_reason이 없을 때만 input_required — notice_received_date는
        더 이상 하드 블로커가 아니다."""
        with patch("openai.OpenAI") as mock_cls:
            result = graph.invoke({
                "fine_type": "과태료", "notice_stage": "1차 고지서",
                "opinion_deadline": _iso(45),
                "law_code": "도로교통법 제32조 제1항",
                "user_appeal_reason": reason,
                "notice_received_date": received,
            })
            mock_cls.assert_not_called()

        env = _envelope(result)
        assert env["status"] == "input_required"
        assert set(env["missing_fields"]) == expected_missing
        sr = env["structured_result"]
        # (v22) deadline_gate_node가 항상 먼저 실행되므로 law_code_verified·computed_deadline은
        # notice_stage 무관하게 input_required 응답에도 이미 계산된 값으로 포함된다.
        assert sr["law_code_verified"] is True
        assert "computed_deadline" in sr

    def test_1차고지서_사유있고_수령일없으면_success_판정_수령일만_missing_fields에(self):
        """(v22) notice_received_date 없이도 사유만 있으면 성공 경로로 진행되고,
        수령일은 missing_fields에 정보성으로만 담긴다 — Supervisor 재호출을 강제하지 않는다."""
        patcher = _mocked_llm()
        try:
            result = graph.invoke({
                "fine_type": "과태료", "notice_stage": "1차 고지서",
                "opinion_deadline": _iso(45),
                "law_code": "도로교통법 제32조 제1항",
                "user_appeal_reason": "사유 있음",
                "notice_received_date": None,
            })
        finally:
            patcher.stop()

        env = _envelope(result)
        assert env["status"] == "success"
        assert env["missing_fields"] == ["notice_received_date"]
        sr = env["structured_result"]
        assert sr["judgment_status"] == "success"
        assert sr["computed_deadline"] is None
        assert "계산할 수 없습니다" in sr["guide"]["timeline"]


# ── PARALLEL → RG ∥ MG → E: 정상 완료 경로 조합 ─────────────────────────────

class TestSuccessBranch:
    def test_사전통지_주정차_도난_merit강함_risk안전(self):
        patcher = _mocked_llm(
            merit_json='{"merit": "강함", "merit_basis": "제160조4항1호 도난 해당"}',
        )
        try:
            result = graph.invoke({
                "fine_type": "과태료", "notice_stage": "사전통지",
                "opinion_deadline": _iso(8),
                "law_code": "도로교통법 제32조 제1항",
                "user_appeal_reason": "제 차를 도둑맞아서 도둑이 운전하다가 위반했습니다",
            })
        finally:
            patcher.stop()

        sr = _structured(result)
        assert sr["judgment_status"] == "success"
        assert sr["merit"] == "강함"
        assert sr["risk_flag"] is False
        assert sr["risk_trigger_category"] is None
        assert sr["overall_possibility"] == "의견_제출시_인정가능"

    def test_사전통지_카테고리C_응급환자_조건부위험(self):
        patcher = _mocked_llm(
            merit_json='{"merit": "강함", "merit_basis": "142조 3호"}',
        )
        try:
            result = graph.invoke({
                "fine_type": "과태료", "notice_stage": "사전통지",
                "opinion_deadline": _iso(8),
                "law_code": "도로교통법 제32조 제1항",
                "user_appeal_reason": "응급환자를 이송하다가 위반했습니다",
            })
        finally:
            patcher.stop()

        sr = _structured(result)
        assert sr["risk_flag"] is True
        assert sr["risk_trigger_category"] == "C_본인운전인정형"
        assert "조건부 위험" in sr["guide"]["disclaimer"]

    def test_1차고지서_카테고리A_제3자운전주장_무조건위험(self):
        patcher = _mocked_llm(
            merit_json='{"merit": "강함", "merit_basis": "제14조 정황요소 해당"}',
        )
        try:
            result = graph.invoke({
                "fine_type": "과태료", "notice_stage": "1차 고지서",
                "opinion_deadline": _iso(45),
                "notice_received_date": _iso(-10),
                "law_code": "도로교통법 제17조 제1항",
                "user_appeal_reason": "다른 사람이 운전했습니다",
            })
        finally:
            patcher.stop()

        sr = _structured(result)
        assert sr["judgment_status"] == "success"
        assert sr["overall_possibility"] == "이의제기_인용가능"
        assert sr["risk_flag"] is True
        assert sr["risk_trigger_category"] == "A_제3자운전주장"
        assert "성공·실패와 무관하게" in sr["guide"]["disclaimer"]

    def test_1차고지서_명시적전환요청_카테고리B(self):
        patcher = _mocked_llm()
        try:
            result = graph.invoke({
                "fine_type": "과태료", "notice_stage": "1차 고지서",
                "opinion_deadline": _iso(45),
                "notice_received_date": _iso(-10),
                "law_code": "도로교통법 제17조 제1항",
                "user_appeal_reason": "범칙금으로 전환해주세요",
            })
        finally:
            patcher.stop()

        sr = _structured(result)
        assert sr["risk_trigger_category"] == "B_명시적전환요청"

    def test_비주정차_위반도_MG가_142조_제7조_공통컨텍스트로_판단(self):
        """(law160-budeuk-hansayu-scope-analysis2.md 확정) 142조는 위반유형 무관 공통
        조문이라, 비주정차 law_code에서도 제7조뿐 아니라 142조까지 함께 주입돼야 한다.

        법령DB 조회를 강제로 실패시켜 하드코딩 폴백 원문으로 결정론적으로 검증한다 —
        실제 DB 원문에는 "시행규칙 제142조"/"질서위반행위규제법 제7조" 같은 표제가 없고
        조문 본문만 저장돼 있어, DB가 살아있으면 이 assertion이 흔들린다.
        """
        captured_context = {}

        def fake_create(*args, **kwargs):
            prompt = kwargs["messages"][0]["content"]
            if "신원노출" in prompt:
                return _fake_response('{"category": null, "confidence": "low", "rationale": "무관"}')
            captured_context["prompt"] = prompt
            return _fake_response('{"merit": "낮음", "merit_basis": "무관"}')

        with patch(
            "etl.legal.search.get_provision_text",
            side_effect=RuntimeError("테스트 환경 — DB 조회 불가"),
        ), patch("openai.OpenAI") as mock_cls:
            mock_cls.return_value.chat.completions.create.side_effect = fake_create
            graph.invoke({
                "fine_type": "과태료", "notice_stage": "사전통지",
                "opinion_deadline": _iso(8),
                "law_code": "도로교통법 제17조 제1항",   # 속도위반 — 비주정차
                "user_appeal_reason": "그냥 급해서 그랬습니다",
            })

        assert "질서위반행위규제법 제7조" in captured_context["prompt"]
        assert "시행규칙 제142조" in captured_context["prompt"]

    def test_MG_LLM_호출실패해도_success로_완료되되_merit_judgment_failed_표시(self):
        """MG의 LLM 호출이 실패해도 그래프는 여전히 judgment_status=success로
        끝나야 하고(RG는 정상 동작), merit="보류"가 실제 애매함 판단이 아니라
        기술적 실패라는 걸 structured_result·disclaimer·next_actions 전부에서
        구분할 수 있어야 한다."""
        def fake_create(*args, **kwargs):
            prompt = kwargs["messages"][0]["content"]
            if "신원노출" in prompt:
                return _fake_response('{"category": null, "confidence": "low", "rationale": "무관"}')
            raise ConnectionError("네트워크 오류")

        with patch("openai.OpenAI") as mock_cls:
            mock_cls.return_value.chat.completions.create.side_effect = fake_create
            result = graph.invoke({
                "fine_type": "과태료", "notice_stage": "사전통지",
                "opinion_deadline": _iso(8),
                "user_appeal_reason": "표지판이 가려져 있었습니다",
            })

        sr = _structured(result)
        assert sr["judgment_status"] == "success"
        assert sr["merit"] == "보류"
        assert sr["merit_judgment_failed"] is True
        assert "기술 오류로 완료되지 못해" in sr["guide"]["disclaimer"]

        next_actions = _envelope(result)["next_actions"]
        assert any("재호출" in action for action in next_actions)


# ── RG ∥ MG 병렬 분기의 실행 순서·독립성 확인 ────────────────────────────────

class TestParallelDispatch:
    def test_RG_MG_둘다_정확히_한번씩_호출됨(self):
        call_count = {"n": 0}

        def fake_create(*args, **kwargs):
            call_count["n"] += 1
            prompt = kwargs["messages"][0]["content"]
            if "신원노출" in prompt:
                return _fake_response('{"category": null, "confidence": "low", "rationale": "무관"}')
            return _fake_response('{"merit": "낮음", "merit_basis": "무관"}')

        with patch("openai.OpenAI") as mock_cls:
            mock_cls.return_value.chat.completions.create.side_effect = fake_create
            graph.invoke({
                "fine_type": "과태료", "notice_stage": "사전통지",
                "opinion_deadline": _iso(8),
                "law_code": "도로교통법 제17조 제1항",
                "user_appeal_reason": "그냥 급해서 그랬습니다",
            })

        assert call_count["n"] == 2  # RG 1회 + MG 1회, 중복 실행 없음

    def test_MG에서_예상못한_예외가_나면_invoke_전체가_전파(self):
        patcher = _mocked_llm()
        try:
            with patch(
                "ai.agents.appeal_decision_flow.merit_gate.get_merit_context",
                side_effect=RuntimeError("의도적으로 주입한 버그"),
            ):
                with pytest.raises(RuntimeError):
                    graph.invoke({
                        "fine_type": "과태료", "notice_stage": "사전통지",
                        "opinion_deadline": _iso(8),
                        "law_code": "도로교통법 제32조 제1항",
                        "user_appeal_reason": "사유",
                    })
        finally:
            patcher.stop()


# ── guide (①~⑥)는 모든 judgment_status에서 항상 전체 출력 ──────────────────

class TestGuideAlwaysComplete:
    _GUIDE_KEYS = {"timeline", "expectation", "channel", "withdrawal", "penalty_myth", "disclaimer"}

    def test_not_applicable_에도_가이드_6종_전부_있음(self):
        result = graph.invoke({
            "fine_type": "범칙금", "notice_stage": "즉결심판", "opinion_deadline": _iso(5),
        })
        assert set(_structured(result)["guide"].keys()) == self._GUIDE_KEYS

    def test_denied_에도_가이드_6종_전부_있음(self):
        result = graph.invoke({
            "fine_type": "과태료", "notice_stage": "사전통지",
            "opinion_deadline": _iso(-3), "user_appeal_reason": "사유",
        })
        assert set(_structured(result)["guide"].keys()) == self._GUIDE_KEYS

    def test_success_에도_가이드_6종_전부_있음(self):
        patcher = _mocked_llm()
        try:
            result = graph.invoke({
                "fine_type": "과태료", "notice_stage": "사전통지",
                "opinion_deadline": _iso(8), "law_code": "도로교통법 제32조 제1항",
                "user_appeal_reason": "그냥 급해서 그랬습니다",
            })
        finally:
            patcher.stop()
        assert set(_structured(result)["guide"].keys()) == self._GUIDE_KEYS
