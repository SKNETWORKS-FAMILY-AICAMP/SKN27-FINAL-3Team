"""Single deterministic fault-ratio calculator shared by A, B, and C.

This module never retrieves or evaluates answers. It receives a selected Rule,
the resolved user/opponent mapping, source-derived profile records, and facts;
then returns only the deterministic calculation trace and result JSON.
"""

from __future__ import annotations

from typing import Any

from .utils import normalize_party_type


def _not_calculable(selection: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "case_id": selection["case_id"], "method": selection["method"], "status": "not_calculable",
        "rule_id": selection["selected_rule_id"], "final_ratio": None, "reason": reason,
    }


def calculate_fault_ratio(selection: dict[str, Any], facts: dict[str, str], profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Apply base fault ratio then source-approved adjustment factors.

    No weights, learned values, or answer-key fields participate in this
    function. A missing mapping/profile returns ``not_calculable`` rather than
    inventing a ratio.
    """
    mapping = selection.get("party_mapping")
    rule_id = selection["selected_rule_id"]
    if not mapping:
        return _not_calculable(selection, "party_mapping_unresolved")
    records = profiles[rule_id]["source_records"]
    bases, parties = records.get("base_faults", []), records.get("parties", [])
    if len(bases) != 1 or len(parties) != 2:
        return _not_calculable(selection, "missing_base_or_parties")
    base = bases[0]
    party_by_type = {normalize_party_type(row.get("party_type")): row["party_key"] for row in parties if normalize_party_type(row.get("party_type"))}
    if isinstance(base.get("party_a_ratio"), int) and isinstance(base.get("party_b_ratio"), int):
        shares = {"A": int(base["party_a_ratio"]), "B": int(base["party_b_ratio"])}
        if isinstance(base.get("party_a_ratio_alt"), int) and isinstance(base.get("party_b_ratio_alt"), int):
            reverse_scope = next((scope for scope in mapping if facts.get(f"{scope}.movement") == "reverse_exit"), None)
            if reverse_scope:
                shares = {"A": int(base["party_a_ratio_alt"]), "B": int(base["party_b_ratio_alt"])}
                variant_id = "\ud6c4\uc9c4\ucd9c\ucc28"
            else:
                variant_id = "\uc804\uc9c4\ucd9c\ucc28"
        else:
            variant_id = None
    elif isinstance(base.get("base_fault_ratio"), int) and base.get("base_fault_party"):
        target = party_by_type.get(str(base["base_fault_party"]))
        if not target:
            return _not_calculable(selection, "single_party_base_mapping_unresolved")
        other = next(row["party_key"] for row in parties if row["party_key"] != target)
        shares, variant_id = {target: int(base["base_fault_ratio"]), other: 100 - int(base["base_fault_ratio"])}, None
    else:
        return _not_calculable(selection, "unsupported_base_format")
    if set(mapping.values()) != set(shares) or sum(shares.values()) != 100:
        return _not_calculable(selection, "base_party_mapping_mismatch")

    steps = [{"step_type": "base", "shares_by_pdf_party": dict(shares)}]
    applied: list[dict[str, Any]] = []
    inverse = {value: key for key, value in mapping.items()}
    for factor in records.get("adjustment_factors", []):
        target = factor.get("target_party_key")
        if target not in shares:
            continue
        # PDF tables explicitly use '비적용' for some factors.  A null delta is
        # not zero and must never be coerced into a numerical adjustment.
        if factor.get("is_applicable") is False or not isinstance(factor.get("delta"), int):
            continue
        name, scope = str(factor.get("factor_name") or ""), inverse[target]
        applies = (
            ("\ub300\ud615\ucc28" in name and facts.get(f"{scope}.vehicle_size") == "large")
            or (("\uc57c\uac04" in name or "\uc2dc\uc57c\uc7a5\uc560" in name) and facts.get("scene.visibility_issue") == "true")
            or ("\uc11c\ud589\ubd88\uc774\ud589" in name and facts.get(f"{scope}.slow") == "false")
        )
        if not applies:
            continue
        delta, other, before = int(factor["delta"]), next(key for key in shares if key != target), dict(shares)
        shares[target] += delta
        shares[other] -= delta
        if min(shares.values()) < 0 or max(shares.values()) > 100:
            return _not_calculable(selection, "adjustment_out_of_range")
        item = {"adjustment_id": factor["adjustment_id"], "target_pdf_party_key": target, "delta": delta, "factor_name": name}
        applied.append(item)
        steps.append({"step_type": "adjustment", "before": before, "after": dict(shares), **item})
    return {
        "case_id": selection["case_id"], "method": selection["method"], "status": "calculated", "rule_id": rule_id,
        "party_mapping": mapping, "variant_id": variant_id,
        "base_ratio": {"user": steps[0]["shares_by_pdf_party"][mapping["user"]], "opponent": steps[0]["shares_by_pdf_party"][mapping["opponent"]]},
        "applied_adjustments": applied, "calculation_steps": steps,
        "final_ratio": {"user": shares[mapping["user"]], "opponent": shares[mapping["opponent"]]},
    }
