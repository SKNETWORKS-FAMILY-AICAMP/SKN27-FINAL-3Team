"""Evidence boundaries for accident-case analysis inputs.

`confirmed_facts.v1` records what a user confirmed in a case form.  It does
not by itself establish that each statement is supported by material evidence.
This module derives the non-breaking `case_evidence.v1` view used by the
Supervisor and the agent-worker boundary.
"""

from __future__ import annotations

from typing import Any

from app.services.consultation_v2_service import CORE_FACT_QUESTIONS


CASE_EVIDENCE_SCHEMA_VERSION = "case_evidence.v1"
MATERIAL_SOURCE_TYPES = frozenset(
    {
        "attachment",
        "official_document",
        "official_record",
        "ocr_verified",
        "material_confirmed",
    }
)


def build_case_evidence(
    *,
    facts: dict[str, Any] | None,
    sources: list[dict[str, Any]] | None,
    conflicts: list[dict[str, Any]] | None,
    material_source_refs: set[str] | None = None,
) -> dict[str, Any]:
    """Classify case values without changing the confirmed-facts record.

    A source attached to no particular field is treated as the common source
    for the submitted form. This preserves the existing request shape while
    still requiring an explicit material source type before a value becomes a
    fact for agent analysis.
    """

    normalized_facts = _dict(facts)
    normalized_sources = _dict_list(sources)
    normalized_conflicts = _dict_list(conflicts)
    conflict_fields = {
        _text(item.get("field"))
        for item in normalized_conflicts
        if _text(item.get("field"))
    }
    source_by_field, default_source = _sources_by_field(normalized_sources)

    material_facts: dict[str, dict[str, Any]] = {}
    claims: dict[str, dict[str, Any]] = {}
    evidence_source: dict[str, dict[str, Any] | None] = {}

    for field, value in normalized_facts.items():
        normalized_field = _text(field)
        if not normalized_field or not _text(value):
            continue
        source = source_by_field.get(normalized_field, default_source)
        evidence_source[normalized_field] = source
        if normalized_field in conflict_fields:
            continue
        record = {"value": value, "evidence_source": source}
        if _is_material_source(source, material_source_refs=material_source_refs):
            material_facts[normalized_field] = record
        else:
            claims[normalized_field] = record

    unknowns: list[dict[str, Any]] = []
    for field, _question in CORE_FACT_QUESTIONS:
        if not _text(normalized_facts.get(field)):
            unknowns.append(
                {
                    "field": field,
                    "reason": "missing_fact",
                    "evidence_source": evidence_source.get(field),
                }
            )
    for field in sorted(conflict_fields):
        unknowns.append(
            {
                "field": field,
                "reason": "conflicting_claim",
                "evidence_source": evidence_source.get(field),
            }
        )

    return {
        "schema_version": CASE_EVIDENCE_SCHEMA_VERSION,
        "facts": material_facts,
        "claims": claims,
        "unknowns": unknowns,
        "evidence_source": evidence_source,
    }


def case_evidence_readiness(evidence: dict[str, Any]) -> dict[str, Any]:
    """Return the analysis gate details for required accident facts."""

    material_facts = _dict(evidence.get("facts"))
    claims = _dict(evidence.get("claims"))
    unknowns = _dict_list(evidence.get("unknowns"))
    required_fields = [field for field, _question in CORE_FACT_QUESTIONS]
    conflict_fields = {
        _text(item.get("field"))
        for item in unknowns
        if _text(item.get("reason")) == "conflicting_claim" and _text(item.get("field"))
    }
    missing_fields = [
        field
        for field in required_fields
        if field not in material_facts and field not in claims and field not in conflict_fields
    ]
    unverified_fields = [
        field
        for field in required_fields
        if field in claims and field not in conflict_fields
    ]
    return {
        "ready": not missing_fields and not unverified_fields and not conflict_fields,
        "required_fields": required_fields,
        "missing_fields": missing_fields,
        "unverified_fields": unverified_fields,
        "conflict_fields": sorted(conflict_fields),
    }


def material_fact_values(evidence: dict[str, Any]) -> dict[str, Any]:
    """Return only values allowed in an agent's factual input text."""

    return {
        field: record.get("value")
        for field, record in _dict(evidence.get("facts")).items()
        if isinstance(record, dict) and _text(record.get("value"))
    }


def _sources_by_field(
    sources: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    source_by_field: dict[str, dict[str, Any]] = {}
    default_source: dict[str, Any] | None = None
    for source in sources:
        field = _text(source.get("field"))
        if field:
            source_by_field[field] = source
        elif default_source is None:
            default_source = source
    return source_by_field, default_source


def _source_type(source: dict[str, Any] | None) -> str:
    return _text((source or {}).get("source_type")).lower()


def _is_material_source(
    source: dict[str, Any] | None,
    *,
    material_source_refs: set[str] | None,
) -> bool:
    if _source_type(source) not in MATERIAL_SOURCE_TYPES:
        return False
    if material_source_refs is None:
        return True
    return _text((source or {}).get("source_ref")) in material_source_refs


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or [] if isinstance(item, dict)]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""
