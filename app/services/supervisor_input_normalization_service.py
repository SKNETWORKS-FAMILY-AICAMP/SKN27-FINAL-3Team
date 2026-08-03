"""Versioned deterministic input-normalization policy for the Supervisor."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any


POLICY_CONTRACT_VERSION = "supervisor_input_normalization_policy.v1"
DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "supervisor_input_normalization_policy.v1.json"
)
EXPECTED_DOMAINS = frozenset({"accident", "fine_notice", "objection"})
ALLOWED_TOKEN_CLASSES = frozenset(
    {"entity", "action", "state", "modifier", "negation", "uncertainty", "particle"}
)
NORMALIZED_INPUT_CONTRACT_VERSION = "normalized_supervisor_input.v1"
MATCH_CONFIDENCE = {
    "exact": 1.0,
    "alias": 0.99,
    "approved_typo": 0.99,
}
DATE_PATTERN = re.compile(
    r"(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|20\d{2}년\s*\d{1,2}월\s*\d{1,2}일)"
)
AMOUNT_PATTERN = re.compile(r"\d{1,3}(?:,\d{3})*\s*원")
AUTHORITY_PATTERN = re.compile(
    r"(?:[가-힣]{2,20}(?:경찰서|시청|구청|군청|도로교통공단)"
    r"|[가-힣]{2,10}(?:특별시|광역시|특별자치시|특별자치도)|서울시)"
)
DUE_DATE_CONTEXT_MARKERS = ("납부기한", "의견제출기한", "의견제출 기한", "까지")


@lru_cache(maxsize=1)
def normalization_policy() -> dict[str, Any]:
    """Load and validate the server-owned normalization policy."""

    configured = os.environ.get("SUPERVISOR_INPUT_NORMALIZATION_POLICY_PATH", "").strip()
    path = Path(configured).expanduser() if configured else DEFAULT_POLICY_PATH
    policy = json.loads(path.read_text(encoding="utf-8"))
    _validate_policy(policy)
    return {**policy, "_source": str(path)}


def clear_normalization_policy_cache() -> None:
    normalization_policy.cache_clear()


def normalization_policy_metadata() -> dict[str, str]:
    policy = normalization_policy()
    return {
        "contract_version": str(policy["contract_version"]),
        "source": str(policy["_source"]),
    }


def normalize_supervisor_input(
    *,
    user_text: str,
    source_message_id: str,
) -> dict[str, Any]:
    """Return only deterministic candidates registered in the policy."""

    original = str(user_text or "")
    normalized, original_indexes = _nfkc_with_index_map(original)
    matches = _registered_matches(normalized)
    matches.extend(_contextual_vehicle_action_matches(normalized))
    matches.extend(_structured_legal_matches(normalized))
    selected = _prefer_longest_non_overlapping(matches)
    candidates = [
        _apply_semantic_guards(
            _candidate_from_match(
                item,
                original=original,
                original_indexes=original_indexes,
                source_message_id=str(source_message_id or ""),
            ),
            normalized=normalized,
            start=int(item["start"]),
            end=int(item["end"]),
        )
        for item in selected
    ]
    clarifications = [
        _clarification_from_candidate(candidate)
        for candidate in candidates
        if candidate["decision"] != "auto_applied"
    ]
    if "고지서" in normalized and not any(
        candidate["field"] == "notice_stage" for candidate in candidates
    ):
        clarifications.append(
            {
                "domain": "fine_notice",
                "schema": "fine_notice_intake",
                "field": "notice_stage",
                "value": None,
                "decision": "clarification_required",
                "reason": "ambiguous_notice_stage",
                "source_message_id": str(source_message_id or ""),
            }
        )
    return {
        "contract_version": NORMALIZED_INPUT_CONTRACT_VERSION,
        "policy_version": POLICY_CONTRACT_VERSION,
        "candidates": candidates,
        "clarifications": clarifications,
    }


def _nfkc_with_index_map(value: str) -> tuple[str, list[int]]:
    normalized: list[str] = []
    original_indexes: list[int] = []
    for index, character in enumerate(value):
        converted = unicodedata.normalize("NFKC", character)
        for converted_character in converted:
            if converted_character.isspace():
                if normalized and normalized[-1] == " ":
                    continue
                converted_character = " "
            normalized.append(converted_character)
            original_indexes.append(index)
    return "".join(normalized), original_indexes


def _registered_matches(normalized: str) -> list[dict[str, Any]]:
    policy = normalization_policy()
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int, str]] = set()
    variant_groups = (
        ("exact", "expressions"),
        ("alias", "aliases"),
        ("approved_typo", "approved_typos"),
    )
    for rule in policy["rules"]:
        for match_kind, key in variant_groups:
            for variant in rule.get(key) or []:
                normalized_variant, _ = _nfkc_with_index_map(str(variant))
                if not normalized_variant:
                    continue
                for match in re.finditer(re.escape(normalized_variant), normalized):
                    identity = (
                        str(rule["rule_id"]),
                        match.start(),
                        match.end(),
                        match_kind,
                    )
                    if identity in seen:
                        continue
                    seen.add(identity)
                    matches.append(
                        {
                            "rule": rule,
                            "start": match.start(),
                            "end": match.end(),
                            "match_kind": match_kind,
                            "confidence": MATCH_CONFIDENCE[match_kind],
                        }
                    )

    matches.extend(_particle_stripped_matches(normalized, policy, seen=seen))
    return matches


def _particle_stripped_matches(
    normalized: str,
    policy: dict[str, Any],
    *,
    seen: set[tuple[str, int, int, str]],
) -> list[dict[str, Any]]:
    """Match registered one-token expressions after removing registered particles."""

    particles = sorted(policy["token_classes"]["particles"], key=len, reverse=True)
    variants: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for rule in policy["rules"]:
        for match_kind, key in (
            ("exact", "expressions"),
            ("alias", "aliases"),
            ("approved_typo", "approved_typos"),
        ):
            for variant in rule.get(key) or []:
                normalized_variant, _ = _nfkc_with_index_map(str(variant))
                if normalized_variant and " " not in normalized_variant:
                    variants.setdefault(normalized_variant, []).append((rule, match_kind))

    matches: list[dict[str, Any]] = []
    for token_match in re.finditer(r"[가-힣A-Za-z0-9]+", normalized):
        token = token_match.group(0)
        for particle in particles:
            if not token.endswith(particle):
                continue
            stripped = token[: -len(particle)]
            if len(stripped) < 2:
                continue
            for rule, match_kind in variants.get(stripped, []):
                start = token_match.start()
                end = start + len(stripped)
                identity = (str(rule["rule_id"]), start, end, match_kind)
                if identity in seen:
                    continue
                seen.add(identity)
                matches.append(
                    {
                        "rule": rule,
                        "start": start,
                        "end": end,
                        "match_kind": match_kind,
                        "confidence": MATCH_CONFIDENCE[match_kind],
                    }
                )
            break
    return matches


def _contextual_vehicle_action_matches(normalized: str) -> list[dict[str, Any]]:
    """Match an action only when the same clause identifies the vehicle."""

    policy = normalization_policy()
    rules_by_field: dict[str, list[dict[str, Any]]] = {}
    for rule in policy["rules"]:
        field = str(rule["field"])
        if field in {"vehicle_actions.self", "vehicle_actions.other"}:
            rules_by_field.setdefault(field, []).append(rule)

    matches: list[dict[str, Any]] = []
    for clause_start, clause_end in _clause_ranges(normalized):
        clause = normalized[clause_start:clause_end]
        tokens = list(re.finditer(r"[가-힣A-Za-z0-9]+", clause))
        for subject_index, subject_match in enumerate(tokens):
            subject = _strip_registered_particle(subject_match.group(0), policy)
            field = _vehicle_action_field_for_subject(subject_match.group(0), subject)
            if not field:
                continue
            possible: list[dict[str, Any]] = []
            for token_match in tokens[subject_index + 1:subject_index + 4]:
                for rule in rules_by_field.get(field, []):
                    action = str(rule["canonical_expression"]).split()[-1]
                    observed_token = token_match.group(0)
                    if len(observed_token) < len(action):
                        continue
                    observed_action = observed_token[:len(action)]
                    if not observed_action.startswith(action[0]):
                        continue
                    start = clause_start + token_match.start()
                    end = start + len(observed_action)
                    if observed_action == action:
                        possible.append(
                            {
                                "rule": rule,
                                "start": start,
                                "end": end,
                                "match_kind": "alias",
                                "confidence": MATCH_CONFIDENCE["alias"],
                            }
                        )
                        continue

                    observed_phrase = _normalized_phrase_for_fuzzy_match(
                        tokens[subject_index:tokens.index(token_match) + 1],
                        policy,
                        final_token=observed_action,
                    )
                    best_ratio = max(
                        (
                            _fuzzy_ratio(
                                observed_phrase,
                                _normalized_policy_variant(variant, policy),
                            )
                            for key in ("expressions", "aliases")
                            for variant in rule.get(key) or []
                        ),
                        default=0.0,
                    )
                    if best_ratio >= float(policy["fuzzy_confirmation_threshold"]):
                        possible.append(
                            {
                                "rule": rule,
                                "start": start,
                                "end": end,
                                "match_kind": "fuzzy",
                                "confidence": round(best_ratio, 4),
                            }
                        )

            if not possible:
                continue
            highest = max(float(item["confidence"]) for item in possible)
            best = [item for item in possible if float(item["confidence"]) == highest]
            identities = {
                (str(item["rule"]["field"]), str(item["rule"]["value"]))
                for item in best
            }
            if len(identities) == 1:
                matches.append(best[0])
    return matches


def _structured_legal_matches(normalized: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for pattern, field, token_class, rule_id in (
        (
            AUTHORITY_PATTERN,
            "issuing_authority",
            "entity",
            "fine_notice.issuing_authority.pattern_01",
        ),
        (
            AMOUNT_PATTERN,
            "amount",
            "entity",
            "fine_notice.amount.pattern_01",
        ),
    ):
        for match in pattern.finditer(normalized):
            matches.append(
                _structured_match(
                    match=match,
                    field=field,
                    decision="auto_applied",
                    token_class=token_class,
                    rule_id=rule_id,
                )
            )

    for match in DATE_PATTERN.finditer(normalized):
        clause_start, clause_end = _clause_range_for_span(
            normalized,
            match.start(),
            match.end(),
        )
        clause = normalized[clause_start:clause_end]
        is_due_date = any(marker in clause for marker in DUE_DATE_CONTEXT_MARKERS)
        matches.append(
            _structured_match(
                match=match,
                field="due_date" if is_due_date else "notice_date",
                decision=("auto_applied" if is_due_date else "confirmation_required"),
                token_class="state",
                rule_id=(
                    "fine_notice.due_date.pattern_01"
                    if is_due_date
                    else "fine_notice.notice_date.pattern_01"
                ),
            )
        )
    return matches


def _structured_match(
    *,
    match: re.Match[str],
    field: str,
    decision: str,
    token_class: str,
    rule_id: str,
) -> dict[str, Any]:
    return {
        "rule": {
            "rule_id": rule_id,
            "domain": "fine_notice",
            "schema": "fine_notice_intake",
            "field": field,
            "value": match.group(0),
            "token_class": token_class,
            "canonical_expression": match.group(0),
            "decision": decision,
            "routing_intent": "fine_notice_procedure",
        },
        "start": match.start(),
        "end": match.end(),
        "match_kind": "exact",
        "confidence": 0.99,
        "preserve_source_value": True,
    }


def _clause_ranges(value: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = 0
    for boundary in re.finditer(r"[.!?。！？\n]+|그리고|하지만|그러나|다만", value):
        if boundary.start() > start:
            ranges.append((start, boundary.start()))
        start = boundary.end()
    if start < len(value):
        ranges.append((start, len(value)))
    return ranges or [(0, len(value))]


def _strip_registered_particle(token: str, policy: dict[str, Any]) -> str:
    for particle in sorted(
        policy["token_classes"]["particles"], key=len, reverse=True
    ):
        if token.endswith(particle) and len(token) - len(particle) >= 2:
            return token[:-len(particle)]
    return token


def _vehicle_action_field_for_subject(raw: str, stripped: str) -> str | None:
    if raw in {"제가", "저는"} or stripped in {"저", "본인", "내", "제"}:
        return "vehicle_actions.self"
    if raw.startswith("상대") or stripped.startswith("상대"):
        return "vehicle_actions.other"
    return None


def _normalized_phrase_for_fuzzy_match(
    token_matches: list[re.Match[str]],
    policy: dict[str, Any],
    *,
    final_token: str,
) -> str:
    tokens = [
        _strip_registered_particle(match.group(0), policy)
        for match in token_matches[:-1]
    ]
    tokens.append(final_token)
    return " ".join(tokens)


def _normalized_policy_variant(value: str, policy: dict[str, Any]) -> str:
    normalized, _ = _nfkc_with_index_map(str(value))
    return " ".join(
        _strip_registered_particle(match.group(0), policy)
        for match in re.finditer(r"[가-힣A-Za-z0-9]+", normalized)
    )


def _fuzzy_ratio(left: str, right: str) -> float:
    return SequenceMatcher(
        None,
        unicodedata.normalize("NFD", left),
        unicodedata.normalize("NFD", right),
    ).ratio()


def _prefer_longest_non_overlapping(
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    occupied: dict[tuple[str, str], list[tuple[int, int]]] = {}
    ordered = sorted(
        matches,
        key=lambda item: (
            -(int(item["end"]) - int(item["start"])),
            int(item["start"]),
            str(item["rule"]["rule_id"]),
        ),
    )
    for item in ordered:
        rule = item["rule"]
        group = (str(rule["schema"]), str(rule["field"]))
        span = (int(item["start"]), int(item["end"]))
        if any(span[0] < end and start < span[1] for start, end in occupied.get(group, [])):
            continue
        occupied.setdefault(group, []).append(span)
        selected.append(item)
    return sorted(
        selected,
        key=lambda item: (
            int(item["start"]),
            int(item["end"]),
            str(item["rule"]["field"]),
        ),
    )


def _candidate_from_match(
    item: dict[str, Any],
    *,
    original: str,
    original_indexes: list[int],
    source_message_id: str,
) -> dict[str, Any]:
    start = int(item["start"])
    end = int(item["end"])
    original_start = original_indexes[start]
    original_end = original_indexes[end - 1] + 1
    rule = item["rule"]
    source_text = original[original_start:original_end]
    return {
        "domain": str(rule["domain"]),
        "schema": str(rule["schema"]),
        "field": str(rule["field"]),
        "value": source_text if item.get("preserve_source_value") else str(rule["value"]),
        "source_span": {"start": original_start, "end": original_end},
        "source_text": source_text,
        "source_message_id": source_message_id,
        "normalized_expression": str(rule["canonical_expression"]),
        "rule_id": str(rule["rule_id"]),
        "token_class": str(rule["token_class"]),
        "match_kind": str(item["match_kind"]),
        "confidence": float(item["confidence"]),
        "decision": str(rule["decision"]),
        "routing_intent": str(rule.get("routing_intent") or ""),
        "negated": False,
        "uncertain": False,
    }


def _apply_semantic_guards(
    candidate: dict[str, Any],
    *,
    normalized: str,
    start: int,
    end: int,
) -> dict[str, Any]:
    clause_start, clause_end = _clause_range_for_span(normalized, start, end)
    relative_start = start - clause_start
    relative_end = end - clause_start
    clause = normalized[clause_start:clause_end]
    before = clause[max(0, relative_start - 8):relative_start]
    after = clause[relative_end:relative_end + 12]
    local_context = f"{before}{after}"
    token_classes = normalization_policy()["token_classes"]
    negated = any(token in local_context for token in token_classes["negation"])
    uncertain = any(
        token in local_context for token in token_classes["uncertainty"]
    )
    decision = str(candidate["decision"])
    if candidate.get("match_kind") == "fuzzy":
        decision = "confirmation_required"
    if negated:
        decision = "clarification_required"
    elif uncertain:
        decision = "confirmation_required"
    return {
        **candidate,
        "negated": negated,
        "uncertain": uncertain,
        "decision": decision,
    }


def _clause_range_for_span(
    value: str,
    start: int,
    end: int,
) -> tuple[int, int]:
    for clause_start, clause_end in _clause_ranges(value):
        if clause_start <= start and end <= clause_end:
            return clause_start, clause_end
    return 0, len(value)


def _clarification_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain": candidate["domain"],
        "schema": candidate["schema"],
        "field": candidate["field"],
        "value": candidate["value"],
        "decision": candidate["decision"],
        "rule_id": candidate["rule_id"],
        "source_message_id": candidate["source_message_id"],
        "reason": (
            "negated_expression"
            if candidate["negated"]
            else "uncertain_expression"
            if candidate["uncertain"]
            else "unregistered_similar_expression"
        ),
    }


def _validate_policy(policy: Any) -> None:
    if not isinstance(policy, dict):
        raise ValueError("normalization_policy_must_be_an_object")
    if policy.get("contract_version") != POLICY_CONTRACT_VERSION:
        raise ValueError("unsupported_normalization_policy_version")

    domains = policy.get("domains")
    if not isinstance(domains, dict) or set(domains) != EXPECTED_DOMAINS:
        raise ValueError("normalization_policy_requires_supported_domains")
    allowed_fields: dict[tuple[str, str], set[str]] = {}
    for domain, domain_policy in domains.items():
        schemas = domain_policy.get("schemas") if isinstance(domain_policy, dict) else None
        if not isinstance(schemas, dict) or not schemas:
            raise ValueError("normalization_policy_requires_domain_schemas")
        for schema, fields in schemas.items():
            normalized_fields = _string_set(fields)
            if not str(schema).strip() or not normalized_fields:
                raise ValueError("normalization_policy_requires_schema_fields")
            allowed_fields[(domain, str(schema).strip())] = normalized_fields

    decisions = _string_set(policy.get("decisions"))
    if decisions != {
        "auto_applied",
        "confirmation_required",
        "clarification_required",
    }:
        raise ValueError("normalization_policy_requires_supported_decisions")

    token_classes = policy.get("token_classes")
    if not isinstance(token_classes, dict):
        raise ValueError("normalization_policy_requires_token_classes")
    for field in ("negation", "uncertainty", "particles"):
        if not _string_set(token_classes.get(field)):
            raise ValueError("normalization_policy_requires_token_classes")

    threshold = policy.get("fuzzy_confirmation_threshold")
    if not isinstance(threshold, (int, float)) or not 0 < float(threshold) <= 1:
        raise ValueError("normalization_policy_requires_fuzzy_threshold")

    rules = policy.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("normalization_policy_requires_rules")
    seen_rule_ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("normalization_policy_contains_invalid_rule")
        rule_id = str(rule.get("rule_id") or "").strip()
        if not rule_id:
            raise ValueError("normalization_policy_requires_rule_id")
        if rule_id in seen_rule_ids:
            raise ValueError("duplicate_normalization_rule_id")
        seen_rule_ids.add(rule_id)

        domain = str(rule.get("domain") or "").strip()
        schema = str(rule.get("schema") or "").strip()
        if (domain, schema) not in allowed_fields:
            raise ValueError("normalization_policy_contains_unknown_schema")
        if str(rule.get("field") or "").strip() not in allowed_fields[(domain, schema)]:
            raise ValueError("normalization_policy_contains_unknown_field")
        if str(rule.get("decision") or "").strip() not in decisions:
            raise ValueError("normalization_policy_contains_invalid_decision")
        if str(rule.get("token_class") or "").strip() not in ALLOWED_TOKEN_CLASSES:
            raise ValueError("normalization_policy_contains_invalid_token_class")
        if not str(rule.get("value") or "").strip():
            raise ValueError("normalization_policy_requires_rule_value")
        if not str(rule.get("canonical_expression") or "").strip():
            raise ValueError("normalization_policy_requires_canonical_expression")
        variants = [
            *_string_set(rule.get("expressions")),
            *_string_set(rule.get("aliases")),
            *_string_set(rule.get("approved_typos")),
        ]
        if not variants:
            raise ValueError("normalization_policy_requires_rule_expressions")


def _string_set(value: Any) -> set[str]:
    return {
        str(item).strip()
        for item in value or []
        if str(item).strip()
    }
