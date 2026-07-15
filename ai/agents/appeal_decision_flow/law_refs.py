"""MG(merit_classification_node)·RG(risk_classification_node)가 참조하는 법조문 원문.

운영 MG 컨텍스트는 법령DB(law_chunks)에서 확인된 조문만 사용한다. DB 비활성화·조회
오류·미적재 시에는 하드코딩 원문을 주입하지 않고 evidence-unavailable로 실패 폐쇄한다.
아래 하드코딩 상수는 드리프트 검사와 테스트의 golden snapshot으로만 유지한다.
원문 출처·적용범위 검증 근거는
`docs/architecture/appeal-judgment/law160-budeuk-hansayu-scope-analysis2.md` 참고
(구 버전 `법조문_참고자료_142조_14조.md`·`...analysis.md`의 "142조=주정차 전용" 전제는
이 v2 재검증으로 폐기됨).
"""

import logging
import os


logger = logging.getLogger(__name__)

# ── 검증용 golden snapshot (운영 LLM 컨텍스트에 사용 금지) ────────────

# 도로교통법 시행규칙 제142조(부득이한 사유)
# 위임 근거: 도로교통법 제160조제4항제1호 "그 밖의 부득이한 사유"
# 적용범위: 위반유형 무관 공통 적용 — §160④는 "§160③에도 불구하고"로 §160③
# 전체(1호 주정차·전용차로·긴급차량 + 2호 범칙금통고 불가 전반=속도위반·신호위반
# 등 무인단속)에 걸리는 예외라, 142조 문언에도 주정차 한정 문구가 없다
# (law160-budeuk-hansayu-scope-analysis2.md §4 확정).
_FALLBACK_RULE_142_TEXT = """\
도로교통법 시행규칙 제142조(부득이한 사유)
「도로교통법」제160조제4항제1호에서 "그 밖의 부득이한 사유"란 해당 위반행위가 다음 각 호의
어느 하나에 해당하는 경우를 말한다.
1. 범죄의 예방·진압이나 그 밖에 긴급한 사건·사고의 조사를 위한 경우
2. 도로공사 또는 교통지도단속을 위한 경우
3. 응급환자의 수송 또는 치료를 위한 경우
4. 화재·수해·재해 등의 구난작업을 위한 경우
5. 「장애인복지법」에 따른 장애인의 승·하차를 돕는 경우
6. 그 밖에 부득이한 사유라고 인정할 만한 상당한 이유가 있는 경우"""

# 도로교통법 제160조제4항제1호 본문 (도난 포함)
# 142조 목록과 별개로, "도난"은 이 본문에 부득이한 사유와 병렬로 직접 명시돼 있다.
# 142조 목록만 주입하면 도난 사례를 놓치므로 위반유형 무관하게 이것도 함께 주입한다.
_FALLBACK_ARTICLE_160_4_1_TEXT = """\
도로교통법 제160조제4항제1호
제3항에도 불구하고 차를 도난당하였거나 그 밖의 부득이한 사유가 있는 경우에는
과태료 처분을 할 수 없다."""

# 질서위반행위규제법 제7~10조(질서위반행위의 성립 등 — 일반 면책·감경 사유)
# 위반유형과 무관하게 모든 과태료(질서위반행위)에 보편 적용되는 일반 원칙들.
# 142조(구체적 열거 목록)와 양자택일이 아니라, 142조 6개 항목에 해당하지 않는
# 경우의 보충 근거로 위반유형 무관하게 항상 함께 주입한다.
# (2026-07-08 발견) 그래프DB 텍스트 매칭으로 "질서위반행위규제법 중 과태료 관련 조문"을
# 전수 조사한 결과, 이미 참조 중인 7조(고의·과실)와 같은 장(제2장 질서위반행위의 성립 등)에
# 속한 8·9·10조가 MG 참조 목록에서 빠져있었다 — "표지판이 안 보였다"류 사유는 7조보다
# 8조(위법성의 착오)가 더 정확한 근거일 수 있는데도 지금까지 LLM에게 8조 원문 자체를
# 보여준 적이 없었다. 상세는
# `docs/architecture/appeal-judgment/오늘 한 일 제8조~10조 merit변경.md` 참고.
_FALLBACK_ARTICLE_7_TEXT = """\
질서위반행위규제법 제7조(고의 또는 과실)
고의 또는 과실이 없는 질서위반행위는 과태료를 부과하지 아니한다."""

_FALLBACK_ARTICLE_8_TEXT = """\
질서위반행위규제법 제8조(위법성의 착오)
자신의 행위가 위법하지 아니한 것으로 오인하고 행한 질서위반행위는 그 오인에 정당한
이유가 있는 때에 한하여 과태료를 부과하지 아니한다."""

_FALLBACK_ARTICLE_9_TEXT = """\
질서위반행위규제법 제9조(책임연령)
14세가 되지 아니한 자의 질서위반행위는 과태료를 부과하지 아니한다. 다만, 다른
법률에 특별한 규정이 있는 경우에는 그러하지 아니하다."""

_FALLBACK_ARTICLE_10_TEXT = """\
질서위반행위규제법 제10조(심신장애)
① 심신(心神)장애로 인하여 행위의 옳고 그름을 판단할 능력이 없거나 그 판단에 따른
행위를 할 능력이 없는 자의 질서위반행위는 과태료를 부과하지 아니한다.
② 심신장애로 인하여 제1항에 따른 능력이 미약한 자의 질서위반행위는 과태료를 감경한다.
③ 스스로 심신장애 상태를 일으켜 질서위반행위를 한 자에 대하여는 제1항 및 제2항을
적용하지 아니한다."""

# 질서위반행위규제법 제14조(과태료의 산정)
# 위반유형 무관 공통 적용. 1차 고지서(법원 비송사건절차) 단계의 정황요소 판단에 추가 주입.
_FALLBACK_ARTICLE_14_TEXT = """\
질서위반행위규제법 제14조(과태료의 산정)
행정청 및 법원은 과태료를 정함에 있어서 다음 각 호의 사항을 고려하여야 한다.
1. 질서위반행위의 동기·목적·방법·결과
2. 질서위반행위 이후의 당사자의 태도와 정황
3. 질서위반행위자의 연령·재산상태·환경
4. 그 밖에 과태료의 산정에 필요하다고 인정되는 사유"""

# ── DB 조회 대상 고정 조문 목록 (etl/legal/reference_drift_check.py가 참조) ──
# get_merit_context()가 실제로 _fetch_provision_text로 조회하는 (법령명, 조문번호,
# 검증된 golden snapshot) 조합을 한곳에 모아둔다 — 법 개정으로 조문번호가 재편되면(예: 142조가
# 143조로 밀림) law_chunks의 해당 article_no 값이 더 이상 이 원문과 같은 내용을
# 가리키지 않게 될 수 있다. 여기 나열된 원문은 마지막으로 사람이 직접 검증한
# "정답" 스냅샷이라, 드리프트 점검 스크립트가 DB 현재 원문과의 임베딩 유사도를 비교하는
# 기준으로 재사용한다. 제160조는 조 단위 조회 결과에 필요한 제4항제1호 문구가 포함됐는지
# 런타임에서도 별도로 검증한다.
PINNED_REFERENCES: list[tuple[str, str, str]] = [
    ("도로교통법", "제160조", _FALLBACK_ARTICLE_160_4_1_TEXT),
    ("도로교통법 시행규칙", "제142조", _FALLBACK_RULE_142_TEXT),
    ("질서위반행위규제법", "제7조", _FALLBACK_ARTICLE_7_TEXT),
    ("질서위반행위규제법", "제8조", _FALLBACK_ARTICLE_8_TEXT),
    ("질서위반행위규제법", "제9조", _FALLBACK_ARTICLE_9_TEXT),
    ("질서위반행위규제법", "제10조", _FALLBACK_ARTICLE_10_TEXT),
    ("질서위반행위규제법", "제14조", _FALLBACK_ARTICLE_14_TEXT),
]


# ── 질서위반행위규제법 제20조 (이의제기 기한) ─────────────────────────
# deadline_gate_node가 쓰는 하드코딩 상수. 기산일은 "받은 날"(수령일, 도달주의) — 발송일 아님.
# (DATA-003 §9) 조문 원문이 아니라 계산 로직에 박힌 숫자 상수라 LDB 조회 대상이 아니다 —
# 별도 수동 검토 대상으로 남겨둔다.
APPEAL_DEADLINE_DAYS = 60
APPEAL_DEADLINE_BASIS = (
    "질서위반행위규제법 제20조제1항 — "
    "과태료 부과 통지를 받은 날부터 60일 이내 서면 이의제기"
)


class LegalProvisionEvidenceUnavailable(RuntimeError):
    """Sanitized fail-closed signal for required legal provision evidence."""

    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _fetch_provision_text(source_name: str, article_no: str) -> str:
    """Load a required provision from the legal DB with explicit provenance."""
    if os.environ.get("LEGAL_PROVISION_DB_ENABLED", "0").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise LegalProvisionEvidenceUnavailable("legal_provision_db_disabled")

    try:
        from etl.legal.search import get_provision_text

        text = get_provision_text(source_name, article_no)
    except Exception as exc:
        logger.warning(
            "Required law reference lookup failed error_class=%s",
            exc.__class__.__name__,
        )
        raise LegalProvisionEvidenceUnavailable(
            "legal_provision_lookup_failed"
        ) from None
    text = str(text or "").strip()
    if not text:
        raise LegalProvisionEvidenceUnavailable("legal_provision_not_found")
    if article_no == "\uc81c160\uc870" and not all(
        marker in text for marker in ("\ub3c4\ub09c", "\ubd80\ub4dd\uc774\ud55c \uc0ac\uc720")
    ):
        raise LegalProvisionEvidenceUnavailable("legal_provision_incomplete")
    return (
        f"[source={source_name}; article={article_no}; "
        f"provenance=legal_provision_db]\n{text}"
    )


def get_merit_context(notice_stage: str) -> str:
    """MG(merit_classification_node)가 LLM에 주입할 참조 법조문 컨텍스트를 조립한다.

    (law160-budeuk-hansayu-scope-analysis2.md 확정) 142조는 §160④1호("부득이한
    사유")의 정의 조항이고, §160④는 §160③ 전체(주정차+비주정차)에 적용되는
    예외라 위반유형 무관하게 공통 1차 검토 대상이다. 질서법 제7조는 142조 미해당
    시 보조적으로 병존 적용되는 일반원칙이라 양자택일하지 않고 항상 함께 넣는다.
    이전 버전(analysis.md)의 law_code 기반 주정차/비주정차 배타적 라우팅 전제는
    v2 재검증으로 폐기됐다.

    (2026-07-08) 질서법 8·9·10조(위법성의 착오·책임연령·심신장애)도 7조와 같은 장
    (제2장 질서위반행위의 성립 등)에 속한 일반 면책·감경 사유라 함께 주입한다 — 상세는
    `docs/architecture/appeal-judgment/오늘 한 일 제8조~10조 merit변경.md` 참고.

        사전통지   → 160조4항1호 + 142조 + 제7~10조
        1차 고지서 → 160조4항1호 + 142조 + 제7~10조 + 제14조
    """
    parts = [
        _fetch_provision_text("도로교통법", "제160조"),
        _fetch_provision_text("도로교통법 시행규칙", "제142조"),
        _fetch_provision_text("질서위반행위규제법", "제7조"),
        _fetch_provision_text("질서위반행위규제법", "제8조"),
        _fetch_provision_text("질서위반행위규제법", "제9조"),
        _fetch_provision_text("질서위반행위규제법", "제10조"),
    ]

    if notice_stage == "1차 고지서":
        parts.append(_fetch_provision_text("질서위반행위규제법", "제14조"))

    return "\n\n".join(parts)
