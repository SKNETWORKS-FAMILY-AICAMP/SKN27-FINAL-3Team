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
        # "보류"로 처리한다. merit 값 자체는 새로 안 만들지만, 이 "보류"가
        # 사유를 실제로 검토한 결과가 아니라 기술적 실패의 기본값이라는 걸
        # merit_judgment_failed로 구분해둔다 — guide_generation_node가 이걸로
        # "판단이 애매하다"가 아니라 "판단을 못 했다, 재시도하면 다를 수 있다"고
        # 사실대로 안내해야, 승산 있는 사유를 사용자가 오해로 포기하지 않는다.
        return {
            "merit":                 "보류",
            "merit_basis":           "LLM 판단 실패로 보류 처리",
            "merit_judgment_failed": True,
        }

    if merit not in _VALID_MERIT:
        # 모델이 지정한 3개 값 밖의 응답을 낸 경우도 동일하게 보류 처리 —
        # 이 역시 사유를 검토해서 나온 판단이 아니므로 같은 플래그를 세운다.
        merit = "보류"
        merit_judgment_failed = True
    else:
        merit_judgment_failed = False

    return {
        "merit":                 merit,
        "merit_basis":           merit_basis,
        "merit_judgment_failed": merit_judgment_failed,
    }
