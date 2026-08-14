"""Fail-closed filesystem contract for canonical local attachment staging."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import BinaryIO


DEFAULT_ATTACHMENT_STAGING_ROOT = "backend/media/mock_object_storage/attachment_staging"
LOCAL_STAGING_URI_PREFIX = "local://attachment-staging/"
_ATTACHMENT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_FILENAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
_REPARSE_POINT_ATTRIBUTE = 0x0400


class UnsafeAttachmentStagingPathError(ValueError):
    """Raised before local staging I/O can cross a link or root boundary."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"unsafe attachment staging path: {reason}")


def staging_root() -> Path:
    """Return the configured root without resolving away a linked component."""

    configured_root = ""
    try:
        from django.conf import settings

        if settings.configured:
            configured_root = _text(getattr(settings, "ATTACHMENT_STAGING_ROOT", ""))
    except ImportError:
        configured_root = ""
    selected = configured_root or _text(os.environ.get("ATTACHMENT_STAGING_ROOT")) or DEFAULT_ATTACHMENT_STAGING_ROOT
    return Path(os.path.abspath(selected))


def validate_attachment_id(value: str) -> str:
    normalized = _text(value)
    if not _ATTACHMENT_ID_PATTERN.fullmatch(normalized):
        raise ValueError("attachment_id must use the canonical safe identifier format")
    return normalized


def validate_staging_filename(value: str) -> str:
    normalized = _text(value)
    if Path(normalized).name != normalized or not _FILENAME_PATTERN.fullmatch(normalized):
        raise UnsafeAttachmentStagingPathError("filename is not a single safe staging path segment")
    return normalized


def prepare_staged_attachment_directory(attachment_id: str) -> Path:
    """Create an attachment directory only after link and containment checks."""

    root = staging_root()
    _verify_safe_path(root, root)
    root.mkdir(parents=True, exist_ok=True)
    _verify_safe_path(root, root)
    directory = root / validate_attachment_id(attachment_id)
    _verify_safe_path(root, directory)
    directory.mkdir(exist_ok=True)
    _verify_safe_path(root, directory)
    return directory


def staged_attachment_directory(attachment_id: str) -> Path:
    root = staging_root()
    directory = root / validate_attachment_id(attachment_id)
    _verify_safe_path(root, directory)
    return directory


def staged_attachment_file_path(
    attachment_id: str,
    filename: str,
    *,
    create_directory: bool = False,
) -> Path:
    directory = (
        prepare_staged_attachment_directory(attachment_id)
        if create_directory
        else staged_attachment_directory(attachment_id)
    )
    path = directory / validate_staging_filename(filename)
    _verify_safe_path(staging_root(), path)
    return path


def open_staged_attachment_file_for_write(attachment_id: str, filename: str) -> BinaryIO:
    path = staged_attachment_file_path(attachment_id, filename, create_directory=True)
    _verify_safe_path(staging_root(), path)
    return path.open("wb")


def delete_staged_attachment_file(attachment_id: str, filename: str) -> bool:
    path = staged_attachment_file_path(attachment_id, filename)
    _verify_safe_path(staging_root(), path)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def remove_empty_staged_attachment_directory(attachment_id: str) -> bool:
    directory = staged_attachment_directory(attachment_id)
    _verify_safe_path(staging_root(), directory)
    try:
        directory.rmdir()
    except OSError:
        return False
    return True


def write_staged_attachment_metadata(attachment_id: str, content: str) -> Path:
    path = staged_attachment_file_path(attachment_id, "metadata.json", create_directory=True)
    _verify_safe_path(staging_root(), path)
    path.write_text(content, encoding="utf-8")
    return path


def read_staged_attachment_metadata(attachment_id: str) -> str:
    path = staged_attachment_file_path(attachment_id, "metadata.json")
    _verify_safe_path(staging_root(), path)
    return path.read_text(encoding="utf-8")


def read_staged_source_bytes(source_uri: str) -> bytes | None:
    parsed = _parse_local_staging_uri(source_uri)
    if parsed is None:
        return None
    attachment_id, filename = parsed
    path = staged_attachment_file_path(attachment_id, filename)
    _verify_safe_path(staging_root(), path)
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def cleanup_staged_source_uri(source_uri: str, *, attachment_id: str = "") -> dict[str, str] | None:
    parsed = _parse_local_staging_uri(source_uri)
    if parsed is None:
        if not attachment_id:
            return None
        normalized_attachment_id = validate_attachment_id(attachment_id)
        source_filename = ""
    else:
        normalized_attachment_id, source_filename = parsed

    source_deleted = (
        delete_staged_attachment_file(normalized_attachment_id, source_filename) if source_filename else False
    )
    metadata_deleted = delete_staged_attachment_file(normalized_attachment_id, "metadata.json")
    directory_deleted = remove_empty_staged_attachment_directory(normalized_attachment_id)
    return {
        "status": "deleted" if source_deleted or metadata_deleted else "not_found",
        "source_status": "deleted" if source_deleted else "not_found",
        "metadata_status": "deleted" if metadata_deleted else "not_found",
        "directory_status": "deleted" if directory_deleted else "retained",
    }


def local_staging_path_from_uri(source_uri: str) -> Path | None:
    parsed = _parse_local_staging_uri(source_uri)
    if parsed is None:
        return None
    attachment_id, filename = parsed
    return staged_attachment_file_path(attachment_id, filename)


def _parse_local_staging_uri(source_uri: str) -> tuple[str, str] | None:
    value = _text(source_uri)
    if not value.startswith(LOCAL_STAGING_URI_PREFIX):
        return None
    relative = value.removeprefix(LOCAL_STAGING_URI_PREFIX).strip("/")
    parts = PurePosixPath(relative).parts
    if len(parts) != 2 or any(part in {"", ".", ".."} for part in parts):
        raise UnsafeAttachmentStagingPathError("local staging URI must contain attachment ID and filename only")
    return validate_attachment_id(parts[0]), validate_staging_filename(parts[1])


def _verify_safe_path(root: Path, candidate: Path) -> None:
    normalized_root = _absolute_path(root)
    normalized_candidate = _absolute_path(candidate)
    _reject_existing_links(normalized_root)
    _reject_existing_links(normalized_candidate)
    resolved_root = normalized_root.resolve(strict=False)
    resolved_candidate = normalized_candidate.resolve(strict=False)
    if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
        raise UnsafeAttachmentStagingPathError("candidate escaped the configured staging root")


def _reject_existing_links(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        try:
            details = os.lstat(current)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise UnsafeAttachmentStagingPathError(f"cannot inspect path component {current}") from exc
        if stat.S_ISLNK(details.st_mode) or bool(getattr(details, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE):
            raise UnsafeAttachmentStagingPathError(f"linked or reparse path component {current}")


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()
