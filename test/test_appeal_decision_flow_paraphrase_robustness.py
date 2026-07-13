"""Integration tests: appeal_decision_flow — 패러프레이즈 강건성(paraphrase robustness) 검증

`test/test_appeal_decision_flow_real_llm.py`는 "이 입력이 기대한 판정을 받는가"만 본다.
`업데이트_기록.md`(2026-07-02)가 고정한 temperature=0은 "같은 입력 → 같은 출력"의 재현성만
보장할 뿐, "같은 의미를 담은 다른 문장 → 같은 출력"인지는 별도로 검증한 적이 없었다.

이 파일은 하나의 의도(제3자 운전 주장/전환 요청/본인 운전 인정형/무관한 사유 등)를 여러
표현으로 바꿔 쓴 뒤, RG·MG가 그 그룹 안에서 서로 일치하는 판정을 내리는지 확인한다.
1단계 키워드 매칭에 걸리면 애초에 LLM까지 가지 않아 이 테스트의 의미가 없으므로, 모든
문구는 `risk_gate.py`의 시드 키워드(도난/A/B/C)를 의도적으로 피해서 2단계 LLM 판단까지
가도록 작성했다.

실행:
    OPENAI_API_KEY=sk-... pytest test/test_appeal_decision_flow_paraphrase_robustness.py -v -s
"""
import datetime
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from ai.agents.appeal_decision_flow.graph import graph  # noqa: E402

_requires_api = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set — 통합 테스트 건너뜀",
)

TODAY = datetime.date.today()


def _iso(days_from_today: int) -> str:
    return (TODAY + datetime.timedelta(days=days_from_today)).isoformat()


def _structured(result: dict) -> dict:
    return result["agent_results"]["appeal_judgment"]["structured_result"]


def _classify(reason: str, notice_stage: str = "사전통지", law_code: str = "도로교통법 제17조 제1항") -> dict:
    result = graph.invoke({
        "fine_type": "과태료", "notice_stage": notice_stage,
        "opinion_deadline": _iso(8),
        "law_code": law_code,
        "user_appeal_reason": reason,
    })
    return _structured(result)


def _assert_all_equal(field: str, phrase_to_value: dict, group_label: str) -> None:
    """그룹 내 모든 패러프레이즈가 같은 판정을 받았는지 확인한다.

    실패 시 어떤 문구가 어떤 값을 받았는지 그대로 보여줘야 프롬프트 보정 방향을
    바로 잡을 수 있어, 값 집합만 비교하지 않고 매핑 전체를 assert 메시지에 담는다.
    """
    values = set(phrase_to_value.values())
    print(f"\n[{group_label}] {field}:")
    for phrase, value in phrase_to_value.items():
        print(f"  {value!r:<30} ← {phrase}")
    assert len(values) == 1, (
        f"[{group_label}] 같은 의미의 패러프레이즈들이 서로 다른 {field}을(를) 받았습니다: "
        f"{phrase_to_value}"
    )


@_requires_api
class TestRiskParaphraseRobustness:
    """RG(risk_classification_node) — 같은 의미의 다른 문장이 같은 risk 판정을 받는지."""

    def test_제3자_운전_주장_패러프레이즈_일관성(self):
        """카테고리 A(제3자 운전 주장)를 키워드 없이 표현한 문구들 — 모두 risk_flag=True,
        category=A_제3자운전주장으로 일치해야 한다."""
        phrases = [
            "그날 운전대를 잡은 사람은 제가 아니라 배우자였습니다",
            "저는 그 시간에 운전을 하지 않았고, 제 형이 차를 몰고 나갔습니다",
            "실제로 핸들을 잡았던 건 저희 언니였고, 저는 조수석에 있었습니다",
            "차량 열쇠는 제가 갖고 있었지만 그날 실제로 몰았던 사람은 동거인이었습니다",
        ]
        risk_flags, categories = {}, {}
        for p in phrases:
            sr = _classify(p)
            risk_flags[p] = sr["risk_flag"]
            categories[p] = sr["risk_trigger_category"]
        _assert_all_equal("risk_flag", risk_flags, "카테고리A 패러프레이즈")
        _assert_all_equal("risk_trigger_category", categories, "카테고리A 패러프레이즈")
        assert next(iter(risk_flags.values())) is True
        assert next(iter(categories.values())) == "A_제3자운전주장"

    def test_명시적_전환_요청_패러프레이즈_일관성(self):
        """카테고리 B(명시적 전환 요청)를 "범칙금 전환"/"범칙금으로 전환" 키워드 없이
        표현한 문구들 — 모두 risk_flag=True로 일치해야 한다."""
        phrases = [
            "이 건은 과태료가 아니라 통고처분 절차로 넘겨서 처리해 주십시오",
            "과태료보다는 범칙금 쪽으로 처리해 주실 수 있을까요",
            "이 사건을 통고처분(범칙금) 절차로 바꿔 진행하고 싶습니다",
            "과태료 처분을 취소하고 대신 범칙금 통고 절차를 밟게 해주세요",
        ]
        risk_flags = {}
        for p in phrases:
            sr = _classify(p)
            risk_flags[p] = sr["risk_flag"]
        _assert_all_equal("risk_flag", risk_flags, "카테고리B 패러프레이즈")
        assert next(iter(risk_flags.values())) is True

    def test_본인_운전_인정형_패러프레이즈_일관성(self):
        """카테고리 C(본인 운전 인정형, 142조 6호 포괄조항류) — 1단계 시드 키워드(응급환자/
        장애인/도로공사 등)를 전혀 쓰지 않고 "차량 고장으로 부득이하게 정차"만 다르게
        표현한 문구들.

        이 케이스는 `test_appeal_decision_flow_real_llm.py`의
        `test_142조_포괄조항류_애매한_표현도_카테고리C로_잡는지`도 category를
        `("C_본인운전인정형", None)` 둘 다 허용할 만큼 원래 애매한 사례로 다뤄왔다 —
        그래서 방향(True/False)을 고정하지 않고, 그룹 내 일관성만 확인한다."""
        phrases = [
            "차가 갑자기 고장나서 견인차를 부를 때까지 어쩔 수 없이 그 자리에 세워둘 수밖에 없었습니다",
            "주행 중 갑자기 시동이 꺼져서, 안전한 곳으로 옮기지 못한 채 그 자리에 정차할 수밖에 없었습니다",
            "타이어가 터져서 도로 한복판에 차를 세울 수밖에 없는 상황이었습니다",
            "브레이크에 이상이 생겨 급하게 갓길도 아닌 그 자리에 차를 세워야 했습니다",
        ]
        risk_flags = {}
        for p in phrases:
            sr = _classify(p)
            risk_flags[p] = sr["risk_flag"]
        _assert_all_equal("risk_flag", risk_flags, "카테고리C 패러프레이즈")

    def test_신원과_무관한_사유_패러프레이즈_일관성(self):
        """신원 노출과 무관한 사유(금액 오류·표지판 등)를 여러 표현으로 바꿔도 모두
        risk_flag=False로 일치해야 한다."""
        phrases = [
            "고지서에 적힌 과태료 금액이 실제 규정된 금액과 다르게 잘못 계산되어 있습니다",
            "부과된 금액이 법정 기준보다 많이 책정된 것 같습니다",
            "고지서에 적힌 위반 장소 표기가 실제와 다릅니다",
            "안내판이 훼손되어 있어서 규정 속도를 알 수 없는 구간이었습니다",
        ]
        risk_flags = {}
        for p in phrases:
            sr = _classify(p)
            risk_flags[p] = sr["risk_flag"]
        _assert_all_equal("risk_flag", risk_flags, "신원무관 패러프레이즈")
        assert next(iter(risk_flags.values())) is False


@_requires_api
class TestMeritParaphraseRobustness:
    """MG(merit_classification_node) — 같은 의미의 다른 문장이 같은 merit 판정을 받는지."""

    def test_부득이한_사유_패러프레이즈_일관성(self):
        """응급환자 이송류(142조 3호)를 다르게 표현한 문구들 — 모두 merit=강함으로
        일치해야 한다."""
        phrases = [
            "응급환자를 병원으로 이송하다가 어쩔 수 없이 주차 위반을 하게 됐습니다",
            "위독한 환자를 태우고 급히 병원으로 가던 중이라 부득이하게 주차 규정을 어기게 됐습니다",
            "다친 사람을 병원까지 데려다주느라 정해진 주차 구역을 지킬 수 없었습니다",
            "생명이 위급한 사람을 이송하는 상황이라 부득이하게 그 자리에 차를 세웠습니다",
        ]
        merits = {}
        for p in phrases:
            sr = _classify(p, law_code="도로교통법 제32조 제1항")
            merits[p] = sr["merit"]
        _assert_all_equal("merit", merits, "부득이한사유 패러프레이즈")
        assert next(iter(merits.values())) == "강함"

    def test_참조법조문과_무관한_사유_패러프레이즈_일관성(self):
        """단순 편의상의 사정(빈자리 없음)류를 다르게 표현한 문구들 — 모두 같은
        merit(낮음 또는 보류)로 일치해야 한다."""
        phrases = [
            "주차할 곳이 마땅치 않아서 어쩔 수 없이 거기에 세웠습니다",
            "근처에 빈자리가 없어서 부득이하게 그곳에 주차했습니다",
            "주차 공간을 찾기 어려워서 잠시 그 자리에 세워둘 수밖에 없었습니다",
            "적당한 주차 자리가 안 보여서 임시로 거기 세웠습니다",
        ]
        merits = {}
        for p in phrases:
            sr = _classify(p, law_code="도로교통법 제32조 제1항")
            merits[p] = sr["merit"]
        _assert_all_equal("merit", merits, "무관사유 패러프레이즈")
        assert next(iter(merits.values())) in ("낮음", "보류")
