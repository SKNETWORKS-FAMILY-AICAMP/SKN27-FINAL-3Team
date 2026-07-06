from __future__ import annotations

from typing import Any


def build_insurer_claim_review(
    *,
    insurer_claim: dict[str, Any] | None,
    issue_tags: list[str],
    evidence: list[dict[str, Any]],
    ratio_range_label: str,
) -> dict[str, Any] | None:
    if not insurer_claim:
        return None

    claimed_ratio = _clean(insurer_claim.get("claimed_ratio"))
    reason_text = _clean(insurer_claim.get("reason_text"))
    source_text = _clean(insurer_claim.get("source_text"))
    reference_evidence = _build_evidence_summaries(evidence)

    limitations = [
        "Insurance claim is user-provided or insurer-provided assertion, not a confirmed fact.",
    ]
    if not evidence:
        limitations.append(
            "No RAG evidence is available yet, so insurer claim cannot be compared with similar cases."
        )

    comparison_parts: list[str] = []
    if reason_text:
        comparison_parts.append(f"insurer_reason: {reason_text}")
    if ratio_range_label:
        comparison_parts.append(f"reference_ratio: {ratio_range_label}")
    if issue_tags:
        comparison_parts.append(f"input_issues: {', '.join(issue_tags[:5])}")
    if reference_evidence:
        refs = [item["source_reference"] for item in reference_evidence[:3] if item["source_reference"]]
        if refs:
            comparison_parts.append("reference_evidence: " + " / ".join(refs))
        source_types = sorted(
            {
                item["source_type"]
                for item in reference_evidence
                if item.get("source_type")
            }
        )
        if source_types:
            comparison_parts.append("reference_sources: " + ", ".join(source_types))

    return {
        "claimed_ratio": claimed_ratio,
        "claim_summary": reason_text or source_text,
        "comparison_summary": " ".join(comparison_parts).strip(),
        "key_dispute_points": issue_tags[:5],
        "reference_ratio_label": ratio_range_label,
        "reference_evidence_count": len(evidence),
        "reference_evidence": reference_evidence,
        "needed_evidence": _build_needed_evidence(issue_tags),
        "limitations": limitations,
    }


def _build_needed_evidence(issue_tags: list[str]) -> list[str]:
    needed: list[str] = []
    joined = " ".join(issue_tags)

    if "signal" in joined.lower() or "신호" in joined:
        needed.append("signal status and each vehicle entry timing evidence")
    if "lane" in joined.lower() or "차로" in joined or "진로" in joined:
        needed.append("lane-change start timing and turn-signal evidence")
    if "center" in joined.lower() or "중앙선" in joined:
        needed.append("road marking and vehicle trajectory evidence")
    if "rear" in joined.lower() or "후방" in joined or "추돌" in joined:
        needed.append("braking timing, safety distance, and impact position evidence")
    if "pedestrian" in joined.lower() or "보행" in joined:
        needed.append("pedestrian path and driver visibility evidence")

    if not needed:
        needed.append("blackbox video, accident scene photos, and insurer ratio explanation")

    return list(dict.fromkeys(needed))


def _build_evidence_summaries(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for item in evidence[:5]:
        metadata = item.get("metadata") or {}
        summaries.append(
            {
                "source_type": item.get("source_type") or "review_case",
                "title": _clean(item.get("title") or metadata.get("case_title")),
                "source_reference": _clean(item.get("source_reference")),
                "case_number": _clean(metadata.get("case_number")),
                "court_name": _clean(metadata.get("court_name")),
                "decision_date": _clean(metadata.get("decision_date")),
                "decision_fault_ratio": _clean(metadata.get("decision_fault_ratio")),
                "claimant_final_ratio": _clean(metadata.get("claimant_final_ratio")),
                "respondent_final_ratio": _clean(metadata.get("respondent_final_ratio")),
                "score": metadata.get("score"),
                "score_type": _clean(metadata.get("score_type")),
                "rank": metadata.get("rank"),
            }
        )
    return summaries


def _clean(value: Any) -> str:
    return str(value or "").strip()
