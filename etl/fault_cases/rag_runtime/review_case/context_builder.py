"""심의사례 청크를 BGE 평가와 같은 전체 사례 문맥으로 조합한다."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any


SECTION_ORDER = (
    ("case_overview", "[CASE_OVERVIEW]"),
    ("arguments", "[ARGUMENTS]"),
    ("evidence_issue", "[EVIDENCE_ISSUE]"),
    ("decision", "[DECISION]"),
)


def build_case_context(
    candidate: dict[str, Any],
    chunks: Sequence[dict[str, Any]],
) -> str:
    sections: dict[str, list[str]] = defaultdict(list)
    for chunk in chunks:
        chunk_type = str(chunk.get("chunk_type") or "")
        chunk_text = str(chunk.get("chunk_text") or "").strip()
        if chunk_text:
            sections[chunk_type].append(chunk_text)

    blocks: list[str] = []
    for chunk_type, heading in SECTION_ORDER:
        texts = sections.get(chunk_type)
        if not texts:
            return str(candidate.get("evidence_text") or "")
        blocks.append(f"{heading}\n" + "\n".join(texts))
    return "\n\n".join(blocks)
