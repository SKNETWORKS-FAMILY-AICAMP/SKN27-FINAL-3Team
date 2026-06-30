"""기준정보 게시글과 첨부파일의 문서유형 후보 점수화 모듈.

게시글 제목은 나중에 바뀔 수 있으므로 제목 하나만 믿지 않는다.
게시글 제목, 첨부파일명, 상세페이지 텍스트를 합쳐서 기준 PDF 후보인지 점수화한다.
"""

import hashlib
# re는 공백과 특수문자를 정규화하기 위해 사용한다.
import re

# Optional은 문서유형이 없을 수도 있음을 표현한다.
from typing import Optional

from ..config import NEGATIVE_KEYWORD_SCORES, POSITIVE_KEYWORD_SCORES, SCORING_CONFIG


# normalize_text 함수는 비교를 쉽게 하기 위해 텍스트에서 공백과 일부 기호를 제거한다.
def normalize_text(text: str) -> str:
    # None이 들어와도 빈 문자열로 처리한다.
    text = text or ""
    # 영문 대소문자 차이를 줄이기 위해 대문자로 통일한다.
    text = text.upper()
    # 공백, 밑줄, 하이픈, 괄호 등을 제거해 키워드 매칭을 안정화한다.
    text = re.sub(r"[\s_\-()\[\]{}·.,/]+", "", text)
    # 정규화된 문자열을 반환한다.
    return text


def make_dynamic_document_type(text: str) -> str:
    normalized = normalize_text(text)
    year_match = re.search(r"20\d{2}", text or "")
    year_part = year_match.group(0) if year_match else "unknown_year"
    short_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    return f"fault_standard_{year_part}_{short_hash}"


# score_document_type 함수는 텍스트를 보고 가장 가능성 높은 문서유형을 찾는다.
def score_document_type(title: str, filename: str = "", detail_text: str = "") -> dict:
    # 제목, 파일명, 상세페이지 본문을 하나로 합친다.
    combined = f"{title} {filename} {detail_text}"
    # 합친 텍스트를 키워드 비교용으로 정규화한다.
    normalized = normalize_text(combined)
    score = 0
    matched = []
    for keyword, point in POSITIVE_KEYWORD_SCORES.items():
        normalized_keyword = normalize_text(keyword)
        if normalized_keyword in normalized:
            score += point
            matched.append(keyword)
    for keyword, point in NEGATIVE_KEYWORD_SCORES.items():
        normalized_keyword = normalize_text(keyword)
        if normalized_keyword in normalized:
            score += point
            matched.append(f"NEGATIVE:{keyword}")
    if any(marker in combined.upper() for marker in SCORING_CONFIG["attachment_markers"]):
        score += SCORING_CONFIG["attachment_bonus"]
    best = {
        "document_type": make_dynamic_document_type(combined),
        "score": score,
        "matched_keywords": matched,
    }
    # 100점을 기준으로 하되 1.0을 넘지 않게 신뢰도를 계산한다.
    confidence = min(max(best["score"], 0) / SCORING_CONFIG["confidence_denominator"], 1.0)
    # 50점 미만이면 문서유형을 확정하지 않는다.
    document_type: Optional[str] = best["document_type"] if best["score"] >= SCORING_CONFIG["confirmation_threshold"] else None
    # 후보 점수화 결과를 반환한다.
    return {
        "document_type_candidate": document_type,
        "document_type_confidence": confidence,
        "matched_keywords": best["matched_keywords"],
        "all_scores": [best],
    }
