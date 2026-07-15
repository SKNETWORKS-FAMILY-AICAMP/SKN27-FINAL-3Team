"""Validate immutable production RAG seed bundles without Django dependencies."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import struct
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterator, Mapping
from urllib.parse import parse_qsl, urlsplit

from app.services.legal_rag_service import LEGAL_SOURCE_TYPES


RAG_SEED_CONTRACT_VERSION = "production_rag_seed_manifest.v1"
REQUIRED_RAG_SEED_ROLES = (
    "legal_chunks",
    "legal_embeddings",
    "review_case_chunks",
    "precedent_fault_ratio_chunks",
)
LEGAL_EMBEDDING_DIMENSIONS = 1024
SUPPORTED_PRODUCTION_EMBEDDING_PROVIDERS = frozenset(
    {"sentence-transformers", "openai"}
)
TEXT_ML_MIN_CHUNK_TEXT_LENGTH = 50
LEGAL_VARCHAR_LIMITS = {
    "chunk_id": 255,
    "source_id": 100,
    "source_name": 255,
    "source_type": 50,
    "chunk_type": 50,
    "article_no": 50,
    "appendix_no": 50,
    "form_no": 50,
    "embedding_provider": 50,
    "embedding_model": 255,
}
_ELASTICSEARCH_FORBIDDEN_INDEX_CHARACTERS = frozenset('\\/*?"<>|,#:')
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CREDENTIAL_QUERY_KEYS = frozenset(
    {
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


class RagSeedValidationError(ValueError):
    """Raised when a RAG seed bundle is unsafe, incomplete, or corrupt."""


@dataclass(frozen=True)
class RagSeedArtifact:
    role: str
    relative_path: str
    path: Path
    sha256: str
    byte_count: int
    row_count: int


@dataclass(frozen=True)
class RagSeedBundle:
    contract_version: str
    manifest_path: Path
    artifacts: Mapping[str, RagSeedArtifact]
    embedding_space: Mapping[str, Any]


def build_rag_seed_manifest(
    *,
    bundle_root: Path,
    artifact_paths: Mapping[str, str | Path],
    manifest_path: Path,
) -> dict[str, Any]:
    """Build and atomically write a validated manifest for four JSONL artifacts."""

    root = Path(bundle_root).resolve()
    if not root.is_dir():
        raise RagSeedValidationError("bundle_root must be an existing directory")
    _validate_exact_roles(artifact_paths.keys())
    target = _manifest_target(root, Path(manifest_path))

    artifacts: list[dict[str, Any]] = []
    row_ids_by_role: dict[str, set[str]] = {}
    embedding_space: tuple[str, str, int] | None = None
    for role in REQUIRED_RAG_SEED_ROLES:
        relative_path = _normalize_relative_path(str(artifact_paths[role]))
        artifact_path = _resolve_artifact_path(root, relative_path)
        _validate_manifest_artifact_separation(target, artifact_path)
        row_count, row_ids, artifact_embedding_space = _validate_jsonl_artifact(
            role,
            artifact_path,
        )
        byte_count = artifact_path.stat().st_size
        artifacts.append(
            {
                "role": role,
                "path": relative_path,
                "sha256": _sha256(artifact_path),
                "bytes": byte_count,
                "row_count": row_count,
            }
        )
        row_ids_by_role[role] = row_ids
        if artifact_embedding_space is not None:
            embedding_space = artifact_embedding_space

    _validate_legal_id_alignment(row_ids_by_role)
    if embedding_space is None:  # Exact roles and non-empty validation make this defensive only.
        raise RagSeedValidationError("legal_embeddings embedding space is required")
    manifest = {
        "contract_version": RAG_SEED_CONTRACT_VERSION,
        "embedding_space": _embedding_space_payload(embedding_space),
        "artifacts": artifacts,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(target)
    finally:
        temporary_path.unlink(missing_ok=True)
    return manifest


def load_and_validate_rag_seed_manifest(manifest_path: Path) -> RagSeedBundle:
    """Parse a manifest and verify paths, integrity metadata, and every JSONL row."""

    path = Path(manifest_path).resolve()
    if not path.is_file():
        raise RagSeedValidationError("RAG seed manifest file was not found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise RagSeedValidationError("RAG seed manifest is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise RagSeedValidationError("RAG seed manifest root must be an object")
    if payload.get("contract_version") != RAG_SEED_CONTRACT_VERSION:
        raise RagSeedValidationError(f"contract_version must be {RAG_SEED_CONTRACT_VERSION}")
    manifest_embedding_space = _manifest_embedding_space(payload.get("embedding_space"))

    artifact_items = payload.get("artifacts")
    if not isinstance(artifact_items, list):
        raise RagSeedValidationError("artifacts must be a list")
    roles = [item.get("role") if isinstance(item, dict) else None for item in artifact_items]
    if any(not isinstance(role, str) for role in roles):
        raise RagSeedValidationError("each artifact role must be a string")
    if len(roles) != len(set(roles)):
        raise RagSeedValidationError("manifest contains a duplicate artifact role")
    _validate_exact_roles(roles)

    root = path.parent.resolve()
    verified: dict[str, RagSeedArtifact] = {}
    row_ids_by_role: dict[str, set[str]] = {}
    artifact_embedding_space: tuple[str, str, int] | None = None
    for item in artifact_items:
        if not isinstance(item, dict):
            raise RagSeedValidationError("each artifact entry must be an object")
        role = str(item["role"])
        relative_path = _normalize_relative_path(item.get("path"))
        expected_sha256 = _manifest_sha256(item.get("sha256"), role)
        expected_bytes = _manifest_non_negative_int(item.get("bytes"), "bytes", role)
        expected_rows = _manifest_non_negative_int(item.get("row_count"), "row_count", role)
        artifact_path = _resolve_artifact_path(root, relative_path)

        actual_bytes = artifact_path.stat().st_size
        if actual_bytes != expected_bytes:
            raise RagSeedValidationError(f"{role} bytes mismatch")
        actual_sha256 = _sha256(artifact_path)
        if actual_sha256 != expected_sha256:
            raise RagSeedValidationError(f"{role} sha256 mismatch")
        actual_rows, row_ids, verified_embedding_space = _validate_jsonl_artifact(
            role,
            artifact_path,
        )
        if actual_rows != expected_rows:
            raise RagSeedValidationError(f"{role} row_count mismatch")

        verified[role] = RagSeedArtifact(
            role=role,
            relative_path=relative_path,
            path=artifact_path,
            sha256=actual_sha256,
            byte_count=actual_bytes,
            row_count=actual_rows,
        )
        row_ids_by_role[role] = row_ids
        if verified_embedding_space is not None:
            artifact_embedding_space = verified_embedding_space

    _validate_legal_id_alignment(row_ids_by_role)
    if artifact_embedding_space != manifest_embedding_space:
        raise RagSeedValidationError("legal_embeddings embedding space mismatch")
    return RagSeedBundle(
        contract_version=RAG_SEED_CONTRACT_VERSION,
        manifest_path=path,
        artifacts=verified,
        embedding_space=_embedding_space_payload(manifest_embedding_space),
    )


def iter_rag_seed_jsonl(artifact: RagSeedArtifact) -> Iterator[dict[str, Any]]:
    """Yield previously validated JSONL objects for a loader."""

    yield from _iter_jsonl(artifact.path, artifact.role)


def validate_elasticsearch_index_targets(
    review_case_index: Any,
    fault_ratio_index: Any,
) -> tuple[str, str]:
    """Validate two distinct Elasticsearch index names before any target write."""

    if (
        not isinstance(review_case_index, str)
        or not review_case_index.strip()
        or not isinstance(fault_ratio_index, str)
        or not fault_ratio_index.strip()
        or review_case_index == fault_ratio_index
    ):
        raise RagSeedValidationError(
            "Elasticsearch index targets must be non-empty and distinct"
        )
    review_case = _validate_elasticsearch_index_name(
        review_case_index,
        setting="REVIEW_CASE_ES_BM25_INDEX",
    )
    fault_ratio = _validate_elasticsearch_index_name(
        fault_ratio_index,
        setting="FAULT_RATIO_PRECEDENT_ES_BM25_INDEX",
    )
    return review_case, fault_ratio


def _manifest_target(root: Path, manifest_path: Path) -> Path:
    target = manifest_path if manifest_path.is_absolute() else root / manifest_path
    resolved = target.resolve(strict=False)
    if not _is_relative_to(resolved, root):
        raise RagSeedValidationError("manifest_path must stay inside bundle_root")
    if resolved.parent != root:
        raise RagSeedValidationError("manifest_path must be directly under the bundle root")
    return resolved


def _validate_manifest_artifact_separation(target: Path, artifact_path: Path) -> None:
    if target == artifact_path:
        raise RagSeedValidationError(
            "manifest target must not collide with a RAG seed artifact"
        )
    if not target.exists():
        return
    try:
        collides = target.samefile(artifact_path)
    except OSError as exc:
        raise RagSeedValidationError(
            "manifest target could not be safely compared with RAG seed artifacts"
        ) from exc
    if collides:
        raise RagSeedValidationError(
            "manifest target must not collide with a RAG seed artifact"
        )


def _validate_exact_roles(roles) -> None:
    role_list = list(roles)
    expected = set(REQUIRED_RAG_SEED_ROLES)
    actual = set(role_list)
    if len(role_list) != len(REQUIRED_RAG_SEED_ROLES) or actual != expected:
        raise RagSeedValidationError(
            "manifest must contain exactly the four required artifact roles: "
            + ", ".join(REQUIRED_RAG_SEED_ROLES)
        )


def _normalize_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RagSeedValidationError("artifact path must be a safe relative path")
    candidate = value.strip()
    posix_path = PurePosixPath(candidate)
    windows_path = PureWindowsPath(candidate)
    if (
        "\\" in candidate
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    ):
        raise RagSeedValidationError("artifact path must be a safe relative POSIX path")
    return posix_path.as_posix()


def _resolve_artifact_path(root: Path, relative_path: str) -> Path:
    try:
        resolved = (root / Path(*PurePosixPath(relative_path).parts)).resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise RagSeedValidationError("RAG seed artifact file was not found") from exc
    if not _is_relative_to(resolved, root) or not resolved.is_file():
        raise RagSeedValidationError("artifact path must be a safe relative path inside the bundle")
    return resolved


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _manifest_sha256(value: Any, role: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise RagSeedValidationError(f"{role} sha256 must be a lowercase SHA-256 digest")
    return value


def _manifest_non_negative_int(value: Any, field: str, role: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RagSeedValidationError(f"{role} {field} must be a non-negative integer")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_jsonl_artifact(
    role: str,
    path: Path,
) -> tuple[int, set[str], tuple[str, str, int] | None]:
    row_count = 0
    row_ids: set[str] = set()
    embedding_space: tuple[str, str, int] | None = None
    for line_number, row in enumerate(_iter_jsonl(path, role), start=1):
        row_id = _validate_row(role, row, line_number)
        if row_id in row_ids:
            raise RagSeedValidationError(f"{role} contains duplicate chunk_id at row {line_number}")
        row_ids.add(row_id)
        row_count += 1
        if role == "legal_embeddings":
            row_embedding_space = _embedding_space_from_row(row)
            if embedding_space is None:
                embedding_space = row_embedding_space
            elif row_embedding_space != embedding_space:
                raise RagSeedValidationError(
                    f"{role} row {line_number} must use one embedding space"
                )
    if row_count == 0:
        raise RagSeedValidationError(f"{role} must not be empty")
    return row_count, row_ids, embedding_space


def _iter_jsonl(path: Path, role: str) -> Iterator[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line, parse_constant=_reject_json_constant)
                except (json.JSONDecodeError, ValueError) as exc:
                    raise RagSeedValidationError(f"{role} has invalid JSON at row {line_number}") from exc
                if not isinstance(row, dict):
                    raise RagSeedValidationError(f"{role} row {line_number} must be an object")
                yield row
    except UnicodeDecodeError as exc:
        raise RagSeedValidationError(f"{role} must be UTF-8 JSONL") from exc


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _validate_row(role: str, row: dict[str, Any], line_number: int) -> str:
    if role == "legal_chunks":
        required = (
            "chunk_id",
            "source_id",
            "source_name",
            "source_type",
            "chunk_type",
            "provision_text",
            "normalized_text",
            "source_url",
            "enforce_date",
        )
        _require_strings(role, row, required, line_number)
        _require_varchar_limits(
            role,
            row,
            (
                "chunk_id",
                "source_id",
                "source_name",
                "source_type",
                "chunk_type",
                "article_no",
                "appendix_no",
                "form_no",
            ),
            line_number,
            optional={"article_no", "appendix_no", "form_no"},
        )
        if row["source_type"] not in LEGAL_SOURCE_TYPES:
            raise RagSeedValidationError(
                f"{role} row {line_number} source_type must be one of: "
                + ", ".join(LEGAL_SOURCE_TYPES)
            )
        _validate_legal_source_url(row["source_url"], role=role, line_number=line_number)
        if row.get("is_searchable", True) is not True:
            raise RagSeedValidationError(
                f"{role} row {line_number} is_searchable must be true"
            )
        domain_tags = row.get("domain_tags", [])
        if not isinstance(domain_tags, list) or any(
            not isinstance(tag, str) or not tag.strip() or tag != tag.strip()
            for tag in domain_tags
        ):
            raise RagSeedValidationError(
                f"{role} row {line_number} domain_tags must be a list of non-empty strings"
            )
        enforce_date = _strict_iso_date(
            row["enforce_date"],
            role=role,
            field="enforce_date",
            line_number=line_number,
        )
        expire_value = row.get("expire_date")
        if expire_value not in (None, ""):
            expire_date = _strict_iso_date(
                expire_value,
                role=role,
                field="expire_date",
                line_number=line_number,
            )
            if expire_date < enforce_date:
                raise RagSeedValidationError(
                    f"{role} row {line_number} expire_date must not precede enforce_date"
                )
    elif role == "legal_embeddings":
        _require_strings(
            role,
            row,
            ("chunk_id", "embedding_provider", "embedding_model"),
            line_number,
        )
        _require_varchar_limits(
            role,
            row,
            ("chunk_id", "embedding_provider", "embedding_model"),
            line_number,
        )
        if row["embedding_provider"] != row["embedding_provider"].strip().lower():
            raise RagSeedValidationError(
                f"{role} row {line_number} embedding_provider must be canonical lowercase"
            )
        if row["embedding_provider"] not in SUPPORTED_PRODUCTION_EMBEDDING_PROVIDERS:
            raise RagSeedValidationError(
                f"{role} row {line_number} embedding_provider must be a supported "
                "production provider: sentence-transformers or openai"
            )
        if row["embedding_model"] != row["embedding_model"].strip():
            raise RagSeedValidationError(
                f"{role} row {line_number} embedding_model must not have surrounding whitespace"
            )
        dimensions = row.get("embedding_dimensions")
        if (
            isinstance(dimensions, bool)
            or not isinstance(dimensions, int)
            or dimensions != LEGAL_EMBEDDING_DIMENSIONS
        ):
            raise RagSeedValidationError(
                f"{role} row {line_number} embedding_dimensions must be exactly "
                f"{LEGAL_EMBEDDING_DIMENSIONS}"
            )
        vector = row.get("embedding_vector")
        if not isinstance(vector, list) or len(vector) != dimensions:
            raise RagSeedValidationError(
                f"{role} row {line_number} embedding_vector must have exactly "
                f"{dimensions} dimensions"
            )
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in vector
        ):
            raise RagSeedValidationError(f"{role} row {line_number} embedding_vector must be finite numbers")
        try:
            numeric_vector = [float(value) for value in vector]
        except (OverflowError, TypeError, ValueError):
            raise RagSeedValidationError(
                f"{role} row {line_number} embedding_vector must be finite numbers"
            ) from None
        if any(not math.isfinite(value) for value in numeric_vector):
            raise RagSeedValidationError(
                f"{role} row {line_number} embedding_vector must be finite numbers"
            )
        float32_vector: list[float] = []
        try:
            for value in numeric_vector:
                converted = struct.unpack("!f", struct.pack("!f", value))[0]
                if not math.isfinite(converted):
                    raise OverflowError
                float32_vector.append(converted)
        except (OverflowError, struct.error):
            raise RagSeedValidationError(
                f"{role} row {line_number} embedding_vector must contain finite numbers "
                "representable as float32"
            ) from None
        if not any(value != 0.0 for value in float32_vector):
            raise RagSeedValidationError(
                f"{role} row {line_number} embedding_vector must have a non-zero norm "
                "after float32 conversion"
            )
    elif role == "review_case_chunks":
        _require_strings(role, row, ("review_case_id", "chunk_id", "chunk_text"), line_number)
        _require_text_ml_chunk_length(role, row, line_number)
    elif role == "precedent_fault_ratio_chunks":
        _require_strings(
            role,
            row,
            ("case_id", "chunk_id", "chunk_type", "chunk_strategy", "chunk_text"),
            line_number,
        )
        chunk_index = row.get("chunk_index")
        if isinstance(chunk_index, bool) or not isinstance(chunk_index, int) or chunk_index < 0:
            raise RagSeedValidationError(f"{role} row {line_number} chunk_index must be a non-negative integer")
        _require_text_ml_chunk_length(role, row, line_number)
    else:  # Protected by exact-role validation; keep the loader fail-closed.
        raise RagSeedValidationError("unknown RAG seed role")
    return str(row["chunk_id"])


def _require_text_ml_chunk_length(role: str, row: dict[str, Any], line_number: int) -> None:
    if len(str(row["chunk_text"]).strip()) < TEXT_ML_MIN_CHUNK_TEXT_LENGTH:
        raise RagSeedValidationError(
            f"{role} row {line_number} chunk_text must contain at least "
            f"{TEXT_ML_MIN_CHUNK_TEXT_LENGTH} characters"
        )


def _require_strings(
    role: str,
    row: dict[str, Any],
    fields: tuple[str, ...],
    line_number: int,
) -> None:
    for field in fields:
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            raise RagSeedValidationError(f"{role} row {line_number} requires non-empty {field}")


def _require_varchar_limits(
    role: str,
    row: Mapping[str, Any],
    fields: tuple[str, ...],
    line_number: int,
    *,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    for field in fields:
        value = row.get(field)
        if field in optional and value in (None, ""):
            continue
        if not isinstance(value, str) or not value.strip():
            raise RagSeedValidationError(
                f"{role} row {line_number} {field} must be a non-empty string"
            )
        limit = LEGAL_VARCHAR_LIMITS[field]
        if len(value) > limit:
            raise RagSeedValidationError(
                f"{role} row {line_number} {field} must contain at most {limit} characters"
            )


def _validate_legal_source_url(value: str, *, role: str, line_number: int) -> None:
    error = (
        f"{role} row {line_number} source_url must be an absolute HTTPS URL "
        "with a non-placeholder host"
    )
    if value != value.strip() or any(character.isspace() for character in value):
        raise RagSeedValidationError(error)
    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").lower()
        query_keys = {
            "".join(character for character in key.lower() if character.isalnum())
            for key, _item in parse_qsl(parsed.query, keep_blank_values=True)
        }
    except ValueError:
        raise RagSeedValidationError(error) from None
    if parsed.scheme.lower() != "https" or not parsed.netloc or not hostname:
        raise RagSeedValidationError(error)
    if (
        parsed.username is not None
        or parsed.password is not None
        or bool(query_keys & _CREDENTIAL_QUERY_KEYS)
    ):
        raise RagSeedValidationError(error)

    placeholder_host = (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname == "offline"
        or hostname.startswith("offline.")
        or hostname.endswith(".offline")
        or hostname == "example"
        or hostname.startswith("example.")
        or hostname.endswith(".example")
        or hostname.endswith((".example.com", ".example.net", ".example.org"))
        or hostname.endswith(".test")
        or hostname.endswith(".invalid")
    )
    try:
        is_loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        is_loopback = False
    if placeholder_host or is_loopback:
        raise RagSeedValidationError(error)


def _validate_elasticsearch_index_name(value: str, *, setting: str) -> str:
    error = f"Elasticsearch index setting {setting} is invalid"
    if value != value.strip() or any(character.isspace() for character in value):
        raise RagSeedValidationError(error)
    if value in {".", ".."} or value.startswith(("-", "_", "+")):
        raise RagSeedValidationError(error)
    if value != value.lower():
        raise RagSeedValidationError(error)
    if any(character in _ELASTICSEARCH_FORBIDDEN_INDEX_CHARACTERS for character in value):
        raise RagSeedValidationError(error)
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise RagSeedValidationError(error) from None
    if len(encoded) > 255:
        raise RagSeedValidationError(error)
    return value


def _validate_legal_id_alignment(row_ids_by_role: Mapping[str, set[str]]) -> None:
    chunks = row_ids_by_role.get("legal_chunks", set())
    embeddings = row_ids_by_role.get("legal_embeddings", set())
    if chunks != embeddings:
        raise RagSeedValidationError("legal_chunks and legal_embeddings chunk_id sets must match exactly")


def _strict_iso_date(
    value: Any,
    *,
    role: str,
    field: str,
    line_number: int,
) -> date:
    if not isinstance(value, str) or not _ISO_DATE_PATTERN.fullmatch(value):
        raise RagSeedValidationError(
            f"{role} row {line_number} {field} must use strict YYYY-MM-DD format"
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RagSeedValidationError(
            f"{role} row {line_number} {field} must be a valid date"
        ) from exc


def _embedding_space_from_row(row: Mapping[str, Any]) -> tuple[str, str, int]:
    return (
        str(row["embedding_provider"]).strip(),
        str(row["embedding_model"]).strip(),
        int(row["embedding_dimensions"]),
    )


def _embedding_space_payload(space: tuple[str, str, int]) -> dict[str, Any]:
    provider, model, dimensions = space
    return {
        "provider": provider,
        "model": model,
        "dimensions": dimensions,
    }


def _manifest_embedding_space(value: Any) -> tuple[str, str, int]:
    if not isinstance(value, dict) or set(value) != {"provider", "model", "dimensions"}:
        raise RagSeedValidationError(
            "embedding_space must contain provider, model, and dimensions"
        )
    provider = value.get("provider")
    model = value.get("model")
    dimensions = value.get("dimensions")
    if not isinstance(provider, str) or not provider.strip():
        raise RagSeedValidationError("embedding_space provider must be non-empty")
    if not isinstance(model, str) or not model.strip():
        raise RagSeedValidationError("embedding_space model must be non-empty")
    if (
        isinstance(dimensions, bool)
        or not isinstance(dimensions, int)
        or dimensions != LEGAL_EMBEDDING_DIMENSIONS
    ):
        raise RagSeedValidationError(
            f"embedding_space dimensions must be exactly {LEGAL_EMBEDDING_DIMENSIONS}"
        )
    return provider.strip(), model.strip(), dimensions
