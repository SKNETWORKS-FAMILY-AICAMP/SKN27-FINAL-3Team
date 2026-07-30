from __future__ import annotations

from typing import Any


def _candidate() -> dict[str, Any]:
    return {
        "document_id": "review_case_2019_008384",
        "evidence_text": "검색된 대표 청크",
        "metadata": {
            "review_case_id": "review_case_2019_008384",
            "decision_fault_ratio": "A(청구) : B(피청구) = 10 : 90",
        },
    }


def test_build_case_context_uses_frozen_section_order() -> None:
    from etl.fault_cases.rag_runtime.review_case.context_builder import (
        build_case_context,
    )

    chunks = [
        {
            "chunk_type": "decision",
            "chunk_text": "결정이유와 최종비율",
        },
        {
            "chunk_type": "case_overview",
            "chunk_text": "사고내용과 결정비율",
        },
        {
            "chunk_type": "evidence_issue",
            "chunk_text": "입증자료와 주요쟁점",
        },
        {
            "chunk_type": "arguments",
            "chunk_text": "청구인 및 피청구인 주장",
        },
    ]

    context = build_case_context(_candidate(), chunks)

    assert context.index("[CASE_OVERVIEW]") < context.index(
        "[ARGUMENTS]"
    )
    assert context.index("[ARGUMENTS]") < context.index(
        "[EVIDENCE_ISSUE]"
    )
    assert context.index("[EVIDENCE_ISSUE]") < context.index(
        "[DECISION]"
    )
    assert "최종비율" in context


def test_build_case_context_falls_back_to_retrieved_chunk() -> None:
    from etl.fault_cases.rag_runtime.review_case.context_builder import (
        build_case_context,
    )

    context = build_case_context(_candidate(), [])

    assert context == "검색된 대표 청크"


def test_build_case_context_rejects_incomplete_section_set() -> None:
    from etl.fault_cases.rag_runtime.review_case.context_builder import (
        build_case_context,
    )

    incomplete = [
        {
            "chunk_type": "case_overview",
            "chunk_text": "사고내용",
        },
        {
            "chunk_type": "arguments",
            "chunk_text": "양측 주장",
        },
        {
            "chunk_type": "decision",
            "chunk_text": "결정이유",
        },
    ]

    context = build_case_context(_candidate(), incomplete)

    assert context == "검색된 대표 청크"


def test_fetch_document_chunks_uses_one_read_only_query(
    monkeypatch,
) -> None:
    from etl.fault_cases.rag_runtime.shared import qwen4_retrieval

    executed: dict[str, Any] = {}

    class Column:
        def __init__(self, name: str) -> None:
            self.name = name

    class Cursor:
        description = [
            Column("document_id"),
            Column("chunk_id"),
            Column("chunk_type"),
            Column("chunk_text"),
            Column("metadata"),
        ]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def execute(self, sql: str, params: tuple[list[str]]) -> None:
            executed["sql"] = sql
            executed["params"] = params

        def fetchall(self) -> list[tuple[Any, ...]]:
            return [
                (
                    "review_case_1",
                    "review_case_1_decision",
                    "decision",
                    "최종비율",
                    {"decision_fault_ratio": "30 : 70"},
                )
            ]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def cursor(self) -> Cursor:
            return Cursor()

    monkeypatch.setattr(
        qwen4_retrieval,
        "_connect",
        lambda corpus: Connection(),
    )

    rows = qwen4_retrieval.fetch_document_chunks(
        "review_case",
        ["review_case_1"],
    )

    assert executed["sql"].lstrip().startswith("SELECT")
    assert all(
        keyword not in executed["sql"].upper()
        for keyword in ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE")
    )
    assert executed["params"] == (["review_case_1"],)
    assert rows["review_case_1"][0]["chunk_type"] == "decision"
