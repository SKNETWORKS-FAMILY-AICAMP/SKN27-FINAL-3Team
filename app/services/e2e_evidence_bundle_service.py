"""Privacy-safe contract builder for deployed pilot E2E evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from typing import Any

from app.security.pii_masking import sanitize_pii
from app.services.analysis_progress_service import ANALYSIS_SEMANTIC_STATUSES


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TEST_ID_RE = re.compile(r"^ID-(?:0?[1-9]|1[0-3])(?:-[a-z][a-z0-9_-]*)?$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,63}$")
_ARTIFACT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_ACCOUNT_TYPES = frozenset({"guest", "authenticated"})
_ALLOWED_FIELDS = {
    "top_level": frozenset(
        {
            "contract_version",
            "test_id",
            "exact_input",
            "executed_at",
            "account_type",
            "release",
            "browser_evidence",
            "http",
            "execution",
            "sanitized_logs",
        }
    ),
    "release": frozenset(
        {"sha", "frontend_image_digest", "backend_image_digest"}
    ),
    "browser_evidence": frozenset({"input_response_screenshot"}),
    "http": frozenset({"status_code", "public_response"}),
    "execution": frozenset(
        {
            "routing_intent",
            "node_list",
            "semantic_status",
            "job_id",
            "correlation_id",
        }
    ),
}
_UNSAFE_KEY_MARKERS = frozenset(
    {
        "authorization",
        "rawocr",
        "rawocrtext",
        "ocrtext",
        "storageuri",
        "signedurl",
        "localpath",
    }
)
_SIGNED_URL_MARKERS = (
    "x-amz-signature=",
    "x-amz-credential=",
    "x-goog-signature=",
    "signature=",
    "sig=",
)

_REQUIRED_PATHS = (
    "contract_version",
    "test_id",
    "exact_input",
    "executed_at",
    "account_type",
    "release.sha",
    "release.frontend_image_digest",
    "release.backend_image_digest",
    "browser_evidence.input_response_screenshot",
    "http.status_code",
    "http.public_response",
    "execution.routing_intent",
    "execution.node_list",
    "execution.semantic_status",
    "execution.job_id",
    "execution.correlation_id",
    "sanitized_logs",
)


class EvidenceBundleValidationError(ValueError):
    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(dict.fromkeys(str(error) for error in errors))
        super().__init__(
            "invalid e2e evidence bundle: " + ", ".join(self.errors)
        )


def build_e2e_evidence_bundle(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build one allowlisted, masked bundle or fail without echoing source data."""

    source = payload if isinstance(payload, Mapping) else {}
    unsafe_errors = _unsafe_errors(source)
    if unsafe_errors:
        raise EvidenceBundleValidationError(unsafe_errors)

    release = _mapping(source.get("release"))
    browser = _mapping(source.get("browser_evidence"))
    http = _mapping(source.get("http"))
    execution = _mapping(source.get("execution"))
    bundle = {
        "contract_version": source.get("contract_version"),
        "test_id": source.get("test_id"),
        "exact_input": sanitize_pii(source.get("exact_input")),
        "executed_at": source.get("executed_at"),
        "account_type": source.get("account_type"),
        "release": {
            "sha": release.get("sha"),
            "frontend_image_digest": release.get("frontend_image_digest"),
            "backend_image_digest": release.get("backend_image_digest"),
        },
        "browser_evidence": {
            "input_response_screenshot": browser.get(
                "input_response_screenshot"
            ),
        },
        "http": {
            "status_code": http.get("status_code"),
            "public_response": sanitize_pii(
                deepcopy(http.get("public_response"))
            ),
        },
        "execution": {
            "routing_intent": execution.get("routing_intent"),
            "node_list": deepcopy(execution.get("node_list")),
            "semantic_status": execution.get("semantic_status"),
            "job_id": execution.get("job_id"),
            "correlation_id": execution.get("correlation_id"),
        },
        "sanitized_logs": sanitize_pii(deepcopy(source.get("sanitized_logs"))),
    }
    errors = validate_e2e_evidence_bundle(bundle)
    if errors:
        raise EvidenceBundleValidationError(errors)
    return bundle


def validate_e2e_evidence_bundle(payload: Mapping[str, Any]) -> list[str]:
    """Return stable validation codes without returning rejected source values."""

    source = payload if isinstance(payload, Mapping) else {}
    errors = _unexpected_errors(source)
    errors.extend(
        f"missing:{path}"
        for path in _REQUIRED_PATHS
        if not _has_path(source, path)
    )
    if any(error.startswith("missing:") for error in errors):
        return errors

    release = _mapping(source.get("release"))
    browser = _mapping(source.get("browser_evidence"))
    http = _mapping(source.get("http"))
    execution = _mapping(source.get("execution"))

    _require(
        errors,
        source.get("contract_version") == "pilot_e2e_evidence.v1",
        "invalid:contract_version",
    )
    _require(
        errors,
        _matches(_TEST_ID_RE, source.get("test_id")),
        "invalid:test_id",
    )
    _require(
        errors,
        isinstance(source.get("exact_input"), str)
        and bool(source["exact_input"].strip()),
        "invalid:exact_input",
    )
    _require(
        errors,
        _is_aware_iso_datetime(source.get("executed_at")),
        "invalid:executed_at",
    )
    _require(
        errors,
        source.get("account_type") in _ACCOUNT_TYPES,
        "invalid:account_type",
    )
    _require(
        errors,
        _matches(_SHA_RE, release.get("sha")),
        "invalid:release.sha",
    )
    _require(
        errors,
        _matches(_DIGEST_RE, release.get("frontend_image_digest")),
        "invalid:release.frontend_image_digest",
    )
    _require(
        errors,
        _matches(_DIGEST_RE, release.get("backend_image_digest")),
        "invalid:release.backend_image_digest",
    )

    screenshot = browser.get("input_response_screenshot")
    _require(
        errors,
        isinstance(screenshot, str) and bool(screenshot.strip()),
        "invalid:browser_evidence.input_response_screenshot",
    )
    if isinstance(screenshot, str) and not _ARTIFACT_RE.fullmatch(screenshot):
        errors.append("unsafe:browser_evidence.input_response_screenshot")

    status_code = http.get("status_code")
    _require(
        errors,
        isinstance(status_code, int)
        and not isinstance(status_code, bool)
        and 100 <= status_code <= 599,
        "invalid:http.status_code",
    )
    _require(
        errors,
        isinstance(http.get("public_response"), Mapping),
        "invalid:http.public_response",
    )
    _require(
        errors,
        _matches(_IDENTIFIER_RE, execution.get("routing_intent")),
        "invalid:execution.routing_intent",
    )

    node_list = execution.get("node_list")
    valid_node_list = (
        isinstance(node_list, list)
        and all(_matches(_IDENTIFIER_RE, item) for item in node_list)
    )
    _require(errors, valid_node_list, "invalid:execution.node_list")
    _require(
        errors,
        execution.get("semantic_status") in ANALYSIS_SEMANTIC_STATUSES,
        "invalid:execution.semantic_status",
    )
    _require(
        errors,
        _matches(_IDENTIFIER_RE, execution.get("job_id")),
        "invalid:execution.job_id",
    )
    _require(
        errors,
        _matches(_IDENTIFIER_RE, execution.get("correlation_id")),
        "invalid:execution.correlation_id",
    )
    _require(
        errors,
        isinstance(source.get("sanitized_logs"), list)
        and all(isinstance(item, Mapping) for item in source["sanitized_logs"]),
        "invalid:sanitized_logs",
    )
    errors.extend(_unsafe_errors(source))
    return list(dict.fromkeys(errors))


def _unsafe_errors(value: Any) -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        if _contains_unsafe(value.get("exact_input")):
            errors.append("unsafe:exact_input")
        http = value.get("http")
        if isinstance(http, Mapping) and _contains_unsafe(
            http.get("public_response")
        ):
            errors.append("unsafe:http.public_response")
        if _contains_unsafe(value.get("sanitized_logs")):
            errors.append("unsafe:sanitized_logs")
        browser = value.get("browser_evidence")
        if isinstance(browser, Mapping):
            screenshot = browser.get("input_response_screenshot")
            if isinstance(screenshot, str) and not _ARTIFACT_RE.fullmatch(
                screenshot
            ):
                errors.append(
                    "unsafe:browser_evidence.input_response_screenshot"
                )
    return errors


def _contains_unsafe(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(marker in normalized_key for marker in _UNSAFE_KEY_MARKERS):
                return True
            if _contains_unsafe(item):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return any(_contains_unsafe(item) for item in value)
    if not isinstance(value, str):
        return False
    lowered = value.strip().lower()
    return (
        "s3://" in lowered
        or "file://" in lowered
        or re.search(r"(?:^|\s)[a-z]:[\\/]", lowered) is not None
        or re.search(r"(?:^|\s)(?:/|\\\\)[^\s]+", lowered) is not None
        or (
            ("http://" in lowered or "https://" in lowered)
            and any(marker in lowered for marker in _SIGNED_URL_MARKERS)
        )
    )


def _unexpected_errors(value: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if any(key not in _ALLOWED_FIELDS["top_level"] for key in value):
        errors.append("unexpected:top_level")
    for section in ("release", "browser_evidence", "http", "execution"):
        nested = value.get(section)
        if isinstance(nested, Mapping) and any(
            key not in _ALLOWED_FIELDS[section] for key in nested
        ):
            errors.append(f"unexpected:{section}")
    return errors


def _has_path(value: Mapping[str, Any], path: str) -> bool:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False
        current = current[part]
    return True


def _is_aware_iso_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _matches(pattern: re.Pattern[str], value: Any) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _require(errors: list[str], condition: bool, error: str) -> None:
    if not condition:
        errors.append(error)
