import json
import re

import openai

from .law_refs import get_merit_context
from .prompts import MERIT_CLASSIFICATION_PROMPT
from .state import AppealJudgmentState

_VALID_MERIT = {"강함", "보류", "낮음"}


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
    raw = response.choices[0].message.content.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise


def merit_classification_node(state: AppealJudgmentState) -> dict:
    """MG — notice_stage별 참조 법조문을 컨텍스트로 LLM 단일 호출 (DATA-003 §5, §9-2, §9-6).

    (law160-budeuk-hansayu-scope-analysis2.md 확정) 참조 조문은 위반유형과
    무관하게 공통이라 law_code로 라우팅하지 않는다 — MG는 이 고지서 개별
    law_code를 인용하지 않고, 항상 사전에 검증된 고정 조문(law_refs.py)만 LLM
    컨텍스트로 주입한다.
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
        # "보류"로 처리한다. 새 상태값을 만들 필요가 없다.
        return {"merit": "보류", "merit_basis": "LLM 판단 실패로 보류 처리"}

    if merit not in _VALID_MERIT:
        # 모델이 지정한 3개 값 밖의 응답을 낸 경우도 동일하게 보류 처리
        merit = "보류"

    return {
        "merit":       merit,
        "merit_basis": merit_basis,
    }
