"""Configurable retention rules shared by Case and file persistence."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone


MEDIA_FILE_TYPES = {"image", "video"}


def upload_retention_days(
    *,
    owner_id: str,
    guest_id: str = "",
    file_type: str = "",
    content_type: str = "",
) -> int:
    """Return the configured retention period for an uploaded object."""

    normalized_file_type = str(file_type or "").strip().lower()
    normalized_content_type = str(content_type or "").strip().lower()
    if normalized_file_type in MEDIA_FILE_TYPES or normalized_content_type.startswith(
        ("image/", "video/")
    ):
        return int(settings.RAW_MEDIA_RETENTION_DAYS)
    if str(owner_id or "").strip():
        return int(settings.USER_RETENTION_DAYS)
    if str(guest_id or "").strip():
        return int(settings.GUEST_RETENTION_DAYS)
    return int(settings.ANONYMOUS_RETENTION_DAYS)


def upload_retention_expires_at(
    *,
    owner_id: str,
    guest_id: str = "",
    file_type: str = "",
    content_type: str = "",
    now: datetime | None = None,
) -> datetime:
    days = upload_retention_days(
        owner_id=owner_id,
        guest_id=guest_id,
        file_type=file_type,
        content_type=content_type,
    )
    return (now or timezone.now()) + timedelta(days=days)
