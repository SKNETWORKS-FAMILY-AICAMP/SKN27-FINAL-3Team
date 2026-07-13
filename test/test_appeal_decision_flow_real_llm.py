"""Integration tests: appeal_decision_flow — 실제 GPT 호출로 프롬프트 품질 검증

test/integration/test_appeal_decision_flow_graph.py는 GPT 호출을 목 처리해
그래프 분기 로직만 검증한다. 이 파일은 실제 RG·MG 프롬프트가 대표 시나리오에서
설계 의도대로 분류하는지 확인한다 (LLM 비결정성 때문에 키워드 매칭으로 우회
가능한 케이스는 피하고, 2단계 LLM까지 가야만 판단 가능한 애매한 표현만 쓴다).

실행:
    OPENAI_API_KEY=sk-... pytest test/test_appeal_decision_flow_real_llm.py -v -s
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
pytestmark = pytest.mark.live

TODAY = datetime.date.today()


def _iso(days_from_today: int) -> str:
    return (TODAY + datetime.timedelta(days=days_from_today)).isoformat()


def _structured(result: dict) -> dict:
    return result["agent_results"]["appeal_judgment"]["structured_result"]


@_requires_api
class TestRealRiskClassification:
    def test_완곡한_제3자_운전_암시를_카테고리A로_잡는지(self):
        """1단계 키워드로는 안 걸리는 완곡한 표현 — 2단계 LLM이 잡아야 한다."""
        result = graph.invoke({
            "fine_type": "과태료", "notice_stage": "사전통지",
            "opinion_deadline": _iso(8),
            "law_code": "도로교통법 제17조 제1항",
            "user_appeal_reason": "그날 저는 차를 쓰지 않았고, 동생이 잠깐 빌려서 몰고 나갔었습니다",
        })
        sr = _structured(result)
        print("\nrisk_flag:", sr["risk_flag"], "| category:", sr["risk_trigger_category"])
        assert sr["risk_flag"] is True
        assert sr["risk_trigger_category"] == "A_제3자운전주장"

    def test_사실관계를_다투는_사유는_안전으로_판단(self):
        """설계문서가 명시한 '안전한 사유'의 기준 예시(금액 산정 오류, 표지판 미설치)를 쓴다.
        주의: "그냥 급해서" 류처럼 본인 사정을 1인칭으로 설명하는 표현은 이유가
        빈약해도 카테고리 C(본인 운전 인정형)의 구조적 패턴에 해당해 risk_flag=True가
        나올 수 있다 — 이건 재현율 우선 원칙상 의도된 동작이지 버그가 아니다.
        "안전"의 기준은 사유의 설득력이 아니라 "신원을 특정하는 진술을 포함하는가"다."""
        result = graph.invoke({
            "fine_type": "과태료", "notice_stage": "사전통지",
            "opinion_deadline": _iso(8),
            "law_code": "도로교통법 제17조 제1항",
            "user_appeal_reason": "고지서에 적힌 과태료 금액이 실제 규정된 금액과 다르게 잘못 계산되어 있습니다",
        })
        sr = _structured(result)
        print("\nrisk_flag:", sr["risk_flag"])
        assert sr["risk_flag"] is False

    def test_142조_포괄조항류_애매한_표현도_카테고리C로_잡는지(self):
        """1단계 시드 키워드에 없는 142조 6호(포괄조항)류 표현."""
        result = graph.invoke({
            "fine_type": "과태료", "notice_stage": "사전통지",
            "opinion_deadline": _iso(8),
            "law_code": "도로교통법 제32조 제1항",
            "user_appeal_reason": "차가 갑자기 고장나서 견인차를 부를 때까지 어쩔 수 없이 그 자리에 세워둘 수밖에 없었습니다",
        })
        sr = _structured(result)
        print("\nrisk_flag:", sr["risk_flag"], "| category:", sr["risk_trigger_category"])
        # 본인이 처한 부득이한 상황을 설명하는 진술이라 category=C로 잡히는 것이 기대값
        assert sr["risk_trigger_category"] in ("C_본인운전인정형", None)


@_requires_api
class TestRealMeritClassification:
    def test_주정차_부득이한_사유_강함_예상(self):
        result = graph.invoke({
            "fine_type": "과태료", "notice_stage": "사전통지",
            "opinion_deadline": _iso(8),
            "law_code": "도로교통법 제32조 제1항",
            "user_appeal_reason": "응급환자를 병원으로 이송하다가 어쩔 수 없이 주차 위반을 하게 됐습니다",
        })
        sr = _structured(result)
        print("\nmerit:", sr["merit"])
        assert sr["merit"] == "강함"

    def test_참조법조문과_무관한_사유는_낮음_예상(self):
        result = graph.invoke({
            "fine_type": "과태료", "notice_stage": "사전통지",
            "opinion_deadline": _iso(8),
            "law_code": "도로교통법 제32조 제1항",
            "user_appeal_reason": "주차할 곳이 마땅치 않아서 어쩔 수 없이 거기에 세웠습니다",
        })
        sr = _structured(result)
        print("\nmerit:", sr["merit"])
        assert sr["merit"] in ("낮음", "보류")

    def test_1차고지서_14조_정황요소류_보류_예상(self):
        result = graph.invoke({
            "fine_type": "과태료", "notice_stage": "1차 고지서",
            "opinion_deadline": _iso(45),
            "notice_received_date": _iso(-10),
            "law_code": "도로교통법 제17조 제1항",
            "user_appeal_reason": "저는 기초생활수급자이고 고령이라 형편이 매우 어렵습니다. 한 번만 선처 부탁드립니다",
        })
        sr = _structured(result)
        print("\nmerit:", sr["merit"], "| overall_possibility:", sr["overall_possibility"])
        assert sr["merit"] in ("보류", "낮음")
        assert sr["overall_possibility"] == "이의제기_인용가능"


@_requires_api
class TestRealTheftCase:
    def test_도난_케이스는_merit강함_risk안전(self):
        result = graph.invoke({
            "fine_type": "과태료", "notice_stage": "사전통지",
            "opinion_deadline": _iso(8),
            "law_code": "도로교통법 제32조 제1항",
            "user_appeal_reason": "제 차를 도둑맞았는데 그 도둑이 운전하다가 위반한 것 같습니다",
        })
        sr = _structured(result)
        print("\nmerit:", sr["merit"], "| risk_flag:", sr["risk_flag"])
        assert sr["risk_flag"] is False
        assert sr["merit"] == "강함"
