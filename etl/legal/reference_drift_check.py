"""appeal_decision_flow가 참조하는 필수 RAG 법조문의 검색 드리프트 점검 배치 스크립트.

`ai/agents/appeal_decision_flow/law_refs.py`의 MG(merit_classification_node) 참조 조문
(142조, 질서위반행위규제법 7~10조·14조)은 조문번호가 아니라 검증 기준 원문 자체를
질의로 쓰는 의미 기반(RAG) 검색으로 조회한다(2026-07-15 전환). 제160조4항1호는 청크
분할 문제 때문에 RAG 대상에서 제외하고 검증된 고정 스냅샷을 사용한다. 이 방식은
법 개정으로 조문번호가 재편돼도(예: 142조가 143조로 밀림) 내용 기반으로 계속 같은
조문을 찾아내므로, exact match 방식이 가졌던 "조회는 성공하지만 조용히 엉뚱한 조문을
주입" 위험은 구조적으로 줄어든다. 다만 다음 두 실패 모드는 여전히 남는다:

- 신뢰도 미달로 런타임 판정이 중단됨 (DB 미적재·임베딩 인프라 문제 등)
- 신뢰도는 통과했지만 매칭된 조문 내용이 검증 기준 원문과 실질적으로 달라짐
  (법 개정으로 조문 실체가 바뀌었거나, 우연히 비슷한 다른 조문에 매칭)

이 스크립트는 law_refs.py의 RAG 매칭 함수(_resolve_provision_match)를 그대로 호출해 —
런타임(_fetch_provision_text)과 같은 매칭 로직을 검증하되, LEGAL_PROVISION_DB_ENABLED
게이트는 우회해 게이트 설정과 무관하게 DB 상태 자체를 확인한다 — 반환된 원문과 기준
원문의 임베딩 코사인 유사도를 비교한다. 문구만 소폭 개정된 정상적인 경우는 유사도가
여전히 높게 유지되므로, "완전히 다른 내용으로 바뀐" 경우만 선별적으로 잡아낸다.

런타임 판정 경로(law_refs.py)에는 개입하지 않는다 — 탐지 전용이며, 사람이 결과를 보고
law_refs.py 재검토 여부를 판단한다. CI·스케줄러에서 주기 실행하도록 의도했다
(2026-07-13, appeal-judgment 미비점 조사 후속 논의 "법 개정시 db에 있는 조문번호가
바뀔 수 있음" 참고).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from ai.agents.appeal_decision_flow.law_refs import REQUIRED_RAG_REFERENCES, _resolve_provision_match
from etl.legal.search import (
    embed_query_with_openai,
    infer_embedding_dimensions,
    infer_embedding_model,
)

# 이 미만이면 "재편으로 다른 내용이 들어왔을 가능성"으로 판단한다. 소폭 문구 개정은
# 임베딩 유사도가 통상 0.9 이상으로 유지되므로, 0.75는 오탐 없이 "완전히 다른 조문
# 내용"만 걸러내기 위한 보수적인 값이다 — 실측으로 조정 가능.
_DRIFT_THRESHOLD = 0.75

# law_embeddings 테이블·search_laws()가 쓰는 것과 같은 임베딩 공간이어야 비교가
# 의미 있다 — provider·dimensions를 동일하게 고정한다.
_EMBEDDING_METADATA = {"embedding_provider": "openai", "embedding_dimensions": 1024}


@dataclass
class DriftResult:
    source_name: str
    golden_preview: str  # 검증 기준 원문 앞부분(로그 식별용) — article_no 같은 안정적 키가 더 이상 없다
    status: str  # "ok" | "unavailable" | "drifted" | "error"
    similarity: float | None
    detail: str = ""


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """embed_query_with_openai가 이미 L2 정규화된 벡터를 반환하므로 내적이 곧 코사인 유사도다."""
    return sum(x * y for x, y in zip(a, b))


def _embed(text: str) -> list[float]:
    return embed_query_with_openai(
        text,
        model_id=infer_embedding_model(_EMBEDDING_METADATA),
        dimensions=infer_embedding_dimensions(_EMBEDDING_METADATA),
    )


def check_reference_drift() -> list[DriftResult]:
    results: list[DriftResult] = []

    for source_name, golden_text in REQUIRED_RAG_REFERENCES:
        preview = golden_text.splitlines()[0][:40]

        try:
            match = _resolve_provision_match(source_name, golden_text)
        except Exception as exc:
            results.append(DriftResult(source_name, preview, "error", None, str(exc)))
            continue

        if match is None:
            results.append(DriftResult(
                source_name, preview, "unavailable", None,
                "RAG 검색이 신뢰도 기준을 못 넘겼거나 source_name이 일치하는 매칭이 없음 — "
                "런타임 판정은 필수 법령 근거 미확보로 중단됨",
            ))
            continue

        resolved_text = f"{source_name} {match.get('provision_text', '')}"

        try:
            golden_vec = _embed(golden_text)
            resolved_vec = _embed(resolved_text)
            similarity = _cosine_similarity(golden_vec, resolved_vec)
        except Exception as exc:
            results.append(DriftResult(source_name, preview, "error", None, str(exc)))
            continue

        if similarity < _DRIFT_THRESHOLD:
            results.append(DriftResult(
                source_name, preview, "drifted", similarity,
                "RAG 매칭 원문이 검증 기준 원문과 크게 다름 — 법 개정으로 조문 실체가 "
                "바뀌었거나 엉뚱한 조문에 매칭됐을 가능성이 있으니 law_refs.py를 재검토하세요",
            ))
        else:
            results.append(DriftResult(source_name, preview, "ok", similarity))

    return results


def main() -> int:
    # Windows 콘솔 기본 코드페이지(cp949)는 "—" 같은 문자를 인코딩하지 못해, 이 스크립트가
    # 실전 실행 중(로컬 DB 미기동 상태) 실제로 UnicodeEncodeError로 죽는 게 확인됐다 —
    # stdout을 UTF-8로 재설정해 결과 메시지가 항상 출력되도록 보장한다.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass  # 일부 환경(예: stdout이 파이프로 리다이렉트된 경우)엔 reconfigure가 없을 수 있음

    results = check_reference_drift()
    problems = [r for r in results if r.status != "ok"]

    for r in results:
        sim_text = f"{r.similarity:.3f}" if r.similarity is not None else "-"
        print(f"[{r.status.upper()}] {r.source_name} {r.golden_preview}... (유사도 {sim_text}) {r.detail}")

    if problems:
        print(f"\n{len(problems)}건 재검토 필요.")
        return 1

    print("\n전부 정상.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
