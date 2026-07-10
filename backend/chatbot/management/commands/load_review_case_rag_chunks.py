"""Load local review-case chunks into the Django fallback RAG tables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from app.services.legal_rag_service import search_legal_rag
from chatbot.models import RagChunk, SourceDocument


DEFAULT_CHUNKS_PATH = Path(
    "etl/fault_cases/artifacts/review_case_output/preprocessed/review_case_chunks.jsonl"
)
SOURCE_TYPE = "review_case"


class Command(BaseCommand):
    help = "Load local review_case JSONL chunks into source_documents/rag_chunks."

    def add_arguments(self, parser):
        parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS_PATH), help="Path to review_case_chunks.jsonl.")
        parser.add_argument("--replace", action="store_true", help="Delete matching loaded chunks before loading.")
        parser.add_argument("--limit", type=int, default=0, help="Optional max rows to load; 0 loads all rows.")
        parser.add_argument("--smoke-query", default="", help="Optional review_case search query after loading.")
        parser.add_argument("--top-k", type=int, default=3, help="Top K for the optional smoke query.")
        parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    def handle(self, *args, **options):
        chunks_path = Path(options["chunks"])
        if not chunks_path.exists():
            raise CommandError(f"review_case chunks file not found: {chunks_path}")

        limit = max(0, int(options["limit"] or 0))
        rows = list(_read_jsonl(chunks_path, limit=limit))
        if not rows:
            raise CommandError(f"review_case chunks file is empty: {chunks_path}")

        with transaction.atomic():
            if options["replace"]:
                chunk_ids = [_required(row, "chunk_id") for row in rows]
                RagChunk.objects.filter(chunk_id__in=chunk_ids, source_type=SOURCE_TYPE).delete()
            loaded = _load_rows(rows, source_path=chunks_path)

        smoke = None
        if str(options["smoke_query"] or "").strip():
            smoke = search_legal_rag(
                str(options["smoke_query"]),
                top_k=max(1, int(options["top_k"] or 3)),
                source_type=SOURCE_TYPE,
            )

        counts = {
            "source_documents": SourceDocument.objects.filter(source_type=SOURCE_TYPE).count(),
            "rag_chunks": RagChunk.objects.filter(source_type=SOURCE_TYPE).count(),
        }
        result = {
            "contract_version": "review_case_rag_chunks_loader.v1",
            "status": "loaded",
            "chunks": str(chunks_path),
            "loaded": loaded,
            "counts": counts,
            "smoke": smoke,
        }
        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(_text_result(result))


def _load_rows(rows: list[dict[str, Any]], *, source_path: Path) -> dict[str, int]:
    source_ids = set()
    chunk_count = 0
    for row in rows:
        review_case_id = str(row.get("review_case_id") or row.get("source_ref") or row.get("chunk_id") or "")
        if not review_case_id:
            raise CommandError("Missing review_case_id/source_ref/chunk_id for review_case RAG row.")
        source_document_id = review_case_id[:64]
        source_ids.add(source_document_id)
        review_no = str(row.get("review_no") or "")
        source, _source_created = SourceDocument.objects.update_or_create(
            source_document_id=source_document_id,
            defaults={
                "source_type": SOURCE_TYPE,
                "source_name": review_no and f"과실비율 심의사례 {review_no}" or source_document_id,
                "source_url": "",
                "status": "active",
                "metadata": {
                    "source": "review_case_rag_chunks_loader",
                    "source_path": str(source_path),
                    "source_ref": row.get("source_ref"),
                    "review_case_id": review_case_id,
                },
            },
        )
        chunk_text = _required(row, "chunk_text")
        RagChunk.objects.update_or_create(
            chunk_id=_required(row, "chunk_id"),
            defaults={
                "source_document": source,
                "source_id": review_case_id,
                "source_type": SOURCE_TYPE,
                "chunk_type": str(row.get("chunk_type") or "case_chunk"),
                "title": _review_case_title(row),
                "article_no": review_no[:50],
                "section_ref": str(row.get("reference_chart_key") or ""),
                "content": chunk_text,
                "normalized_text": _normalized_text(row),
                "is_searchable": str(row.get("parse_status") or "valid") != "invalid",
                "domain_tags": _domain_tags(row),
                "metadata": {
                    "source": "review_case_rag_chunks_loader",
                    "source_ref": row.get("source_ref"),
                    "review_case_id": review_case_id,
                    "review_no": review_no,
                    "decision_fault_ratio": row.get("decision_fault_ratio"),
                    "reference_chart_key": row.get("reference_chart_key"),
                    "source_reliability_score": row.get("source_reliability_score"),
                    "parse_status": row.get("parse_status"),
                    "quality_flags": row.get("quality_flags") or [],
                },
            },
        )
        chunk_count += 1
    return {"source_documents": len(source_ids), "rag_chunks": chunk_count}


def _review_case_title(row: dict[str, Any]) -> str:
    review_no = str(row.get("review_no") or "")
    chunk_type = str(row.get("chunk_type") or "case_chunk")
    ratio = str(row.get("decision_fault_ratio") or "")
    title = " ".join(item for item in (review_no, chunk_type, ratio) if item)
    return title[:255]


def _normalized_text(row: dict[str, Any]) -> str:
    parts = [
        row.get("chunk_text"),
        row.get("decision_fault_ratio"),
        row.get("reference_chart_key"),
        row.get("source_ref"),
        row.get("review_no"),
    ]
    return " ".join(str(item) for item in parts if item)


def _domain_tags(row: dict[str, Any]) -> list[str]:
    tags = ["review_case", "fault_ratio"]
    text = _normalized_text(row)
    keyword_tags = {
        "intersection": ("교차로", "사거리", "신호"),
        "lane_change": ("차선", "진로변경", "차로"),
        "rear_end": ("추돌", "급정거"),
        "blackbox": ("블랙박스", "영상"),
        "pedestrian": ("보행자", "횡단보도"),
    }
    for tag, keywords in keyword_tags.items():
        if any(keyword in text for keyword in keywords):
            tags.append(tag)
    return sorted(set(tags))


def _read_jsonl(path: Path, *, limit: int = 0):
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, start=1):
            if limit and line_no > limit:
                break
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise CommandError(f"Invalid JSON in {path}:{line_no}: {exc}") from exc


def _required(row: dict[str, Any], key: str) -> Any:
    value = row.get(key)
    if value in {None, ""}:
        raise CommandError(f"Missing required review_case RAG field: {key}")
    return value


def _text_result(result: dict[str, Any]) -> str:
    smoke = result.get("smoke") or {}
    lines = [
        f"Review case RAG chunks: {result['status']}",
        f"- source_documents: {result['counts']['source_documents']}",
        f"- rag_chunks: {result['counts']['rag_chunks']}",
        f"- loaded_chunks: {result['loaded']['rag_chunks']}",
    ]
    if smoke:
        lines.extend(
            [
                f"- smoke_backend: {smoke.get('backend')}",
                f"- smoke_status: {smoke.get('status')}",
                f"- smoke_results: {len(smoke.get('results') or [])}",
            ]
        )
    return "\n".join(lines)
