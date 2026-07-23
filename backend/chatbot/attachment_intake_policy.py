"""Canonical upload MIME and purpose policy for chat attachments."""

from __future__ import annotations


_MIME_TO_FILE_TYPE = {
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "application/pdf": "pdf",
    "video/mp4": "video",
    "video/quicktime": "video",
}
_DOCUMENT_PURPOSES = {
    "fine_notice",
    "accident_scene",
    "evidence",
    "traffic_accident_confirmation",
    "unknown",
}
_PURPOSE_ALIASES = {
    "supporting_evidence": "evidence",
}


def classify_attachment_intake(
    *,
    content_type: str,
    filename: str,
    purpose: str,
) -> dict[str, str | bool]:
    """Return the stable upload admission and routing decision.

    MIME determines the modality.  The filename deliberately has no authority
    over media admission; it is accepted to keep the call site explicit and to
    allow a later server-side signature check without changing this contract.
    """

    del filename
    normalized_mime = str(content_type or "").split(";", 1)[0].strip().lower()
    file_type = _MIME_TO_FILE_TYPE.get(normalized_mime, "")
    requested_purpose = str(purpose or "unknown").strip() or "unknown"
    requested_purpose = _PURPOSE_ALIASES.get(requested_purpose, requested_purpose)

    if not file_type:
        return {
            "accepted": False,
            "error_code": "unsupported_media_type",
            "file_type": "",
            "routing_purpose": "",
            "purpose_conflict": False,
        }

    if file_type == "video":
        conflict = requested_purpose not in {"unknown", "blackbox_video"}
        return {
            "accepted": not conflict,
            "error_code": "purpose_media_mismatch" if conflict else "",
            "file_type": "video",
            "routing_purpose": "blackbox_video",
            "purpose_conflict": conflict,
        }

    accepted = requested_purpose in _DOCUMENT_PURPOSES
    return {
        "accepted": accepted,
        "error_code": "purpose_media_mismatch" if not accepted else "",
        "file_type": file_type,
        "routing_purpose": requested_purpose,
        "purpose_conflict": not accepted,
    }
