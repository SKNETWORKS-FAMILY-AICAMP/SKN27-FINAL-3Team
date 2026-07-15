"""MG(merit_classification_node)·RG(risk_classification_node)가 참조하는 법조문 원문.

법령DB(law_chunks)를 내용 기반 검색(law_ground_search의 RAG 파이프라인, search_law_provisions)
으로 조회하는 게 우선이고, 조회 실패(DB 연결 오류 등)·신뢰도 미달·해당 조문이 아직
적재되지 않은 경우에만 아래 하드코딩 상수로 폴백한다 — 법령DB가 항상 최신본을 반영하지만,
일시적으로 접근이 안 될 때 MG가 컨텍스트 없이 판단하는 사태는 막는다.

(2026-07-15) 기존에는 (법령명, 조문번호) exact match로 조회했으나, 법 개정으로 조문번호가
재편되면(예: 142조가 143조로 밀림) 같은 키가 더 이상 같은 내용을 가리키지 않아 "조회는
성공하지만 조용히 엉뚱한 조문을 주입"하는 위험이 있었다. 이제는 조문번호 대신 폴백 원문
자체를 검색 질의로 써서 의미 기반(임베딩 유사도) 검색을 하므로, 조문번호가 바뀌어도
내용이 비슷하면 계속 올바른 조문을 찾는다 — 검색 결과의 source_name이 기대값과 다르거나
신뢰도(evaluate_confidence)가 기준치 미만이면 폴백으로 떨어진다.

(2026-07-15, 같은 날 되돌림) 단, 도로교통법 제160조제4항제1호는 RAG 대상에서 다시
제외했다 — 실측(A/B 비교)으로 확인된 이유는
`docs/architecture/appeal-judgment/기능_폐기_결정_히스토리.md` ⑤번 참고. 요약하면 제160조가
①~④항을 다 담은 긴 조문이라, ETL의 길이 기반 분할(`etl/legal/ingestion/parser.py`의
`split_long_text`)이 항 경계를 무시하고 ③항(무관한 열거)과 ④항(우리가 원하는 내용)을 한
청크에 섞어버린다. 이 청크로 RAG 검색을 하면 신뢰도(0.65)는 임계값을 넘기지만, 실제
LLM 호출에서 merit_basis가 "제160조제4항제1호" 대신 청크에 섞인 "제11조제4항"과 뒤섞여
"제11조제4항제1호"라는 존재하지 않는 조합을 인용하는 오류가 실측으로 재현됐고, 검증 안 된
④항2~4호(운전자 확인된 경우 등)가 노출되면서 판정 자체도 달라지는 사례까지 나왔다. 142조·
질서법 7~10·14조는 조문 자체가 짧아 이 문제가 없다(청크가 항 경계 없이도 조문 하나 =
청크 하나로 깔끔하게 맞아떨어짐, 실측 스코어 0.92~0.96) — 그래서 이 여섯 개만 RAG를 유지하고
160조4항1호만 예전처럼 영구 하드코딩 폴백 전용으로 되돌렸다.

원문 출처·적용범위 검증 근거는
`docs/architecture/appeal-judgment/law160-budeuk-hansayu-scope-analysis2.md` 참고
(구 버전 `법조문_참고자료_142조_14조.md`·`...analysis.md`의 "142조=주정차 전용" 전제는
이 v2 재검증으로 폐기됨).
"""

import logging
import os

from ai.agents.law_ground_search.search import evaluate_confidence, search_law_provisions


logger = logging.getLogger(__name__)

# ── 폴백 원문 (DB 조회 실패·신뢰도 미달 시 사용 — 동시에 RAG 검색 질의문으로도 재사용) ──

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
#
# (2026-07-15) 이 조문은 PINNED_REFERENCES에 넣지 않고 get_merit_context()에서 RAG 없이
# 이 상수를 직접 쓴다 — 제160조가 ①~④항을 다 포함한 긴 조문이라 ETL 길이 분할이 항 경계를
# 무시하고 ③항(무관한 열거)과 한 청크에 섞어버려, RAG로 조회하면 신뢰도는 통과해도 LLM이
# 섞여든 다른 항 번호를 조문 인용에 잘못 섞어 쓰는 오류가 실측으로 확인됐다. 상세는
# `docs/architecture/appeal-judgment/기능_폐기_결정_히스토리.md` ⑤번 참고.
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

# ── RAG 조회 대상 고정 참조 목록 (etl/legal/reference_drift_check.py가 참조) ──
# get_merit_context()가 실제로 _fetch_provision_text로 조회하는 (법령명, 검증된 폴백 원문)
# 조합을 한곳에 모아둔다. 폴백 원문은 마지막으로 사람이 직접 검증한 "정답" 스냅샷이자,
# 동시에 의미 기반 검색의 질의문으로도 재사용된다 — 조문번호를 조회 키로 쓰지 않으므로
# 법 개정으로 조문번호가 재편돼도 이 목록을 갱신할 필요가 없다. 드리프트 점검 스크립트가
# 검색 결과와 이 폴백 원문의 임베딩 유사도를 비교하는 기준으로 재사용한다.
#
# 도로교통법 제160조제4항제1호는 이 목록에서 제외한다 — RAG로 조회하면 ETL 길이 분할이
# 항 경계를 무시해 섞인 청크 때문에 신뢰도는 통과하지만 LLM이 잘못된 조문 인용을 만들어내는
# 문제가 실측으로 확인됐다(_FALLBACK_ARTICLE_160_4_1_TEXT 주석,
# `기능_폐기_결정_히스토리.md` ⑤번 참고). get_merit_context()가 이 상수를 RAG 없이 직접 쓴다.
PINNED_REFERENCES: list[tuple[str, str]] = [
    ("도로교통법 시행규칙", _FALLBACK_RULE_142_TEXT),
    ("질서위반행위규제법", _FALLBACK_ARTICLE_7_TEXT),
    ("질서위반행위규제법", _FALLBACK_ARTICLE_8_TEXT),
    ("질서위반행위규제법", _FALLBACK_ARTICLE_9_TEXT),
    ("질서위반행위규제법", _FALLBACK_ARTICLE_10_TEXT),
    ("질서위반행위규제법", _FALLBACK_ARTICLE_14_TEXT),
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
    """필수 법령 근거를 신뢰할 수 있는 RAG 결과로 확보하지 못한 상태."""

    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _resolve_provision_match(source_name: str, golden_text: str) -> dict | None:
    """golden_text와 내용이 가장 유사한 (source_name) 조문을 RAG로 찾아 매칭 결과를 반환한다.

    신뢰도 미달이거나 검색 결과 중 source_name이 일치하는 게 없으면 None. 예외는 삼키지
    않고 그대로 전파한다 — 호출자가 각자의 정책대로 처리한다(_fetch_provision_text는
    런타임이라 그레이스풀 디그레이드, etl/legal/reference_drift_check.py는 점검 스크립트라
    "error" 상태로 구분해서 보고). LEGAL_PROVISION_DB_ENABLED 게이트는 여기서 보지 않는다 —
    그 게이트는 런타임에서 RAG 조회 자체를 켤지 말지 결정하는 관심사이고, 드리프트 점검처럼
    게이트 설정과 무관하게 DB 상태를 직접 확인해야 하는 호출자도 있다.
    """
    provisions = search_law_provisions(
        query_text=golden_text,
        article_refs=[],
        temporal_basis={},
        scope={},
    )
    matches = [p for p in provisions if p.get("source_name") == source_name]
    confidence = evaluate_confidence(matches)
    if not confidence["is_confident"]:
        return None
    return matches[0]


def _fetch_provision_text(source_name: str, golden_text: str) -> str:
    """golden_text와 내용이 가장 유사한 조문을 법령DB에서 의미 기반(RAG) 검색으로 조회하고,
    신뢰할 수 있는 결과를 확보하지 못하면 명시적으로 실패한다.

    조문번호가 아니라 golden_text(검증된 기준 원문) 자체를 검색 질의로 써서, 법 개정으로
    조문번호가 재편돼도(예: 142조→143조) 내용 기반으로 계속 올바른 조문을 찾는다. 검색
    결과의 source_name이 기대값과 다르면(엉뚱한 법의 비슷한 문구에 매칭) 신뢰하지 않고
    판정을 중단한다. 검증 스냅샷을 직접 쓰는 예외는 제160조제4항제1호뿐이다.
    """
    if os.environ.get("LEGAL_PROVISION_DB_ENABLED", "0").strip().lower() not in {"1", "true", "yes"}:
        raise LegalProvisionEvidenceUnavailable("legal_provision_db_disabled")

    try:
        match = _resolve_provision_match(source_name, golden_text)
    except Exception as exc:
        logger.warning(
            "Required law reference RAG lookup failed; error_class=%s",
            exc.__class__.__name__,
        )
        raise LegalProvisionEvidenceUnavailable("legal_provision_lookup_failed") from None

    if match is None:
        raise LegalProvisionEvidenceUnavailable("legal_provision_low_confidence_or_not_found")

    text = match.get("provision_text")
    if not text:
        raise LegalProvisionEvidenceUnavailable("legal_provision_not_found")
    return f"[source={source_name}; provenance=legal_rag]\n{text}"


def _pinned_article_160_context() -> str:
    """청크 혼합이 확인된 제160조제4항제1호만 검증 스냅샷으로 제공한다."""
    return (
        "[source=도로교통법; article=제160조제4항제1호; "
        "provenance=pinned_verified_snapshot; verified_at=2026-07-15]\n"
        f"{_FALLBACK_ARTICLE_160_4_1_TEXT}"
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
        # RAG 대상에서 제외 — _FALLBACK_ARTICLE_160_4_1_TEXT 주석 참고.
        _pinned_article_160_context(),
        _fetch_provision_text("도로교통법 시행규칙", _FALLBACK_RULE_142_TEXT),
        _fetch_provision_text("질서위반행위규제법", _FALLBACK_ARTICLE_7_TEXT),
        _fetch_provision_text("질서위반행위규제법", _FALLBACK_ARTICLE_8_TEXT),
        _fetch_provision_text("질서위반행위규제법", _FALLBACK_ARTICLE_9_TEXT),
        _fetch_provision_text("질서위반행위규제법", _FALLBACK_ARTICLE_10_TEXT),
    ]

    if notice_stage == "1차 고지서":
        parts.append(_fetch_provision_text("질서위반행위규제법", _FALLBACK_ARTICLE_14_TEXT))

    return "\n\n".join(parts)
