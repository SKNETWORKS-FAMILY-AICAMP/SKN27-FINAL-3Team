"""Collect current legal sources and build an approval-bound reusable RAG seed."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from app.services.approved_legal_seed_builder import (
    ApprovedLegalSeedBuildError,
    PaidEmbeddingApprovalRequired,
    build_approved_legal_seed,
)
from app.services.rag_seed_bundle import (
    RagSeedValidationError,
    load_and_validate_rag_seed_manifest,
)
from etl.legal.ingestion.collector import load_manifest, validate_manifest
from etl.legal.ingestion.run import PipelineConfig, run_pipeline


BUILD_RESULT_CONTRACT_VERSION = "approved_legal_rag_seed_build.v1"


class Command(BaseCommand):
    help = "Collect current laws and safely reuse verified production embeddings."

    def add_arguments(self, parser):
        parser.add_argument("--source-config", required=True)
        parser.add_argument("--existing-manifest", required=True)
        parser.add_argument("--output-root", required=True)
        parser.add_argument("--dataset-version")
        parser.add_argument("--approved-plan-sha256")
        parser.add_argument("--max-age-hours", required=True, type=int)
        parser.add_argument(
            "--client",
            choices=("offline", "law_go_kr"),
            default="law_go_kr",
        )
        parser.add_argument("--base-date", default=date.today().isoformat())
        parser.add_argument("--history-years", type=int, default=3)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--allow-paid-embedding", action="store_true")
        parser.add_argument("--format", choices=("json", "text"), default="json")

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        allow_paid = bool(options["allow_paid_embedding"])
        expected_dataset_version = options.get("dataset_version")
        approved_plan_sha256 = options.get("approved_plan_sha256")
        if dry_run and allow_paid:
            raise CommandError("dry-run cannot allow paid embedding")
        if not dry_run and not expected_dataset_version:
            raise CommandError("--dataset-version is required outside dry-run")
        if allow_paid and not approved_plan_sha256:
            raise CommandError(
                "--approved-plan-sha256 is required with --allow-paid-embedding"
            )

        try:
            base_date = date.fromisoformat(str(options["base_date"]))
        except ValueError:
            raise CommandError("--base-date must be an ISO date") from None
        source_config = Path(options["source_config"]).resolve()
        existing_manifest = Path(options["existing_manifest"]).resolve()
        output_root = Path(options["output_root"]).resolve()
        ingestion_root = output_root.with_name(f"{output_root.name}.ingestion")

        try:
            required_sources = [
                str(row["source_id"])
                for row in validate_manifest(load_manifest(source_config))
            ]
            if not required_sources:
                raise ApprovedLegalSeedBuildError(
                    "source config has no enabled legal sources"
                )
            _run_legal_ingestion(
                source_config=source_config,
                output_root=ingestion_root,
                base_date=base_date,
                history_years=int(options["history_years"]),
                client=str(options["client"]),
            )
            existing_bundle = load_and_validate_rag_seed_manifest(existing_manifest)
            embedding_generator = None
            if allow_paid and not dry_run:
                from etl.legal.embedding.run_openai import generate_embeddings

                embedding_generator = generate_embeddings
            result = build_approved_legal_seed(
                existing_bundle=existing_bundle,
                ingestion_output_root=ingestion_root,
                output_root=output_root,
                expected_dataset_version=expected_dataset_version,
                max_age_hours=int(options["max_age_hours"]),
                required_sources=required_sources,
                now=datetime.now(timezone.utc),
                dry_run=dry_run,
                allow_paid_embedding=allow_paid,
                approved_plan_sha256=approved_plan_sha256,
                embedding_generator=embedding_generator,
            )
        except PaidEmbeddingApprovalRequired as exc:
            self.stdout.write(
                _render_result(_approval_required_payload(exc.plan), options["format"])
            )
            raise CommandError(
                "paid embedding approval is required for the reported plan_sha256"
            ) from None
        except (ApprovedLegalSeedBuildError, RagSeedValidationError) as exc:
            raise CommandError(str(exc)) from None
        except (OSError, ValueError):
            raise CommandError("approved legal seed build input is invalid") from None

        self.stdout.write(_render_result(_result_payload(result), options["format"]))


def _run_legal_ingestion(
    *,
    source_config: Path,
    output_root: Path,
    base_date: date,
    history_years: int,
    client: str,
) -> Path:
    if output_root.exists() and any(output_root.iterdir()):
        raise ApprovedLegalSeedBuildError("ingestion output root must be empty")
    config = PipelineConfig(
        manifest=source_config,
        base_date=base_date,
        history_years=history_years,
        mode="artifact",
        output_dir=output_root,
        client=client,
    )
    config.validate()
    summary = run_pipeline(config)
    if summary.get("status") != "success":
        raise ApprovedLegalSeedBuildError("legal source ingestion did not succeed")
    return output_root


def _result_payload(result) -> dict[str, object]:
    plan = result.reuse_plan
    return {
        "contract_version": BUILD_RESULT_CONTRACT_VERSION,
        "status": result.status,
        "dataset_version": result.dataset_version,
        "verified_at": result.verified_at,
        "plan_sha256": plan.plan_sha256,
        "manifest_sha256": result.manifest_sha256,
        "manifest": str(result.manifest_path) if result.manifest_path else None,
        "counts": _plan_counts(plan),
    }


def _approval_required_payload(plan) -> dict[str, object]:
    return {
        "contract_version": BUILD_RESULT_CONTRACT_VERSION,
        "status": "approval_required",
        "dataset_version": plan.dataset_version,
        "plan_sha256": plan.plan_sha256,
        "manifest_sha256": None,
        "manifest": None,
        "counts": _plan_counts(plan),
    }


def _plan_counts(plan) -> dict[str, int]:
    return {
        "reused": int(plan.reused_count),
        "changed": int(plan.changed_count),
        "new": int(plan.new_count),
        "removed": int(plan.removed_count),
        "pending": int(plan.pending_count),
    }


def _render_result(payload: dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    counts = payload["counts"]
    return "\n".join(
        (
            f"Approved legal RAG seed: {payload['status']}",
            f"- dataset_version: {payload['dataset_version']}",
            f"- plan_sha256: {payload['plan_sha256']}",
            f"- reused: {counts['reused']}",
            f"- changed: {counts['changed']}",
            f"- new: {counts['new']}",
            f"- removed: {counts['removed']}",
            f"- pending: {counts['pending']}",
        )
    )
