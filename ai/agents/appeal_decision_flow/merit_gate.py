import json
import re

import openai

from .law_refs import get_merit_context
from .prompts import MERIT_CLASSIFICATION_PROMPT, RELIEF_TYPE_CLASSIFICATION_PROMPT
from .state import AppealJudgmentState

_VALID_MERIT = {"강함", "보류", "낮음"}
_VALID_RELIEF_TYPES = {"면제", "감경"}

# 같은 조문 안에 면제 항·감경 항이 함께 있는 경우(예: 질서법 제10조① 능력없음=면제 vs
# ② 능력미약=감경), LLM(gpt-4o-mini)이 프롬프트 지시에도 불구하고 사용자가 "미약/다소"류
# 표현을 썼는데도 계속 ①(면제)로 잘못 분류하는 게 실측으로 확인됐다 — RG의 1단계 키워드
# 안전장치와 같은 패턴으로, LLM 판단 위에 보수적 재보정을 한 겹 더 둔다.
#
# ⚠️ 정도완화 표현(예: "다소", "일부")만으로 판단하면 안 된다 — 142조5호("장애인 승하차를
# 돕느라 다소 지체됐다")나 8조("표지판이 일부 가려져 몰랐다")처럼 애초에 "감경" 개념 자체가
# 없는 순수 면제형 조문에서도 이 단어들이 자연스럽게 나올 수 있다. 그런 경우까지 감경으로
# 깎아버리면 정당한 면제 사유를 과소평가하게 되므로, **"능력이 얼마나 됐는지"를 말하는
# 문맥(심신·판단·의식·정신)과 함께 나올 때만** 재보정한다 — 심신장애(제10조) 케이스에만
# 좁게 적용하려는 의도다.
_DIMINISHED_CAPACITY_HEDGE_WORDS = ("미약", "약간", "다소", "조금", "일부")
_CAPACITY_CONTEXT_WORDS = ("심신", "판단", "의식", "정신")


def _downgrade_relief_type_if_hedged(reason: str, relief_type: str | None) -> str | None:
    """심신장애류 능력 판단 문맥에서 사용자 표현이 정도를 낮춰 말했는데 LLM이 "면제"를
    줬다면, 실제로는 감경 사유일 가능성이 높으므로 안전한 쪽(감경)으로 재보정한다 —
    처분이 취소될 거라는 과도한 기대를 사용자에게 주면 안 되기 때문에, 애매하면 항상
    보수적으로. 능력 판단과 무관한 문맥(장애인 돕기, 표지판 등)까지 건드리지 않도록
    두 종류의 단어가 함께 있을 때만 작동한다."""
    if relief_type != "면제":
        return relief_type
    has_hedge = any(word in reason for word in _DIMINISHED_CAPACITY_HEDGE_WORDS)
    has_capacity_context = any(word in reason for word in _CAPACITY_CONTEXT_WORDS)
    if has_hedge and has_capacity_context:
        return "감경"
    return relief_type


def _parse_llm_json(raw: str) -> dict:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise


def _call_llm_merit(reason: str, law_context: str) -> dict:
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=256,
        temperature=0,
        messages=[{
            "role": "user",
            "content": MERIT_CLASSIFICATION_PROMPT.format(reason=reason, law_context=law_context),
        }],
    )
    return _parse_llm_json(response.choices[0].message.content)


def _call_llm_relief_type(reason: str, law_context: str) -> dict:
    """merit="강함"일 때만 호출하는 전용 판단 — merit·relief_type을 한 호출에서
    함께 물었더니 "미약"류 표현에도 계속 면제(①)로 잘못 답하는 게 실측으로 확인돼
    분리했다 (prompts.py의 RELIEF_TYPE_CLASSIFICATION_PROMPT 주석 참고)."""
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=256,
        temperature=0,
        messages=[{
            "role": "user",
            "content": RELIEF_TYPE_CLASSIFICATION_PROMPT.format(reason=reason, law_context=law_context),
        }],
    )
    return _parse_llm_json(response.choices[0].message.content)


def merit_classification_node(state: AppealJudgmentState) -> dict:
    """MG — notice_stage별 참조 법조문을 컨텍스트로 LLM 호출 (DATA-003 §5, §9-2, §9-6).

    (law160-budeuk-hansayu-scope-analysis2.md 확정) 참조 조문은 위반유형과
    무관하게 공통이라 law_code로 라우팅하지 않는다 — MG는 이 고지서 개별
    law_code를 인용하지 않고, 항상 사전에 검증된 고정 조문(law_refs.py)만 LLM
    컨텍스트로 주입한다.

    merit 판단은 항상 1회 호출. merit="강함"일 때만 relief_type(면제/감경) 판단을
    위해 2번째 호출을 추가로 한다 — 한 호출에서 둘 다 물으면 정확도가 떨어지는 게
    실측으로 확인돼 분리했다 ("면제·감경 사유 merit 구분 설계.md" §7 참고).
    """
    reason = state.get("user_appeal_reason") or ""
    notice_stage = state.get("notice_stage")

    law_context = get_merit_context(notice_stage)

    try:
        result = _call_llm_merit(reason, law_context)
        merit = result.get("merit")
        merit_basis = result.get("merit_basis")
    except Exception:
        # LLM 호출·파싱 실패 — MG는 애매해도 "보류"로 안전하게 수렴하도록
        # 설계돼 있으므로(RG와 달리 안전 문제가 아님), 판단 불가도 같은
        # "보류"로 처리한다. merit 값 자체는 새로 안 만들지만, 이 "보류"가
        # 사유를 실제로 검토한 결과가 아니라 기술적 실패의 기본값이라는 걸
        # merit_judgment_failed로 구분해둔다 — guide_generation_node가 이걸로
        # "판단이 애매하다"가 아니라 "판단을 못 했다, 재시도하면 다를 수 있다"고
        # 사실대로 안내해야, 승산 있는 사유를 사용자가 오해로 포기하지 않는다.
        return {
            "merit":                      "보류",
            "merit_basis":                "LLM 판단 실패로 보류 처리",
            "merit_judgment_failed":      True,
            "merit_relief_type":          None,
            "relief_type_judgment_failed": None,  # merit 판정 자체가 실패해 relief_type
                                                    # 호출까지 가지 못했다 — merit_judgment_failed로
                                                    # 이미 원인이 드러나므로 여긴 "적용 대상 아님".
        }

    if merit not in _VALID_MERIT:
        # 모델이 지정한 3개 값 밖의 응답을 낸 경우도 동일하게 보류 처리 —
        # 이 역시 사유를 검토해서 나온 판단이 아니므로 같은 플래그를 세운다.
        merit = "보류"
        merit_judgment_failed = True
        relief_type = None
        relief_type_judgment_failed = None
    elif merit != "강함":
        # 보류/낮음은 relief_type이 애초에 의미 없다 — 추가 호출 없이 바로 None.
        merit_judgment_failed = False
        relief_type = None
        relief_type_judgment_failed = None
    else:
        merit_judgment_failed = False
        # relief_type은 merit="강함"일 때만 의미가 있다(면제 사유 결과 = 처분 자체 불가) —
        # 별도 호출로 판단한다(§ _call_llm_relief_type 주석). 이 호출이 실패해도 이미
        # 확정된 merit="강함" 자체는 취소하지 않는다 — relief_type 세부 구분만 못 하는
        # 것이지, 인정 가능성 판단 자체가 실패한 게 아니기 때문 (merit_judgment_failed는
        # 여기서 건드리지 않는다).
        try:
            relief_result = _call_llm_relief_type(reason, law_context)
            relief_type = relief_result.get("relief_type")
        except Exception:
            relief_type = None

        if relief_type not in _VALID_RELIEF_TYPES:
            # merit="강함"이면 참조 법조문은 항상 면제 또는 감경 중 하나로 확정되므로
            # (RELIEF_TYPE_CLASSIFICATION_PROMPT), 이 시점에 None인 경우는 전부 호출
            # 실패·파싱 실패다 — "구분 불필요"인 정상 케이스가 아니다. RG·MG 1차 호출과
            # 대칭으로 이 실패를 명시적으로 표시해, guide_generation_node가 "감경(확정)"과
            # "구분 미확정(기술 오류)"을 다른 문구로 안내할 수 있게 한다.
            relief_type = None
            relief_type_judgment_failed = True
        else:
            # 별도 호출로도 "미약"류 표현을 계속 면제로 오판할 가능성에 대비해,
            # 알려진 실패 패턴에 한해 키워드 안전장치를 마지막 방어선으로 유지한다.
            relief_type = _downgrade_relief_type_if_hedged(reason, relief_type)
            relief_type_judgment_failed = False

    return {
        "merit":                      merit,
        "merit_basis":                merit_basis,
        "merit_judgment_failed":      merit_judgment_failed,
        "merit_relief_type":          relief_type,
        "relief_type_judgment_failed": relief_type_judgment_failed,
    }
