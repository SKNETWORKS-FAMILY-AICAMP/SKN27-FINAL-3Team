"""Load a tiny legal RAG fixture into Django fallback RAG tables."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from app.services.legal_rag_service import search_legal_rag
from chatbot.models import RagChunk, SourceDocument


DEFAULT_FIXTURE_PATH = Path("storage/rag/legal_rag_smoke_chunks.jsonl")


class Command(BaseCommand):
    help = "Load local legal RAG smoke chunks into source_documents/rag_chunks and run an optional query."

    def add_arguments(self, parser):
        parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE_PATH), help="Path to legal RAG smoke JSONL.")
        parser.add_argument("--replace", action="store_true", help="Delete existing smoke fixture chunks before loading.")
        parser.add_argument("--smoke-query", default="", help="Optional query to run after loading.")
        parser.add_argument("--top-k", type=int, default=3, help="Top K for the optional smoke query.")
        parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    def handle(self, *args, **options):
        fixture_path = Path(options["fixture"])
        if not fixture_path.exists():
            raise CommandError(f"Legal RAG smoke fixture not found: {fixture_path}")

        rows = list(_read_jsonl(fixture_path))
        if not rows:
            raise CommandError(f"Legal RAG smoke fixture is empty: {fixture_path}")

        with transaction.atomic():
            if options["replace"]:
                chunk_ids = [_required(row, "chunk_id") for row in rows]
                RagChunk.objects.filter(chunk_id__in=chunk_ids).delete()
            loaded = _load_rows(rows)

        smoke = None
        if str(options["smoke_query"] or "").strip():
            smoke = search_legal_rag(str(options["smoke_query"]), top_k=max(1, int(options["top_k"] or 3)))

        result = {
            "contract_version": "legal_rag_smoke_fixture.v1",
            "status": "loaded",
            "fixture": str(fixture_path),
            "loaded": loaded,
            "counts": {
                "source_documents": SourceDocument.objects.filter(metadata__smoke_fixture=True).count(),
                "rag_chunks": RagChunk.objects.filter(metadata__smoke_fixture=True).count(),
            },
            "smoke": smoke,
        }
        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(_text_result(result))


def _load_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    source_ids = set()
    chunk_count = 0
    for row in rows:
        source_document_id = _required(row, "source_document_id")
        source_ids.add(source_document_id)
        source, _source_created = SourceDocument.objects.update_or_create(
            source_document_id=source_document_id,
            defaults={
                "source_type": str(row.get("source_type") or "law"),
                "source_name": _required(row, "source_name"),
                "source_url": str(row.get("source_url") or ""),
                "effective_date": date.fromisoformat(_required(row, "effective_date")),
                "status": "active",
                "metadata": {"smoke_fixture": True, "source": "legal_rag_smoke_fixture"},
            },
        )
        RagChunk.objects.update_or_create(
            chunk_id=_required(row, "chunk_id"),
            defaults={
                "source_document": source,
                "source_id": str(row.get("source_id") or source_document_id),
                "source_type": str(row.get("source_type") or "law"),
                "chunk_type": str(row.get("chunk_type") or "article"),
                "title": str(row.get("title") or ""),
                "article_no": str(row.get("article_no") or ""),
                "content": _required(row, "content"),
                "normalized_text": str(row.get("normalized_text") or row.get("content") or ""),
                "is_searchable": bool(row.get("is_searchable", True)),
                "domain_tags": list(row.get("domain_tags") or []),
                "metadata": {"smoke_fixture": True, "source": "legal_rag_smoke_fixture"},
            },
        )
        chunk_count += 1
    return {"source_documents": len(source_ids), "rag_chunks": chunk_count}


def _read_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise CommandError(f"Invalid JSON in {path}:{line_no}: {exc}") from exc


def _required(row: dict[str, Any], key: str) -> Any:
    value = row.get(key)
    if value in {None, ""}:
        raise CommandError(f"Missing required legal RAG smoke field: {key}")
    return value


def _text_result(result: dict[str, Any]) -> str:
    smoke = result.get("smoke") or {}
    lines = [
        f"Legal RAG smoke fixture: {result['status']}",
        f"- source_documents: {result['counts']['source_documents']}",
        f"- rag_chunks: {result['counts']['rag_chunks']}",
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
