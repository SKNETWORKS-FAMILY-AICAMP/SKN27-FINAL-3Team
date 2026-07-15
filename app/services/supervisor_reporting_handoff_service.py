"""Deterministic Supervisor-to-Reporting handoff contracts.

The builder is intentionally framework-free and never invokes an LLM.  Callers
must supply rows reloaded from the canonical AgentResult repository.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlsplit


HANDOFF_CONTRACT_VERSION = "supervisor_reporting_handoff.v1"
ALLOWED_RESULT_STATUSES = {"success", "partial", "failed"}
RESULT_FIELDS = (
    "result_id",
    "node_code",
    "status",
    "summary",
    "structured_result",
    "evidence",
    "next_actions",
    "limitations",
)
ATTACHMENT_REFERENCE_FIELDS = ("attachment_id", "purpose", "filename")
SENSITIVE_RESULT_FIELDS = {
    "access_token",
    "agent_input",
    "api_key",
    "authorization",
    "client_secret",
    "password",
    "raw_output",
    "reasoning",
    "refresh_token",
    "secret",
    "token",
}
SENSITIVE_RESULT_FIELD_KEYS = {
    "accesstoken",
    "agentinput",
    "apikey",
    "authorization",
    "clientsecret",
    "idtoken",
    "localpath",
    "ocrraw",
    "ocrtext",
    "password",
    "presignedurl",
    "prompt",
    "rawoutput",
    "rawpayload",
    "rawtext",
    "reasoning",
    "refreshtoken",
    "secret",
    "signedurl",
    "token",
    "transcript",
    "usertext",
}
SENSITIVE_RESULT_FIELD_FRAGMENTS = (
    "accesstoken",
    "accesskey",
    "agentinput",
    "apikey",
    "authorization",
    "bearer",
    "chainofthought",
    "clientsecret",
    "cookie",
    "credential",
    "documenttext",
    "extractedtext",
    "fulltext",
    "idtoken",
    "localpath",
    "password",
    "privatekey",
    "rawoutput",
    "rawpayload",
    "rawtext",
    "reasoning",
    "refreshtoken",
    "secret",
    "scratchpad",
    "signedurl",
    "storagepath",
    "storageuri",
    "token",
    "transcript",
    "usertext",
)
CREDENTIAL_TEXT_PATTERNS = (
    re.compile(r"\bauthorization\s*:\s*bearer\s+[^\s,;]+", re.IGNORECASE),
    re.compile(r"\bauthorization\s*:\s*basic\s+[^\s,;]+", re.IGNORECASE),
    re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bbasic\s+[A-Za-z0-9+/=]{8,}", re.IGNORECASE),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bya29\.[A-Za-z0-9._~-]{10,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{10,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{10,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(
        r"\b(?:api[_ -]?key|client[_ -]?secret|access[_ -]?token|"
        r"refresh[_ -]?token|password|secret)\s*[:=]\s*[^\s,;]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"-----BEGIN (?P<label>[A-Z ]*PRIVATE KEY)-----.*?"
        r"-----END (?P=label)-----",
        re.IGNORECASE | re.DOTALL,
    ),
)


def build_supervisor_reporting_handoff(
    *,
    job: dict[str, Any],
    results: Iterable[dict[str, Any]],
    required_node_codes: Iterable[str],
    target_node_code: str,
    report_type: str,
    optional_node_codes: Iterable[str] = (),
    case_context: dict[str, Any] | None = None,
    reporting_step_executable: bool = True,
) -> dict[str, Any]:
    """Build a canonical handoff from already-persisted AgentResult records."""

    required = _unique_codes(required_node_codes)
    optional = [code for code in _unique_codes(optional_node_codes) if code not in required]
    rows_by_node: dict[str, list[dict[str, Any]]] = {}
    for raw_result in results:
        if not isinstance(raw_result, dict):
            continue
        node_code = _text(raw_result.get("node_code"))
        if not node_code:
            continue
        rows_by_node.setdefault(node_code, []).append(raw_result)

    ordered_codes = [*required, *optional]
    ordered_codes.extend(
        sorted(code for code in rows_by_node if code not in set(ordered_codes))
    )
    sanitized_results: dict[str, dict[str, Any]] = {}
    for node_code in ordered_codes:
        candidates = rows_by_node.get(node_code, [])
        if len(candidates) != 1:
            continue
        sanitized_results[node_code] = _sanitize_result(candidates[0], node_code=node_code)

    missing_required = [code for code in required if not rows_by_node.get(code)]
    duplicate_required = [code for code in required if len(rows_by_node.get(code, [])) > 1]
    failed_required = [
        code
        for code in required
        if len(rows_by_node.get(code, [])) == 1
        and _text(rows_by_node[code][0].get("status")) == "failed"
    ]
    partial_required = [
        code
        for code in required
        if len(rows_by_node.get(code, [])) == 1
        and _text(rows_by_node[code][0].get("status")) == "partial"
    ]
    invalid_required = [
        code
        for code in required
        if len(rows_by_node.get(code, [])) == 1
        and _text(rows_by_node[code][0].get("status")) not in ALLOWED_RESULT_STATUSES
    ]
    unavailable_optional = [
        code
        for code in optional
        if len(rows_by_node.get(code, [])) != 1
        or _text(rows_by_node[code][0].get("status")) != "success"
    ]

    reason_codes: list[str] = []
    if missing_required:
        reason_codes.append("required_result_missing")
    if duplicate_required:
        reason_codes.append("required_result_duplicate")
    if failed_required:
        reason_codes.append("required_result_failed")
    if invalid_required:
        reason_codes.append("required_result_invalid")
    if not reporting_step_executable:
        reason_codes.append("reporting_step_not_executable")
    blocked = bool(
        missing_required
        or duplicate_required
        or failed_required
        or invalid_required
        or not reporting_step_executable
    )
    if blocked:
        gate_status = "blocked"
    elif partial_required:
        gate_status = "draft"
        reason_codes.append("required_result_partial")
    else:
        gate_status = "ready"
    ready_for_reporting = gate_status == "ready"

    job_id = _text(job.get("job_id"))
    base_payload = {
        "contract_version": HANDOFF_CONTRACT_VERSION,
        "handoff_id": _handoff_id(job_id),
        "job": {
            "job_id": job_id,
            "session_id": _text(job.get("session_id")) or None,
            "message_id": _text(job.get("message_id")) or None,
            "analysis_plan_id": _text(job.get("analysis_plan_id")) or None,
            "routing_intent": _text(job.get("routing_intent")) or None,
        },
        "target": {
            "node_code": _text(target_node_code),
            "report_type": _text(report_type),
        },
        "source_node_codes": list(sanitized_results),
        "ready_for_reporting": ready_for_reporting,
        "gate": {
            "status": gate_status,
            "ready_for_reporting": ready_for_reporting,
            "required_node_codes": required,
            "optional_node_codes": optional,
            "partial_required_node_codes": partial_required,
            "failed_required_node_codes": failed_required,
            "missing_required_node_codes": missing_required,
            "duplicate_required_node_codes": duplicate_required,
            "invalid_required_node_codes": invalid_required,
            "unavailable_optional_node_codes": unavailable_optional,
            "reason_codes": reason_codes,
        },
        "case_context": _sanitize_case_context(case_context),
        "results": sanitized_results,
    }
    result_ids = [
        result["result_id"]
        for result in sanitized_results.values()
        if _text(result.get("result_id"))
    ]
    fingerprint = _canonical_fingerprint(base_payload)
    return {
        **base_payload,
        "source": {
            "persistence": "agent_results",
            "persisted": True,
            "result_ids": result_ids,
            "fingerprint": fingerprint,
        },
    }


def _sanitize_result(result: dict[str, Any], *, node_code: str) -> dict[str, Any]:
    sanitized = {
        field: deepcopy(result.get(field))
        for field in RESULT_FIELDS
    }
    sanitized["node_code"] = node_code
    sanitized["result_id"] = _text(sanitized.get("result_id"))
    sanitized["status"] = _text(sanitized.get("status"))
    sanitized["summary"] = sanitize_sensitive_text(sanitized.get("summary"))
    sanitized["structured_result"] = _sanitize_value(
        _dict(sanitized.get("structured_result"))
    )
    sanitized["evidence"] = _sanitize_value(_list(sanitized.get("evidence")))
    sanitized["next_actions"] = _sanitize_value(_list(sanitized.get("next_actions")))
    sanitized["limitations"] = _sanitize_value(_list(sanitized.get("limitations")))
    return sanitized


def _sanitize_case_context(value: dict[str, Any] | None) -> dict[str, Any]:
    context = value if isinstance(value, dict) else {}
    attachment_refs = []
    for attachment in _list(context.get("attachment_refs")):
        if not isinstance(attachment, dict):
            continue
        reference = {}
        for field in ATTACHMENT_REFERENCE_FIELDS:
            sanitized_value = sanitize_sensitive_text(attachment.get(field))
            if sanitized_value:
                reference[field] = sanitized_value
        if reference:
            attachment_refs.append(reference)
    return {
        "user_facts": sanitize_sensitive_text(context.get("user_facts")),
        "attachment_refs": attachment_refs,
    }


def _canonical_fingerprint(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_result_field(key) or _is_credential_url(item):
                continue
            sanitized[str(key)] = _sanitize_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value if not _is_credential_url(item)]
    if isinstance(value, tuple):
        return [_sanitize_value(item) for item in value if not _is_credential_url(item)]
    if _is_credential_url(value):
        return None
    if isinstance(value, str):
        return sanitize_sensitive_text(value)
    return deepcopy(value)


def sanitize_sensitive_text(value: Any) -> str:
    text = _text(value)
    if not text or _is_credential_url(text):
        return ""
    for pattern in CREDENTIAL_TEXT_PATTERNS:
        text = pattern.sub("[REDACTED_CREDENTIAL]", text)
    return text


def _is_sensitive_result_field(key: Any) -> bool:
    normalized = str(key).strip().lower()
    collapsed = "".join(character for character in normalized if character.isalnum())
    return bool(
        normalized in SENSITIVE_RESULT_FIELDS
        or collapsed in SENSITIVE_RESULT_FIELD_KEYS
        or collapsed.endswith("token")
        or any(fragment in collapsed for fragment in SENSITIVE_RESULT_FIELD_FRAGMENTS)
    )


def _is_credential_url(value: Any) -> bool:
    if not isinstance(value, str) or "://" not in value:
        return False
    try:
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None:
            return True
        query_keys = {
            "".join(character for character in key.lower() if character.isalnum())
            for key, _item in parse_qsl(parsed.query, keep_blank_values=True)
        }
    except ValueError:
        return False
    return bool(
        query_keys
        & {
            "accesstoken",
            "credential",
            "googleaccessid",
            "sig",
            "signature",
            "token",
            "xamzcredential",
            "xamzsecuritytoken",
            "xamzsignature",
            "xgoogcredential",
            "xgoogsecuritytoken",
            "xgoogsignature",
        }
    )


def _handoff_id(job_id: str) -> str:
    readable = f"srh_{job_id}"
    if len(readable) <= 64:
        return readable
    return f"srh_{hashlib.sha256(job_id.encode('utf-8')).hexdigest()[:24]}"


def _unique_codes(values: Iterable[str]) -> list[str]:
    codes: list[str] = []
    for value in values:
        code = _text(value)
        if code and code not in codes:
            codes.append(code)
    return codes


def _dict(value: Any) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return deepcopy(value) if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""
