"""Plan safe reuse of verified legal embeddings for a freshly collected dataset."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from app.services.rag_seed_bundle import RagSeedBundle


REUSE_PLAN_CONTRACT_VERSION = "legal_embedding_reuse_plan.v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class LegalEmbeddingReuseError(ValueError):
    """Raised when embedding reuse inputs are incomplete or ambiguous."""


@dataclass(frozen=True)
class EmbeddingReusePlan:
    plan_sha256: str
    dataset_version: str
    existing_manifest_sha256: str
    reused_count: int
    changed_count: int
    new_count: int
    removed_count: int
    pending_count: int
    reused_embeddings_path: Path | None
    pending_inputs_path: Path
    report_path: Path
    audit_path: Path


def build_embedding_reuse_plan(
    *,
    bundle: RagSeedBundle,
    fresh_inputs_path: Path,
    output_dir: Path,
    dataset_version: str,
    materialize_reused_embeddings: bool = True,
) -> EmbeddingReusePlan:
    """Classify fresh embedding inputs and copy only exactly matching vectors."""

    normalized_dataset_version = str(dataset_version or "").strip()
    if not normalized_dataset_version or len(normalized_dataset_version) > 128:
        raise LegalEmbeddingReuseError("dataset_version is invalid")

    fresh_path = Path(fresh_inputs_path).resolve()
    if not fresh_path.is_file():
        raise LegalEmbeddingReuseError("fresh embedding inputs were not found")
    legal_embeddings = bundle.artifacts.get("legal_embeddings")
    if legal_embeddings is None:
        raise LegalEmbeddingReuseError("verified bundle has no legal embeddings")

    embedding_space = _embedding_space(bundle.embedding_space)
    fresh_hashes = _read_identity_map(fresh_path, label="fresh embedding inputs")
    if not fresh_hashes:
        raise LegalEmbeddingReuseError("fresh embedding inputs must not be empty")

    target_dir = Path(output_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    reused_target = (
        target_dir / "reused_embeddings.jsonl"
        if materialize_reused_embeddings
        else None
    )
    targets = {
        "pending": target_dir / "pending_embedding_inputs.jsonl",
        "report": target_dir / "embedding_reuse_plan.json",
        "audit": target_dir / "embedding_reuse_audit.csv",
    }
    if reused_target is not None:
        targets["reused"] = reused_target
    for target in targets.values():
        if target.exists():
            raise LegalEmbeddingReuseError(
                f"reuse plan output already exists: {target.name}"
            )
    temporary = {
        name: path.with_name(f".{path.name}.{os.getpid()}.tmp")
        for name, path in targets.items()
    }

    existing_hashes: dict[str, str] = {}
    reused_ids: set[str] = set()
    try:
        reused = (
            temporary["reused"].open("w", encoding="utf-8", newline="\n")
            if materialize_reused_embeddings
            else None
        )
        try:
            source = legal_embeddings.path.open("r", encoding="utf-8-sig")
        except Exception:
            if reused is not None:
                reused.close()
            raise
        try:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                row = _json_object(line, label="existing legal embeddings", line_number=line_number)
                chunk_id, text_hash = _identity(row, label="existing legal embeddings", line_number=line_number)
                if chunk_id in existing_hashes:
                    raise LegalEmbeddingReuseError(
                        f"existing legal embeddings contain duplicate chunk_id at row {line_number}"
                    )
                existing_hashes[chunk_id] = text_hash
                if fresh_hashes.get(chunk_id) == text_hash:
                    if reused is not None:
                        reused.write(line.rstrip("\r\n") + "\n")
                    reused_ids.add(chunk_id)
        finally:
            source.close()
            if reused is not None:
                reused.close()

        existing_ids = set(existing_hashes)
        fresh_ids = set(fresh_hashes)
        changed_ids = {
            chunk_id
            for chunk_id in fresh_ids & existing_ids
            if fresh_hashes[chunk_id] != existing_hashes[chunk_id]
        }
        new_ids = fresh_ids - existing_ids
        removed_ids = existing_ids - fresh_ids
        pending_ids = changed_ids | new_ids

        with (
            fresh_path.open("r", encoding="utf-8-sig") as source,
            temporary["pending"].open("w", encoding="utf-8", newline="\n") as pending,
        ):
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                row = _json_object(line, label="fresh embedding inputs", line_number=line_number)
                chunk_id, _ = _identity(row, label="fresh embedding inputs", line_number=line_number)
                if chunk_id in pending_ids:
                    pending.write(line.rstrip("\r\n") + "\n")

        existing_manifest_sha256 = _sha256_file(bundle.manifest_path)
        plan_sha256 = _plan_sha256(
            dataset_version=normalized_dataset_version,
            existing_manifest_sha256=existing_manifest_sha256,
            embedding_space=embedding_space,
            pending_identities=[
                f"{chunk_id}:{fresh_hashes[chunk_id]}"
                for chunk_id in sorted(pending_ids)
            ],
        )
        plan = EmbeddingReusePlan(
            plan_sha256=plan_sha256,
            dataset_version=normalized_dataset_version,
            existing_manifest_sha256=existing_manifest_sha256,
            reused_count=len(reused_ids),
            changed_count=len(changed_ids),
            new_count=len(new_ids),
            removed_count=len(removed_ids),
            pending_count=len(pending_ids),
            reused_embeddings_path=reused_target,
            pending_inputs_path=targets["pending"],
            report_path=targets["report"],
            audit_path=targets["audit"],
        )
        _write_report(temporary["report"], plan, embedding_space=embedding_space)
        _write_audit(
            temporary["audit"],
            fresh_hashes=fresh_hashes,
            existing_hashes=existing_hashes,
            classifications={
                "changed": changed_ids,
                "new": new_ids,
                "removed": removed_ids,
                "reused": reused_ids,
            },
        )
        for name in ("reused", "pending", "report", "audit"):
            if name not in targets:
                continue
            temporary[name].replace(targets[name])
        return plan
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)


def _read_identity_map(path: Path, *, label: str) -> dict[str, str]:
    identities: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = _json_object(line, label=label, line_number=line_number)
            chunk_id, text_hash = _identity(row, label=label, line_number=line_number)
            if chunk_id in identities:
                raise LegalEmbeddingReuseError(
                    f"{label} contain duplicate chunk_id at row {line_number}"
                )
            identities[chunk_id] = text_hash
    return identities


def _json_object(line: str, *, label: str, line_number: int) -> dict[str, Any]:
    try:
        row = json.loads(line)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LegalEmbeddingReuseError(
            f"{label} contain invalid JSON at row {line_number}"
        ) from exc
    if not isinstance(row, dict):
        raise LegalEmbeddingReuseError(
            f"{label} row {line_number} must be an object"
        )
    return row


def _identity(
    row: dict[str, Any], *, label: str, line_number: int
) -> tuple[str, str]:
    chunk_id = str(row.get("chunk_id") or "").strip()
    text_hash = str(row.get("embedding_text_hash") or "").strip()
    if not chunk_id:
        raise LegalEmbeddingReuseError(
            f"{label} row {line_number} has no chunk_id"
        )
    if not _SHA256_PATTERN.fullmatch(text_hash):
        raise LegalEmbeddingReuseError(
            f"{label} row {line_number} has invalid embedding_text_hash"
        )
    return chunk_id, text_hash


def _embedding_space(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LegalEmbeddingReuseError("verified bundle embedding space is invalid")
    provider = value.get("provider")
    model = value.get("model")
    dimensions = value.get("dimensions")
    if (provider, model, dimensions) != (
        "openai",
        "text-embedding-3-large",
        1024,
    ):
        raise LegalEmbeddingReuseError(
            "verified bundle must use openai/text-embedding-3-large/1024"
        )
    return {
        "provider": provider,
        "model": model,
        "dimensions": dimensions,
    }


def _plan_sha256(
    *,
    dataset_version: str,
    existing_manifest_sha256: str,
    embedding_space: dict[str, Any],
    pending_identities: list[str],
) -> str:
    lines = [
        f"dataset_version={dataset_version}",
        f"existing_manifest_sha256={existing_manifest_sha256}",
        f"provider={embedding_space['provider']}",
        f"model={embedding_space['model']}",
        f"dimensions={embedding_space['dimensions']}",
        *pending_identities,
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _write_report(
    path: Path,
    plan: EmbeddingReusePlan,
    *,
    embedding_space: dict[str, Any],
) -> None:
    payload = {
        "contract_version": REUSE_PLAN_CONTRACT_VERSION,
        "status": "planned",
        "plan_sha256": plan.plan_sha256,
        "dataset_version": plan.dataset_version,
        "existing_manifest_sha256": plan.existing_manifest_sha256,
        "embedding_space": embedding_space,
        "counts": {
            "reused": plan.reused_count,
            "changed": plan.changed_count,
            "new": plan.new_count,
            "removed": plan.removed_count,
            "pending": plan.pending_count,
        },
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_audit(
    path: Path,
    *,
    fresh_hashes: dict[str, str],
    existing_hashes: dict[str, str],
    classifications: dict[str, set[str]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "chunk_id",
                "classification",
                "existing_text_hash",
                "fresh_text_hash",
            ),
        )
        writer.writeheader()
        for classification in ("changed", "new", "removed", "reused"):
            for chunk_id in sorted(classifications[classification]):
                writer.writerow(
                    {
                        "chunk_id": chunk_id,
                        "classification": classification,
                        "existing_text_hash": existing_hashes.get(chunk_id, ""),
                        "fresh_text_hash": fresh_hashes.get(chunk_id, ""),
                    }
                )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
