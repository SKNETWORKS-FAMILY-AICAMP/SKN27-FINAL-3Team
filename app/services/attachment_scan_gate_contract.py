"""Neutral provenance contract for canonical scan-ready attachment handoffs."""

from __future__ import annotations

from typing import Any


class _CanonicalScanGateMarker(str):
    """JSON-safe in-process provenance marker that preserves identity on copies."""

    __slots__ = ()

    def __new__(cls) -> "_CanonicalScanGateMarker":
        return str.__new__(cls, "canonical-scan-gate")

    def __deepcopy__(self, memo: dict[int, Any]) -> "_CanonicalScanGateMarker":
        del memo
        return self


CANONICAL_SCAN_GATE_MARKER = _CanonicalScanGateMarker()


def is_canonical_scan_ready_reference(reference: dict[str, Any]) -> bool:
    """Accept only the in-process canonical scan-gate handoff contract."""

    object_storage = reference.get("object_storage")
    storage_uri = str(reference.get("storage_uri") or "").strip()
    return (
        isinstance(object_storage, dict)
        and reference.get("_canonical_scan_gate") is CANONICAL_SCAN_GATE_MARKER
        and reference.get("resolution_status") == "scan_ready"
        and reference.get("status") == "ready"
        and reference.get("scan_status") == "clean"
        and storage_uri.startswith("s3://")
        and object_storage.get("resource_type") == "uploaded_file"
        and object_storage.get("status") == "ready"
        and object_storage.get("storage_uri") == storage_uri
    )


def merge_canonical_scan_ready_reference(reference: dict[str, Any]) -> dict[str, Any]:
    """Project a verified canonical handoff without leaking its private marker."""

    if not is_canonical_scan_ready_reference(reference):
        raise ValueError("reference is not a canonical scan-ready handoff")
    attachment = {
        **reference,
        "resolution_status": "scan_ready",
        "metadata_source": "canonical_scan_gate",
    }
    return {
        key: value
        for key, value in attachment.items()
        if key != "_canonical_scan_gate" and value is not None
    }
