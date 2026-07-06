from __future__ import annotations

import json
from typing import Any

from .chunk_config import DEFAULT_CHUNK_CONFIG, FAULT_RATIO_EVIDENCE_TERMS, ChunkConfig
from .chunker import TextChunk, join_labeled_parts, normalize_text, split_long_text


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value] if value else []
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def build_overview(row: dict[str, Any], dataset: str, config: ChunkConfig) -> list[TextChunk]:
    parts = [
        ("사건명", row.get("case_name")),
        ("사건번호", row.get("case_number")),
        ("법원", row.get("court_name")),
        ("선고일", str(row.get("decision_date") or "")),
        ("사건분류", row.get("case_category")),
        ("판결유형", row.get("judgment_type")),
        ("교통사고 라벨", row.get("traffic_verification_final_label") or row.get("traffic_label")),
    ]
    if dataset == "fault_ratio":
        parts.extend(
            [
                ("과실비율 라벨", row.get("fault_ratio_verification_final_label") or row.get("fault_ratio_label")),
            ]
        )
    text = join_labeled_parts(parts)
    return split_long_text(text, "case_overview", ["metadata", "labels"], config)


def build_metadata_chunks(row: dict[str, Any], dataset: str, config: ChunkConfig) -> list[TextChunk]:
    if dataset == "fault_ratio":
        fields = [
            "fault_ratio_signal_groups",
            "fault_ratio_evidence_terms",
            "fault_ratio_explicit_terms",
            "fault_ratio_party_fault_terms",
            "fault_ratio_damage_terms",
            "fault_ratio_duty_terms",
            "fault_ratio_number_examples",
        ]
        chunk_type = "fault_ratio_metadata"
    else:
        fields = [
            "traffic_signal_groups",
            "traffic_evidence_terms",
            "traffic_direct_terms",
            "traffic_legal_terms",
            "traffic_actor_terms",
            "traffic_action_terms",
            "traffic_situation_terms",
            "traffic_fault_terms",
        ]
        chunk_type = "traffic_metadata"

    parts = []
    for field in fields:
        values = [str(value) for value in as_list(row.get(field)) if str(value).strip()]
        if values:
            parts.append((field, "\n".join(values)))
    text = join_labeled_parts(parts)
    return split_long_text(text, chunk_type, fields, config)


def build_holding_summary(row: dict[str, Any], config: ChunkConfig) -> list[TextChunk]:
    text = join_labeled_parts(
        [
            ("판시사항", row.get("holding")),
            ("요약", row.get("summary")),
        ]
    )
    return split_long_text(text, "holding_summary", ["holding", "summary"], config)


def build_law_reference(row: dict[str, Any], config: ChunkConfig) -> list[TextChunk]:
    text = join_labeled_parts(
        [
            ("참조법령", row.get("referenced_laws")),
            ("참조판례", row.get("referenced_cases")),
        ]
    )
    return split_long_text(text, "law_reference", ["referenced_laws", "referenced_cases"], config)


def build_fault_ratio_evidence(row: dict[str, Any], config: ChunkConfig) -> list[TextChunk]:
    evidence_values = []
    for field in [
        "fault_ratio_evidence_terms",
        "fault_ratio_number_examples",
        "fault_ratio_explicit_terms",
        "fault_ratio_party_fault_terms",
        "fault_ratio_damage_terms",
        "fault_ratio_duty_terms",
    ]:
        values = [str(value) for value in as_list(row.get(field)) if str(value).strip()]
        if values:
            evidence_values.append((field, "\n".join(values)))

    main_text = normalize_text(row.get("main_text"))
    snippets = []
    for term in FAULT_RATIO_EVIDENCE_TERMS:
        index = main_text.find(term)
        if index < 0:
            continue
        start = max(index - 450, 0)
        end = min(index + 850, len(main_text))
        snippets.append(main_text[start:end])
    if snippets:
        evidence_values.append(("main_text_evidence_snippets", "\n\n".join(dict.fromkeys(snippets))))

    text = join_labeled_parts(evidence_values)
    return split_long_text(
        text=text,
        chunk_type="fault_ratio_evidence",
        source_fields=[
            "fault_ratio_evidence_terms",
            "fault_ratio_number_examples",
            "fault_ratio_explicit_terms",
            "fault_ratio_party_fault_terms",
            "main_text",
        ],
        config=config,
    )


def build_chunks(row: dict[str, Any], dataset: str, config: ChunkConfig = DEFAULT_CHUNK_CONFIG) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    chunks.extend(build_overview(row, dataset, config))
    chunks.extend(build_metadata_chunks(row, dataset, config))
    chunks.extend(build_holding_summary(row, config))

    if dataset == "fault_ratio":
        chunks.extend(build_fault_ratio_evidence(row, config))

    chunks.extend(
        split_long_text(
            text=row.get("main_text") or row.get("full_text") or "",
            chunk_type="main_text",
            source_fields=["main_text"],
            config=config,
        )
    )
    chunks.extend(build_law_reference(row, config))

    return [chunk for chunk in chunks if normalize_text(chunk.text)]
