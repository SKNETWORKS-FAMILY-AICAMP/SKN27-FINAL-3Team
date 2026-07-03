"""File scan policy service for canonical upload handoff gating."""

from __future__ import annotations

import base64
import json
import re
import socket
import struct
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from chatbot.models import UploadedFile, UploadedFileStatus


FILE_SCAN_RESULT_VERSION = "file_scan_result.v1"
ATTACHMENT_SCAN_GATE_VERSION = "attachment_scan_gate.v1"
DEFAULT_MAX_SCAN_BYTES = 50 * 1024 * 1024
DEFAULT_SCAN_TIMEOUT_SECONDS = 10
DEFAULT_EXTERNAL_INLINE_MAX_BYTES = 5 * 1024 * 1024
DANGEROUS_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".exe",
    ".jar",
    ".js",
    ".msi",
    ".ps1",
    ".scr",
    ".vbs",
}
PII_PATTERNS = (
    re.compile(r"01[016789]-?\d{3,4}-?\d{4}"),
    re.compile(r"\d{6}-[1-4]\d{6}"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)


def scan_uploaded_file(uploaded_file: UploadedFile) -> dict[str, Any]:
    """Run the local policy scanner and persist READY/REJECTED state."""

    now = timezone.now()
    with transaction.atomic():
        locked_file = UploadedFile.objects.select_for_update().get(pk=uploaded_file.pk)
        locked_file.status = UploadedFileStatus.SCANNING
        locked_file.scan_status = "scanning"
        metadata = dict(locked_file.metadata or {})
        metadata["scan_started_at"] = now.isoformat()
        locked_file.metadata = metadata
        locked_file.save(update_fields=["status", "scan_status", "metadata", "updated_at"])

    result = build_file_scan_result(locked_file)
    final_status = (
        UploadedFileStatus.REJECTED
        if result["status"] == "rejected"
        else UploadedFileStatus.READY
    )
    final_scan_status = "rejected" if result["status"] == "rejected" else "clean"

    with transaction.atomic():
        scanned_file = UploadedFile.objects.select_for_update().get(pk=uploaded_file.pk)
        metadata = dict(scanned_file.metadata or {})
        checks = dict(metadata.get("checks") or {})
        checks["file_scan"] = {
            "contract_version": FILE_SCAN_RESULT_VERSION,
            "status": result["status"],
            "scan_status": final_scan_status,
            "finding_count": len(result["findings"]),
        }
        metadata["checks"] = checks
        metadata["scan_result"] = result
        metadata["scan_completed_at"] = result["scanned_at"]
        scanned_file.metadata = metadata
        scanned_file.status = final_status
        scanned_file.scan_status = final_scan_status
        scanned_file.privacy_risk = bool(result["privacy_risk"])
        scanned_file.agent_handoff = _handoff_with_scan(scanned_file.agent_handoff, result)
        scanned_file.save(
            update_fields=[
                "status",
                "scan_status",
                "privacy_risk",
                "agent_handoff",
                "metadata",
                "updated_at",
            ]
        )

    return result


def process_uploaded_file_scans(*, limit: int = 20) -> dict[str, Any]:
    queryset = (
        UploadedFile.objects.filter(
            status__in=[
                UploadedFileStatus.PENDING,
                UploadedFileStatus.UPLOADED,
                UploadedFileStatus.SCANNING,
            ]
        )
        .exclude(scan_status="clean")
        .exclude(scan_status="rejected")
        .order_by("created_at")
    )
    if limit > 0:
        queryset = queryset[:limit]

    results = []
    clean_count = 0
    rejected_count = 0
    for uploaded_file in queryset:
        result = scan_uploaded_file(uploaded_file)
        results.append(result)
        if result["status"] == "rejected":
            rejected_count += 1
        else:
            clean_count += 1

    return {
        "contract_version": "file_scan_batch.v1",
        "status": "pass" if rejected_count == 0 else "warn",
        "processed": len(results),
        "clean": clean_count,
        "rejected": rejected_count,
        "results": results,
    }


def build_file_scan_result(uploaded_file: UploadedFile) -> dict[str, Any]:
    findings = []
    max_bytes = int(getattr(settings, "FILE_SCAN_MAX_BYTES", DEFAULT_MAX_SCAN_BYTES))
    size_bytes = uploaded_file.size_bytes or 0
    extension = Path(uploaded_file.original_filename or "").suffix.lower()
    searchable_text = _searchable_metadata(uploaded_file)
    provider = str(getattr(settings, "FILE_SCAN_PROVIDER", "local_policy") or "local_policy")

    if size_bytes > max_bytes:
        findings.append(
            {
                "category": "policy",
                "code": "file_too_large",
                "severity": "high",
                "message": "File size exceeds the configured scan limit.",
            }
        )
    if extension in DANGEROUS_EXTENSIONS:
        findings.append(
            {
                "category": "policy",
                "code": "dangerous_extension",
                "severity": "high",
                "message": "Executable or script-like files are not accepted.",
                "extension": extension,
            }
        )
    if "eicar" in searchable_text.lower():
        findings.append(
            {
                "category": "virus",
                "code": "mock_eicar_signature",
                "severity": "critical",
                "message": "Mock virus signature detected.",
            }
        )

    pii_matches = []
    for pattern in PII_PATTERNS:
        if pattern.search(searchable_text):
            pii_matches.append(pattern.pattern)
    if pii_matches:
        findings.append(
            {
                "category": "pii",
                "code": "pii_pattern_detected",
                "severity": "medium",
                "message": "Potential personal information pattern detected in metadata.",
                "pattern_count": len(pii_matches),
            }
        )

    reject_pii = bool(getattr(settings, "FILE_SCAN_REJECT_PII", False))
    rejected = any(item["severity"] in {"high", "critical"} for item in findings)
    if reject_pii and any(item["category"] == "pii" for item in findings):
        rejected = True

    provider_findings = _provider_scan_findings(uploaded_file, provider=provider)
    findings.extend(provider_findings)
    if any(item["severity"] in {"high", "critical"} for item in provider_findings):
        rejected = True

    return {
        "contract_version": FILE_SCAN_RESULT_VERSION,
        "scanner": provider,
        "attachment_id": uploaded_file.attachment_id,
        "status": "rejected" if rejected else "clean",
        "scan_status": "rejected" if rejected else "clean",
        "privacy_risk": bool(pii_matches),
        "findings": findings,
        "scanned_at": timezone.now().isoformat(),
        "policy": {
            "max_bytes": max_bytes,
            "dangerous_extensions": sorted(DANGEROUS_EXTENSIONS),
            "reject_pii": reject_pii,
            "provider": provider,
        },
    }


def _provider_scan_findings(uploaded_file: UploadedFile, *, provider: str) -> list[dict[str, Any]]:
    if provider == "local_policy":
        return []
    if provider == "clamav":
        return _clamav_scan_findings(uploaded_file)
    if provider == "external":
        return _external_scan_findings(uploaded_file)
    return [_scanner_unavailable_finding(provider=provider, reason="unsupported_provider")]


def _clamav_scan_findings(uploaded_file: UploadedFile) -> list[dict[str, Any]]:
    host = str(getattr(settings, "FILE_SCAN_CLAMAV_HOST", "") or "").strip()
    port = int(getattr(settings, "FILE_SCAN_CLAMAV_PORT", 3310) or 3310)
    file_path = _local_upload_path(uploaded_file)
    if not host:
        return [_scanner_unavailable_finding(provider="clamav", reason="missing_host")]
    if file_path is None or not file_path.exists():
        return [_scanner_unavailable_finding(provider="clamav", reason="source_file_unavailable")]

    try:
        response = _clamav_instream_scan(host=host, port=port, file_path=file_path)
    except Exception as exc:
        return [_scanner_unavailable_finding(provider="clamav", reason=_exception_reason(exc), exc=exc)]
    return _clamav_findings_from_response(response)


def _external_scan_findings(uploaded_file: UploadedFile) -> list[dict[str, Any]]:
    url = str(getattr(settings, "FILE_SCAN_EXTERNAL_URL", "") or "").strip()
    api_key = str(getattr(settings, "FILE_SCAN_EXTERNAL_API_KEY", "") or "").strip()
    if not url:
        return [_scanner_unavailable_finding(provider="external", reason="missing_url")]
    if not api_key:
        return [_scanner_unavailable_finding(provider="external", reason="missing_api_key")]

    try:
        response = _post_external_scan_request(uploaded_file, url=url, api_key=api_key)
    except Exception as exc:
        return [_scanner_unavailable_finding(provider="external", reason=_exception_reason(exc), exc=exc)]
    return _external_findings_from_response(response)


def apply_attachment_scan_gate(payload: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(payload)
    attachments = enriched.get("attachments")
    if not isinstance(attachments, list):
        return enriched

    allowed_attachments = []
    blocked_attachments = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        attachment_id = str(attachment.get("attachment_id") or "")
        uploaded_file = UploadedFile.objects.filter(attachment_id=attachment_id).first() if attachment_id else None
        if uploaded_file is None:
            allowed_attachments.append(attachment)
            continue
        if uploaded_file.status == UploadedFileStatus.READY and uploaded_file.scan_status == "clean":
            allowed_attachments.append(_attachment_handoff(uploaded_file, attachment))
            continue
        blocked_attachments.append(_blocked_attachment(uploaded_file))

    enriched["attachments"] = allowed_attachments
    if blocked_attachments:
        enriched["blocked_attachments"] = blocked_attachments
    enriched["attachment_scan_policy"] = {
        "contract_version": ATTACHMENT_SCAN_GATE_VERSION,
        "allowed_count": len(allowed_attachments),
        "blocked_count": len(blocked_attachments),
    }
    return enriched


def _handoff_with_scan(agent_handoff: Any, result: dict[str, Any]) -> dict[str, Any]:
    handoff = dict(agent_handoff or {})
    handoff["scan_status"] = result["scan_status"]
    handoff["file_scan_result"] = {
        "contract_version": result["contract_version"],
        "status": result["status"],
        "privacy_risk": result["privacy_risk"],
        "finding_count": len(result["findings"]),
    }
    return handoff


def _attachment_handoff(uploaded_file: UploadedFile, request_attachment: dict[str, Any]) -> dict[str, Any]:
    handoff = dict(uploaded_file.agent_handoff or {})
    handoff.update(
        {
            "attachment_id": uploaded_file.attachment_id,
            "purpose": uploaded_file.purpose,
            "type": uploaded_file.file_type,
            "storage_uri": uploaded_file.storage_uri,
            "content_type": uploaded_file.content_type,
            "size_bytes": uploaded_file.size_bytes or 0,
            "status": uploaded_file.status,
            "scan_status": uploaded_file.scan_status,
            "privacy_risk": uploaded_file.privacy_risk,
        }
    )
    handoff.update({key: value for key, value in request_attachment.items() if value is not None})
    handoff["resolution_status"] = "scan_ready"
    return handoff


def _blocked_attachment(uploaded_file: UploadedFile) -> dict[str, Any]:
    reason = "scan_rejected" if uploaded_file.status == UploadedFileStatus.REJECTED else "scan_not_ready"
    return {
        "contract_version": ATTACHMENT_SCAN_GATE_VERSION,
        "attachment_id": uploaded_file.attachment_id,
        "purpose": uploaded_file.purpose,
        "type": uploaded_file.file_type,
        "status": uploaded_file.status,
        "scan_status": uploaded_file.scan_status,
        "reason": reason,
        "required_action": "replace_file" if reason == "scan_rejected" else "wait_for_file_scan",
    }


def _clamav_instream_scan(*, host: str, port: int, file_path: Path) -> str:
    timeout = int(getattr(settings, "FILE_SCAN_TIMEOUT_SECONDS", DEFAULT_SCAN_TIMEOUT_SECONDS) or DEFAULT_SCAN_TIMEOUT_SECONDS)
    with closing(socket.create_connection((host, port), timeout=timeout)) as sock:
        sock.settimeout(timeout)
        sock.sendall(b"zINSTREAM\0")
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                sock.sendall(struct.pack("!I", len(chunk)))
                sock.sendall(chunk)
        sock.sendall(struct.pack("!I", 0))
        response = sock.recv(4096)
    return response.decode("utf-8", errors="replace").strip("\0\r\n ")


def _post_external_scan_request(uploaded_file: UploadedFile, *, url: str, api_key: str) -> dict[str, Any]:
    timeout = int(getattr(settings, "FILE_SCAN_TIMEOUT_SECONDS", DEFAULT_SCAN_TIMEOUT_SECONDS) or DEFAULT_SCAN_TIMEOUT_SECONDS)
    payload = _external_scan_payload(uploaded_file)
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib_request.urlopen(request, timeout=timeout) as response:
        response_body = response.read()
    if not response_body:
        return {"status": "clean"}
    return json.loads(response_body.decode("utf-8"))


def _external_scan_payload(uploaded_file: UploadedFile) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": "file_scan_external_request.v1",
        "attachment_id": uploaded_file.attachment_id,
        "filename": uploaded_file.original_filename,
        "content_type": uploaded_file.content_type,
        "size_bytes": uploaded_file.size_bytes or 0,
        "storage_uri": uploaded_file.storage_uri,
        "metadata": _safe_external_metadata(uploaded_file.metadata or {}),
    }
    file_path = _local_upload_path(uploaded_file)
    inline_max = int(
        getattr(settings, "FILE_SCAN_EXTERNAL_INLINE_MAX_BYTES", DEFAULT_EXTERNAL_INLINE_MAX_BYTES)
        or DEFAULT_EXTERNAL_INLINE_MAX_BYTES
    )
    if file_path is not None and file_path.exists() and file_path.stat().st_size <= inline_max:
        payload["file_base64"] = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return payload


def _safe_external_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe = dict(metadata)
    for key in list(safe):
        if any(token in key.lower() for token in ("secret", "token", "password", "api_key")):
            safe[key] = "[redacted]"
    return safe


def _clamav_findings_from_response(response: str) -> list[dict[str, Any]]:
    normalized = response.strip()
    if not normalized or normalized.endswith(": OK") or normalized == "OK":
        return []
    if "FOUND" in normalized:
        signature = normalized.rsplit(":", 1)[-1].replace("FOUND", "").strip()
        return [
            {
                "category": "virus",
                "code": "clamav_signature_found",
                "severity": "critical",
                "message": "ClamAV reported a malware signature.",
                "signature": signature,
            }
        ]
    return [_scanner_unavailable_finding(provider="clamav", reason="unexpected_response", message=normalized)]


def _external_findings_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    raw_findings = response.get("findings")
    if isinstance(raw_findings, list):
        findings = [_normalize_provider_finding(item, provider="external") for item in raw_findings if isinstance(item, dict)]
        if findings:
            return findings

    status = str(response.get("status") or response.get("verdict") or "clean").lower()
    if status in {"clean", "pass", "ok", "allowed"}:
        return []
    if status in {"malicious", "infected", "rejected", "blocked", "fail", "failed"}:
        return [
            {
                "category": "virus",
                "code": str(response.get("code") or "external_scan_rejected"),
                "severity": "critical",
                "message": str(response.get("message") or "External scan provider rejected the file."),
            }
        ]
    return [_scanner_unavailable_finding(provider="external", reason="unexpected_response", message=json.dumps(response, ensure_ascii=False)[:180])]


def _normalize_provider_finding(item: dict[str, Any], *, provider: str) -> dict[str, Any]:
    severity = str(item.get("severity") or "").lower()
    if severity not in {"low", "medium", "high", "critical"}:
        severity = "critical" if str(item.get("category") or "").lower() in {"virus", "malware"} else "medium"
    return {
        "category": str(item.get("category") or "provider"),
        "code": str(item.get("code") or f"{provider}_finding"),
        "severity": severity,
        "message": str(item.get("message") or "File scan provider returned a finding."),
        **{key: value for key, value in item.items() if key not in {"category", "code", "severity", "message"}},
    }


def _scanner_unavailable_finding(
    *,
    provider: str,
    reason: str,
    exc: Exception | None = None,
    message: str = "",
) -> dict[str, Any]:
    finding = {
        "category": "scanner",
        "code": "scanner_unavailable",
        "severity": "critical",
        "message": message or "Configured file scan provider could not scan the uploaded file.",
        "provider": provider,
        "reason": reason,
    }
    if exc is not None:
        finding["error_class"] = exc.__class__.__name__
    return finding


def _exception_reason(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, urllib_error.HTTPError):
        return f"http_{exc.code}"
    if isinstance(exc, urllib_error.URLError):
        return "url_error"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json_response"
    if isinstance(exc, OSError):
        return "connection_failed"
    return "provider_error"


def _local_upload_path(uploaded_file: UploadedFile) -> Path | None:
    storage_uri = str(uploaded_file.storage_uri or "")
    if not storage_uri.startswith("mock://uploads/"):
        return None
    relative = storage_uri.removeprefix("mock://uploads/").strip("/")
    if not relative:
        return None
    root = Path(getattr(settings, "MOCK_UPLOAD_ROOT", "") or "backend/media/mock_uploads").resolve()
    candidate = (root / Path(*Path(relative).parts)).resolve()
    if root != candidate and root not in candidate.parents:
        return None
    return candidate


def _searchable_metadata(uploaded_file: UploadedFile) -> str:
    values = [
        uploaded_file.attachment_id,
        uploaded_file.original_filename,
        uploaded_file.content_type,
        uploaded_file.storage_uri,
        json.dumps(uploaded_file.metadata or {}, ensure_ascii=False, default=str),
    ]
    return "\n".join(str(value or "") for value in values)
