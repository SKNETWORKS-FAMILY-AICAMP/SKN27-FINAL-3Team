"""Versioned, provider-free NEW++ seed staging and pointer management."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, ContextManager

from ..config import (
    EXPECTED_RAG_BLOCKS,
    EXPECTED_RAG_CASES,
    QWEN_DIMENSION,
    QWEN_MODEL_ID,
    QWEN_REVISION,
)
from ..precedent_embedding.build_bootstrap import (
    SOURCE_METADATA_SHA256,
    SOURCE_NPY_SHA256,
)
from .loader import iter_versioned_record_params, load_bootstrap_pair


CONTRACT_VERSION = "precedent_newplusplus_seed.v1"
ADVISORY_LOCK_KEY = 0x505245434544454E
ConnectionFactory = Callable[[], ContextManager[Any]]


class SeedIntegrityError(RuntimeError):
    """Credential-safe domain failure for seed lifecycle operations."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SeedIdentity:
    seed_version: str
    source_npy_sha256: str
    source_metadata_sha256: str
    model_id: str
    model_revision: str
    block_count: int
    case_count: int
    embedding_dimension: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _identity_payload(
    *,
    source_npy_sha256: str,
    source_metadata_sha256: str,
    model_id: str,
    model_revision: str,
    block_count: int,
    case_count: int,
    embedding_dimension: int,
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "source_npy_sha256": source_npy_sha256,
        "source_metadata_sha256": source_metadata_sha256,
        "model_id": model_id,
        "model_revision": model_revision,
        "block_count": block_count,
        "case_count": case_count,
        "embedding_dimension": embedding_dimension,
    }


def _seed_version(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def compute_seed_identity() -> SeedIdentity:
    payload = _identity_payload(
        source_npy_sha256=SOURCE_NPY_SHA256,
        source_metadata_sha256=SOURCE_METADATA_SHA256,
        model_id=QWEN_MODEL_ID,
        model_revision=QWEN_REVISION,
        block_count=EXPECTED_RAG_BLOCKS,
        case_count=EXPECTED_RAG_CASES,
        embedding_dimension=QWEN_DIMENSION,
    )
    return SeedIdentity(seed_version=_seed_version(payload), **payload_without_contract(payload))


def payload_without_contract(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "contract_version"}


def stage_seed(
    *,
    embeddings_path: Path,
    metadata_path: Path,
    connection_factory: ConnectionFactory,
) -> dict[str, Any]:
    records, embeddings = load_bootstrap_pair(embeddings_path, metadata_path)
    identity = compute_seed_identity()

    with connection_factory() as connection, connection.cursor() as cursor:
        _acquire_lock(cursor)
        existing = _read_verified_seed(cursor, identity.seed_version)
        if existing is not None:
            return _stage_result(identity.seed_version, "reused", existing)

        cursor.execute(
            """
            INSERT INTO precedent_newplusplus.seed_releases (
              seed_version, source_npy_sha256, source_metadata_sha256,
              model_id, model_revision, block_count, case_count,
              embedding_dimension, status, verified_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'staged',CURRENT_TIMESTAMP)
            """,
            (
                identity.seed_version,
                identity.source_npy_sha256,
                identity.source_metadata_sha256,
                identity.model_id,
                identity.model_revision,
                identity.block_count,
                identity.case_count,
                identity.embedding_dimension,
            ),
        )
        insert_statement = """
            INSERT INTO precedent_newplusplus.block_versions (
              seed_version, block_id, record_id, block_type, semantic_role,
              block_text, case_number, case_name, court_name, decision_date,
              internal_grade, source_metadata, embedding
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::vector)
        """
        for params in iter_versioned_record_params(
            records,
            embeddings,
            seed_version=identity.seed_version,
        ):
            cursor.execute(insert_statement, params)

        verified = _read_verified_seed(cursor, identity.seed_version)
        if verified is None:
            raise SeedIntegrityError(
                "SEED_EXACT_VERIFICATION_FAILED",
                "precedent exact seed verification failed",
            )
        return _stage_result(identity.seed_version, "staged", verified)


def verify_seed(
    *,
    expected_seed_version: str,
    connection_factory: ConnectionFactory,
) -> dict[str, Any]:
    with connection_factory() as connection, connection.cursor() as cursor:
        verified = _read_active_verified_seed(cursor, expected_seed_version)
    if verified is None:
        raise SeedIntegrityError(
            "SEED_NOT_FOUND",
            "expected precedent seed is unavailable",
        )
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "verified",
        "seed_version": expected_seed_version,
        "release_status": verified["release_status"],
        "block_count": verified["block_count"],
        "case_count": verified["case_count"],
        "embedding_dimension": verified["embedding_dimension"],
    }


def promote_seed(
    *,
    seed_version: str,
    expected_active_seed_version: str | None,
    connection_factory: ConnectionFactory,
) -> dict[str, Any]:
    with connection_factory() as connection, connection.cursor() as cursor:
        _acquire_lock(cursor)
        actual_active, _actual_previous = _read_pointer_for_update(cursor)
        if actual_active != expected_active_seed_version:
            raise SeedIntegrityError(
                "ACTIVE_SEED_CHANGED",
                "active seed changed before promotion",
            )

        target = _read_verified_seed(cursor, seed_version)
        if target is None:
            raise SeedIntegrityError("SEED_NOT_FOUND", "promotion seed is unavailable")
        if actual_active == seed_version:
            return _pointer_result("reused", seed_version, _actual_previous)
        if target["release_status"] != "staged":
            raise SeedIntegrityError(
                "SEED_NOT_STAGED",
                "promotion seed is not staged",
            )

        if actual_active is not None:
            cursor.execute(
                """
                UPDATE precedent_newplusplus.seed_releases
                   SET status = 'previous'
                 WHERE seed_version = %s
                """,
                (actual_active,),
            )
        cursor.execute(
            """
            UPDATE precedent_newplusplus.seed_releases
               SET status = 'active'
             WHERE seed_version = %s
            """,
            (seed_version,),
        )
        cursor.execute(
            """
            INSERT INTO precedent_newplusplus.active_seed (
              singleton, active_seed_version, previous_seed_version, updated_at
            ) VALUES (TRUE,%s,%s,CURRENT_TIMESTAMP)
            ON CONFLICT (singleton) DO UPDATE SET
              active_seed_version = EXCLUDED.active_seed_version,
              previous_seed_version = EXCLUDED.previous_seed_version,
              updated_at = EXCLUDED.updated_at
            """,
            (seed_version, actual_active),
        )
        return _pointer_result("promoted", seed_version, actual_active)


def rollback_seed(
    *,
    expected_active_seed_version: str,
    connection_factory: ConnectionFactory,
) -> dict[str, Any]:
    with connection_factory() as connection, connection.cursor() as cursor:
        _acquire_lock(cursor)
        actual_active, previous = _read_pointer_for_update(cursor)
        if actual_active != expected_active_seed_version:
            raise SeedIntegrityError(
                "ACTIVE_SEED_CHANGED",
                "active seed changed before rollback",
            )
        if previous is None:
            raise SeedIntegrityError(
                "PREVIOUS_SEED_UNAVAILABLE",
                "previous seed is unavailable",
            )
        target = _read_verified_seed(cursor, previous)
        if target is None:
            raise SeedIntegrityError(
                "PREVIOUS_SEED_UNAVAILABLE",
                "previous seed is unavailable",
            )

        cursor.execute(
            """
            UPDATE precedent_newplusplus.seed_releases
               SET status = 'previous'
             WHERE seed_version = %s
            """,
            (actual_active,),
        )
        cursor.execute(
            """
            UPDATE precedent_newplusplus.seed_releases
               SET status = 'active'
             WHERE seed_version = %s
            """,
            (previous,),
        )
        cursor.execute(
            """
            UPDATE precedent_newplusplus.active_seed
               SET active_seed_version = %s,
                   previous_seed_version = %s,
                   updated_at = CURRENT_TIMESTAMP
             WHERE singleton IS TRUE
            """,
            (previous, actual_active),
        )
        return _pointer_result("rolled_back", previous, actual_active)


def _acquire_lock(cursor: Any) -> None:
    cursor.execute("SELECT pg_advisory_xact_lock(%s);", (ADVISORY_LOCK_KEY,))


def _read_pointer_for_update(cursor: Any) -> tuple[str | None, str | None]:
    cursor.execute(
        """
        SELECT active_seed_version, previous_seed_version
          FROM precedent_newplusplus.active_seed
         WHERE singleton IS TRUE
         FOR UPDATE
        """
    )
    row = cursor.fetchone()
    if row is None:
        return None, None
    return str(row[0]), str(row[1]) if row[1] is not None else None


def _read_verified_seed(cursor: Any, seed_version: str) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT release.status,
               release.source_npy_sha256,
               release.source_metadata_sha256,
               release.model_id,
               release.model_revision,
               release.block_count,
               release.case_count,
               release.embedding_dimension,
               count(blocks.block_id)::int,
               count(DISTINCT blocks.record_id)::int,
               min(vector_dims(blocks.embedding))::int,
               max(vector_dims(blocks.embedding))::int,
               count(*) FILTER (
                 WHERE blocks.internal_grade NOT IN (
                   'GENERAL_READY_DIRECT', 'SEED_READY'
                 )
               )::int
          FROM precedent_newplusplus.seed_releases AS release
          LEFT JOIN precedent_newplusplus.block_versions AS blocks
            ON blocks.seed_version = release.seed_version
         WHERE release.seed_version = %s
         GROUP BY release.seed_version, release.status,
                  release.source_npy_sha256, release.source_metadata_sha256,
                  release.model_id, release.model_revision,
                  release.block_count, release.case_count,
                  release.embedding_dimension
        """,
        (seed_version,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return _verified_seed_from_row(row, seed_version)


def _read_active_verified_seed(
    cursor: Any,
    seed_version: str,
) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT release.status,
               release.source_npy_sha256,
               release.source_metadata_sha256,
               release.model_id,
               release.model_revision,
               release.block_count,
               release.case_count,
               release.embedding_dimension,
               count(blocks.block_id)::int,
               count(DISTINCT blocks.record_id)::int,
               min(vector_dims(blocks.embedding))::int,
               max(vector_dims(blocks.embedding))::int,
               count(*) FILTER (
                 WHERE blocks.internal_grade NOT IN (
                   'GENERAL_READY_DIRECT', 'SEED_READY'
                 )
               )::int
          FROM precedent_newplusplus.seed_releases AS release
          JOIN precedent_newplusplus.active_seed AS active
            ON active.singleton IS TRUE
           AND active.active_seed_version = release.seed_version
          LEFT JOIN precedent_newplusplus.blocks AS blocks ON TRUE
         WHERE release.seed_version = %s
         GROUP BY release.seed_version, release.status,
                  release.source_npy_sha256, release.source_metadata_sha256,
                  release.model_id, release.model_revision,
                  release.block_count, release.case_count,
                  release.embedding_dimension
        """,
        (seed_version,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    verified = _verified_seed_from_row(row, seed_version)
    if verified["release_status"] != "active":
        raise SeedIntegrityError(
            "SEED_EXACT_VERIFICATION_FAILED",
            "precedent exact seed verification failed",
        )
    return verified


def _verified_seed_from_row(
    row: Any,
    seed_version: str,
) -> dict[str, Any]:
    (
        release_status,
        source_npy_sha256,
        source_metadata_sha256,
        model_id,
        model_revision,
        declared_blocks,
        declared_cases,
        declared_dimension,
        blocks,
        cases,
        min_dims,
        max_dims,
        invalid_grades,
    ) = row
    payload = _identity_payload(
        source_npy_sha256=str(source_npy_sha256).strip(),
        source_metadata_sha256=str(source_metadata_sha256).strip(),
        model_id=str(model_id),
        model_revision=str(model_revision),
        block_count=int(declared_blocks),
        case_count=int(declared_cases),
        embedding_dimension=int(declared_dimension),
    )
    exact = (
        _seed_version(payload) == seed_version
        and int(declared_blocks) == EXPECTED_RAG_BLOCKS
        and int(declared_cases) == EXPECTED_RAG_CASES
        and int(declared_dimension) == QWEN_DIMENSION
        and int(blocks) == EXPECTED_RAG_BLOCKS
        and int(cases) == EXPECTED_RAG_CASES
        and int(min_dims) == int(max_dims) == QWEN_DIMENSION
        and int(invalid_grades) == 0
    )
    if not exact:
        raise SeedIntegrityError(
            "SEED_EXACT_VERIFICATION_FAILED",
            "precedent exact seed verification failed",
        )
    return {
        "release_status": str(release_status),
        "block_count": int(blocks),
        "case_count": int(cases),
        "embedding_dimension": int(min_dims),
    }


def _stage_result(
    seed_version: str,
    status: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "seed_version": seed_version,
        "release_status": evidence["release_status"],
        "block_count": evidence["block_count"],
        "case_count": evidence["case_count"],
        "embedding_dimension": evidence["embedding_dimension"],
    }


def _pointer_result(
    status: str,
    active_seed_version: str,
    previous_seed_version: str | None,
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "active_seed_version": active_seed_version,
        "previous_seed_version": previous_seed_version,
    }
