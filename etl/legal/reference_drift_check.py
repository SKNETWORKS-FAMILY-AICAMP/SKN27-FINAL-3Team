"""appeal_decision_flow가 참조하는 고정 조문번호의 법 개정 드리프트 점검 배치 스크립트.

`ai/agents/appeal_decision_flow/law_refs.py`의 MG(merit_classification_node) 참조 조문
(142조, 질서위반행위규제법 7~10조·14조)은 법률 분석으로 확정한 고정 조문번호를
`get_provision_text(source_name, article_no)`로 exact match 조회한다. 이 방식은 조문
"내용"이 개정돼도(enforce_date 최신본 자동 반영) 문제없지만, 법 개정으로 조문번호
자체가 재편되면(예: 142조가 143조로 밀림) 같은 (source_name, article_no) 키가 더 이상
같은 내용을 가리키지 않게 될 수 있다 — 조회는 "성공"하지만 조용히 엉뚱한 조문을
LLM에 근거로 주입하는 위험한 실패 모드다.

이 스크립트는 law_refs.py의 하드코딩 폴백 원문(마지막으로 사람이 직접 검증한 "정답"
스냅샷)과 법령DB의 현재 원문을 임베딩 코사인 유사도로 비교해, 유사도가 크게 떨어지면
경고한다. 문구만 소폭 개정된 정상적인 경우는 유사도가 여전히 높게 유지되므로, 조문번호
재편처럼 "완전히 다른 내용으로 바뀐" 경우만 선별적으로 잡아낸다.

런타임 판정 경로(law_refs.py)에는 개입하지 않는다 — 탐지 전용이며, 사람이 결과를 보고
law_refs.py 재검토 여부를 판단한다. CI·스케줄러에서 주기 실행하도록 의도했다
(2026-07-13, appeal-judgment 미비점 조사 후속 논의 "법 개정시 db에 있는 조문번호가
바뀔 수 있음" 참고).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from ai.agents.appeal_decision_flow.law_refs import PINNED_REFERENCES
from etl.legal.search import (
    embed_query_with_openai,
    get_provision_text,
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
    article_no: str
    status: str  # "ok" | "missing" | "drifted" | "error"
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

    for source_name, article_no, golden_text in PINNED_REFERENCES:
        try:
            current_text = get_provision_text(source_name, article_no)
        except Exception as exc:
            results.append(DriftResult(source_name, article_no, "error", None, str(exc)))
            continue

        if not current_text:
            results.append(DriftResult(
                source_name, article_no, "missing", None,
                "법령DB에 해당 조문이 없음 — 현재 폴백 원문만으로 운영 중",
            ))
            continue

        try:
            golden_vec = _embed(golden_text)
            current_vec = _embed(f"{source_name} {current_text}")
            similarity = _cosine_similarity(golden_vec, current_vec)
        except Exception as exc:
            results.append(DriftResult(source_name, article_no, "error", None, str(exc)))
            continue

        if similarity < _DRIFT_THRESHOLD:
            results.append(DriftResult(
                source_name, article_no, "drifted", similarity,
                "DB 원문이 검증된 폴백 원문과 크게 다름 — 법 개정으로 조문번호가 재편됐을 "
                "가능성이 있으니 law_refs.py를 재검토하세요",
            ))
        else:
            results.append(DriftResult(source_name, article_no, "ok", similarity))

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
        print(f"[{r.status.upper()}] {r.source_name} {r.article_no} (유사도 {sim_text}) {r.detail}")

    if problems:
        print(f"\n{len(problems)}건 재검토 필요.")
        return 1

    print("\n전부 정상.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
