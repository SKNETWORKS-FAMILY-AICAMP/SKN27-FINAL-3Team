import json
import re
from typing import Optional

import openai

from .prompts import RISK_CLASSIFICATION_PROMPT
from .state import AppealJudgmentState

# ── 0단계: 도난 예외 — 카테고리 A보다 먼저 체크 (DATA-003 §8) ────────
# 성공(입증)·실패(입증 못함) 무관하게 아무에게도 범칙금 전환 위험이 없다.
_THEFT_KEYWORDS = ["도둑", "도난", "훔쳐", "도난당", "절도"]

# ── 1단계: 고신뢰 키워드 매칭 (세 카테고리, A/B가 C보다 우선) ────────
_CATEGORY_A_KEYWORDS = [  # 제3자 운전 주장
    "다른 사람이 운전", "다른사람이 운전", "제가 운전하지 않았", "제가 몰지 않았",
    "지인이 운전", "친구가 운전", "가족이 운전", "아내가 운전", "남편이 운전",
]
_CATEGORY_B_KEYWORDS = [  # 명시적 전환 요청
    "범칙금으로 전환", "범칙금 전환",
]
_CATEGORY_C_KEYWORDS = [  # 본인 운전 인정형 — 142조 1~5호 대응 시드
    "긴급 상황", "범죄를 막으려고", "사건을 신고하려고",     # 1호
    "도로공사 중", "교통정리를 돕", "교통지도단속",           # 2호
    "응급환자", "환자를 이송", "응급실로",                    # 3호
    "화재 현장", "구조작업", "수해 복구",                     # 4호
    "장애인 승하차", "장애인을 돕",                           # 5호
]

_CATEGORY_LABELS = {
    "A": "A_제3자운전주장",
    "B": "B_명시적전환요청",
    "C": "C_본인운전인정형",
}
_CONFIDENCE_SCORE = {"high": 0.9, "medium": 0.6, "low": 0.2}


def _match_any(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


def _call_llm_classifier(reason: str) -> dict:
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=256,
        temperature=0,
        messages=[{"role": "user", "content": RISK_CLASSIFICATION_PROMPT.format(reason=reason)}],
    )
    raw = response.choices[0].message.content.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise


def risk_classification_node(state: AppealJudgmentState) -> dict:
    """RG — 0단계 도난 예외 → 1단계 키워드(A/B/C) → 2단계 LLM (DATA-003 §8).

    카테고리 C의 표현 범위(142조 vs 14조 정황요소)는 notice_stage에 따라 갈리지만
    (§9-4), 1단계 키워드는 142조 1~5호 시드만 다루고 그 외 표현은 2단계 LLM
    프롬프트가 notice_stage와 무관하게 "본인 운전 전제 정황 진술" 기준으로 함께
    판단하므로, 이 구현은 notice_stage를 직접 분기하지 않는다.
    """
    reason = state.get("user_appeal_reason") or ""

    # ── 0단계: 도난 예외 ──────────────────────────────────────────────
    if _match_any(reason, _THEFT_KEYWORDS):
        return {
            "risk_flag":             False,
            "risk_stage_matched":    "keyword",
            "risk_trigger_category": None,
        }

    # ── 1단계: 카테고리 A/B/C 키워드 매칭 ─────────────────────────────
    matched_category: Optional[str] = None
    if _match_any(reason, _CATEGORY_A_KEYWORDS):
        matched_category = "A"
    elif _match_any(reason, _CATEGORY_B_KEYWORDS):
        matched_category = "B"
    elif _match_any(reason, _CATEGORY_C_KEYWORDS):
        matched_category = "C"

    if matched_category is not None:
        return {
            "risk_flag":             True,
            "risk_stage_matched":    "keyword",
            "risk_trigger_category": _CATEGORY_LABELS[matched_category],
        }

    # ── 2단계: LLM 구조화 분류 ─────────────────────────────────────────
    # category 하나로만 위험 여부를 판단한다 — is_identity_related을 별도
    # 필드로 함께 물으면 모델이 두 판단을 독립적으로 내려 서로 모순되는
    # 응답(category=A인데 is_identity_related=false 등)을 낼 수 있음이
    # 실제 API 호출 테스트로 확인됐다. category만 신뢰한다.
    try:
        result = _call_llm_classifier(reason)
        confidence = result.get("confidence")
        category = result.get("category")
    except Exception:
        # LLM 호출·파싱 실패(네트워크 오류·레이트리밋·잘못된 응답 등) — 재현율 우선
        # 원칙에 따라 "판단 불가"를 안전이 아니라 위험 쪽으로 보수적 처리한다.
        # 놓쳤을 때(false negative) 실제 불이익으로 이어지는 안전 문제이기 때문이다.
        return {
            "risk_flag":             True,
            "risk_stage_matched":    "llm",
            "risk_confidence":       None,
            "risk_trigger_category": None,
        }

    # 재현율 우선: confidence가 "low"로 명시적으로 확인된 경우에만 안전 처리.
    # confidence가 예상 밖 값(모델 오응답 등)이면 "low"가 아니므로 위험 쪽으로
    # 폴백한다 — category in ("high","medium")만 확인하면 예상 밖 값이 조용히
    # 안전 판정으로 새는 문제가 있었다.
    risk_flag = category is not None and confidence != "low"

    return {
        "risk_flag":             risk_flag,
        "risk_stage_matched":    "llm",
        "risk_confidence":       _CONFIDENCE_SCORE.get(confidence),
        "risk_trigger_category": _CATEGORY_LABELS.get(category) if risk_flag else None,
    }
