"""Build a verified legal RAG seed with explicitly approved incremental embedding."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Callable

from app.services.legal_embedding_reuse import (
    EmbeddingReusePlan,
    build_embedding_reuse_plan,
)
from app.services.rag_seed_bundle import (
    RagSeedBundle,
    RagSeedValidationError,
    build_rag_seed_manifest,
    load_and_validate_rag_seed_manifest,
)
from etl.legal.validate_run_summary import evaluate_run_summary


EmbeddingGenerator = Callable[..., dict]


class ApprovedLegalSeedBuildError(ValueError):
    """Raised when an approved legal seed cannot be built safely."""


class PaidEmbeddingApprovalRequired(ApprovedLegalSeedBuildError):
    """Raised before provider use when the exact pending plan is unapproved."""

    def __init__(self, plan: EmbeddingReusePlan):
        super().__init__(
            "paid embedding approval is required for the current reuse plan"
        )
        self.plan = plan


@dataclass(frozen=True)
class ApprovedLegalSeedBuildResult:
    status: str
    dataset_version: str
    verified_at: str
    reuse_plan: EmbeddingReusePlan
    manifest_path: Path | None
    manifest_sha256: str | None


def build_approved_legal_seed(
    *,
    existing_bundle: RagSeedBundle,
    ingestion_output_root: Path,
    output_root: Path,
    expected_dataset_version: str | None,
    max_age_hours: int,
    required_sources: list[str],
    now: datetime | None = None,
    dry_run: bool,
    allow_paid_embedding: bool,
    approved_plan_sha256: str | None,
    embedding_generator: EmbeddingGenerator | None,
) -> ApprovedLegalSeedBuildResult:
    """Validate fresh ingestion, reuse exact vectors, and build a new v1 bundle."""

    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        raise ApprovedLegalSeedBuildError("now must include timezone information")
    source_root = Path(ingestion_output_root).resolve()
    target_root = Path(output_root).resolve()
    if target_root.exists() and any(target_root.iterdir()):
        raise ApprovedLegalSeedBuildError("output_root must be empty")
    target_root.mkdir(parents=True, exist_ok=True)

    summary_path = source_root / "reports" / "run_summary.json"
    summary = _read_json_object(summary_path, label="legal ingestion run summary")
    dataset_version = str(summary.get("dataset_version") or "").strip()
    if not dataset_version:
        raise ApprovedLegalSeedBuildError(
            "legal ingestion run summary has no dataset_version"
        )
    if not dry_run and not expected_dataset_version:
        raise ApprovedLegalSeedBuildError(
            "expected_dataset_version is required outside dry-run"
        )
    if expected_dataset_version and expected_dataset_version != dataset_version:
        raise ApprovedLegalSeedBuildError("dataset_version mismatch")

    validation = evaluate_run_summary(
        summary,
        now=checked_at,
        max_age_hours=max_age_hours,
        required_sources=required_sources,
        expected_dataset_version=expected_dataset_version,
    )
    if validation["status"] != "success":
        categories = [
            name
            for name in ("errors", "missing_sources", "failed_sources", "stale_sources")
            if validation.get(name)
        ]
        raise ApprovedLegalSeedBuildError(
            "freshness validation failed: " + ",".join(categories)
        )

    fresh_inputs_path = source_root / "embeddings" / "embedding_inputs.jsonl"
    fresh_chunks_path = source_root / "chunks" / "law_chunks.jsonl"
    if not fresh_chunks_path.is_file():
        raise ApprovedLegalSeedBuildError("fresh legal chunks were not found")

    evidence_dir = target_root / "evidence"
    reuse_plan = build_embedding_reuse_plan(
        bundle=existing_bundle,
        fresh_inputs_path=fresh_inputs_path,
        output_dir=evidence_dir / "reuse",
        dataset_version=dataset_version,
        materialize_reused_embeddings=not dry_run,
    )
    _copy_file(summary_path, evidence_dir / "run_summary.json")

    verified_at = _verified_at(summary, required_sources=required_sources)
    if dry_run:
        return ApprovedLegalSeedBuildResult(
            status="planned",
            dataset_version=dataset_version,
            verified_at=verified_at,
            reuse_plan=reuse_plan,
            manifest_path=None,
            manifest_sha256=None,
        )

    generated_path: Path | None = None
    if reuse_plan.pending_count:
        if not allow_paid_embedding:
            raise PaidEmbeddingApprovalRequired(reuse_plan)
        if approved_plan_sha256 != reuse_plan.plan_sha256:
            raise ApprovedLegalSeedBuildError("approved plan sha256 mismatch")
        if embedding_generator is None:
            raise ApprovedLegalSeedBuildError("embedding generator is unavailable")
        generated_path = evidence_dir / "generated_embeddings.jsonl"
        provider_report_path = evidence_dir / "embedding_provider_report.json"
        try:
            embedding_generator(
                input_path=reuse_plan.pending_inputs_path,
                output_path=generated_path,
                report_path=provider_report_path,
                model_id="text-embedding-3-large",
                dimensions=1024,
                batch_size=128,
            )
        except Exception as exc:
            raise ApprovedLegalSeedBuildError(
                "approved embedding provider execution failed"
            ) from exc
        _assert_generated_identities(
            pending_path=reuse_plan.pending_inputs_path,
            generated_path=generated_path,
        )

    data_dir = target_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    final_paths = {
        "legal_chunks": data_dir / "legal_chunks.jsonl",
        "legal_embeddings": data_dir / "legal_embeddings.jsonl",
        "review_case_chunks": data_dir / "review_case_chunks.jsonl",
        "precedent_fault_ratio_chunks": data_dir / "precedent_fault_ratio_chunks.jsonl",
    }
    manifest_path = target_root / "rag-seed-manifest.json"
    try:
        _copy_file(fresh_chunks_path, final_paths["legal_chunks"])
        _assemble_final_embeddings(
            final_paths["legal_embeddings"],
            reused_path=reuse_plan.reused_embeddings_path,
            generated_path=generated_path,
        )
        reuse_plan = replace(
            reuse_plan,
            reused_embeddings_path=final_paths["legal_embeddings"],
        )
        _copy_file(
            existing_bundle.artifacts["review_case_chunks"].path,
            final_paths["review_case_chunks"],
        )
        _copy_file(
            existing_bundle.artifacts["precedent_fault_ratio_chunks"].path,
            final_paths["precedent_fault_ratio_chunks"],
        )
        relative_paths = {
            role: path.relative_to(target_root).as_posix()
            for role, path in final_paths.items()
        }
        build_rag_seed_manifest(
            bundle_root=target_root,
            artifact_paths=relative_paths,
            manifest_path=manifest_path,
        )
        load_and_validate_rag_seed_manifest(manifest_path)
    except (OSError, RagSeedValidationError, ValueError) as exc:
        manifest_path.unlink(missing_ok=True)
        raise ApprovedLegalSeedBuildError(
            "final production RAG seed validation failed"
        ) from exc

    return ApprovedLegalSeedBuildResult(
        status="verified",
        dataset_version=dataset_version,
        verified_at=verified_at,
        reuse_plan=reuse_plan,
        manifest_path=manifest_path,
        manifest_sha256=_sha256_file(manifest_path),
    )


def _read_json_object(path: Path, *, label: str) -> dict:
    if not path.is_file():
        raise ApprovedLegalSeedBuildError(f"{label} was not found")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise ApprovedLegalSeedBuildError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise ApprovedLegalSeedBuildError(f"{label} must be an object")
    return value


def _verified_at(summary: dict, *, required_sources: list[str]) -> str:
    required = {source_id.strip() for source_id in required_sources if source_id.strip()}
    source_rows = summary.get("source_summaries")
    source_rows = source_rows if isinstance(source_rows, list) else []
    timestamps: list[datetime] = []
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        source_id = str(row.get("source_id") or "").strip()
        if required and source_id not in required:
            continue
        value = str(row.get("last_verified_at") or "").strip()
        if value.endswith("Z"):
            value = f"{value[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            timestamps.append(parsed.astimezone(timezone.utc))
    if not timestamps:
        raise ApprovedLegalSeedBuildError(
            "freshness validation has no source verified timestamp"
        )
    return min(timestamps).isoformat()


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _assemble_final_embeddings(
    target: Path,
    *,
    reused_path: Path | None,
    generated_path: Path | None,
) -> None:
    if reused_path is None or not reused_path.is_file():
        raise ApprovedLegalSeedBuildError("reused embeddings were not materialized")
    target.parent.mkdir(parents=True, exist_ok=True)
    if generated_path is not None:
        with (
            reused_path.open("ab") as output,
            generated_path.open("rb") as generated,
        ):
            shutil.copyfileobj(generated, output, length=1024 * 1024)
    reused_path.replace(target)


def _identity_map(path: Path) -> dict[str, str]:
    identities: dict[str, str] = {}
    if not path.is_file():
        raise ApprovedLegalSeedBuildError("generated embeddings were not produced")
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ApprovedLegalSeedBuildError(
                    "generated embeddings contain invalid JSON"
                ) from exc
            if not isinstance(row, dict):
                raise ApprovedLegalSeedBuildError(
                    "generated embeddings must contain objects"
                )
            chunk_id = str(row.get("chunk_id") or "").strip()
            text_hash = str(row.get("embedding_text_hash") or "").strip()
            if not chunk_id or not text_hash or chunk_id in identities:
                raise ApprovedLegalSeedBuildError(
                    f"generated embedding identity is invalid at row {line_number}"
                )
            identities[chunk_id] = text_hash
    return identities


def _assert_generated_identities(*, pending_path: Path, generated_path: Path) -> None:
    if _identity_map(pending_path) != _identity_map(generated_path):
        raise ApprovedLegalSeedBuildError(
            "generated embedding identities do not match the approved pending plan"
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
