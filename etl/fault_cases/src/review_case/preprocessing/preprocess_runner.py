from __future__ import annotations

import argparse
from pathlib import Path

from ..config import PipelineConfig
from ..paths import (
    case_json_dir,
    chunks_path,
    documents_path,
    ensure_preprocessing_dirs,
    loader_report_path,
    page_coverage_path,
    preprocessing_summary_path,
    quality_report_path,
    raw_pdf_dir,
    source_chunks_path,
    toc_case_links_path,
    toc_items_path,
)
from .builder import build_documents
from .case_splitter import split_cases
from .chunker import build_review_case_chunks, build_source_chunks
from .io_utils import write_json, write_jsonl
from .pdf_loader import load_pdf_pages
from .quality_validator import build_summary, validate_document
from .toc_parser import link_toc_items, parse_toc_items


def resolve_pdf_path(config: PipelineConfig, explicit_path: str | None = None) -> Path:
    if explicit_path:
        return Path(explicit_path).expanduser()
    return raw_pdf_dir(config.output_root) / config.review_case_pdf_name


def parse_args() -> tuple[PipelineConfig, str | None]:
    defaults = PipelineConfig()
    parser = argparse.ArgumentParser(description="심의사례 PDF 전처리")
    parser.add_argument("--pdf-path", default=None)
    parser.add_argument("--output-root", default=str(defaults.output_root))
    parser.add_argument("--review-case-pdf-name", default=defaults.review_case_pdf_name)
    parser.add_argument("--chunk-size", type=int, default=defaults.chunk_size)
    parser.add_argument("--chunk-overlap", type=int, default=defaults.chunk_overlap)
    parser.add_argument("--source-chunk-size", type=int, default=defaults.source_chunk_size)
    parser.add_argument("--source-chunk-overlap", type=int, default=defaults.source_chunk_overlap)
    parser.add_argument("--toc-max-pages", type=int, default=defaults.toc_max_pages)
    parser.add_argument("--skip-source-chunks", action="store_true")
    parser.add_argument("--write-case-json-files", action="store_true")
    args = parser.parse_args()
    config = PipelineConfig(
        output_root=Path(args.output_root).expanduser(),
        review_case_pdf_name=args.review_case_pdf_name,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        source_chunk_size=args.source_chunk_size,
        source_chunk_overlap=args.source_chunk_overlap,
        toc_max_pages=args.toc_max_pages,
        write_source_chunks=not args.skip_source_chunks,
        write_case_json_files=args.write_case_json_files,
    )
    return config, args.pdf_path


def build_page_coverage(pages: list[object], documents: list[object]) -> dict[str, object]:
    covered_pages = set()
    for doc in documents:
        start = getattr(doc, "pdf_page_start", None)
        end = getattr(doc, "pdf_page_end", None)
        if start and end:
            covered_pages.update(range(start, end + 1))
    return {
        "page_count": len(pages),
        "covered_page_count": len(covered_pages),
        "uncovered_pages": [page.page_no for page in pages if page.page_no not in covered_pages],
    }


def run_preprocess(config: PipelineConfig, pdf_path: Path) -> dict[str, object]:
    ensure_preprocessing_dirs(config.output_root, include_case_json=config.write_case_json_files)

    pages, loader_report = load_pdf_pages(pdf_path)
    toc_items = parse_toc_items(pages, config.source_type, max_pages=config.toc_max_pages)
    case_texts = split_cases(pages)
    source_chunks = (
        build_source_chunks(
            case_texts,
            config.source_type,
            config.source_reliability_score,
            config.source_chunk_size,
            config.source_chunk_overlap,
        )
        if config.write_source_chunks
        else []
    )
    documents = build_documents(case_texts, config, toc_items)

    all_chunks = []
    quality_rows = []
    for doc in documents:
        doc_chunks = build_review_case_chunks(doc)
        quality_rows.append(validate_document(doc, doc_chunks, config))
        all_chunks.extend(doc_chunks)

    toc_links = link_toc_items(documents, toc_items)
    summary = build_summary(documents, source_chunks, all_chunks, quality_rows, len(toc_items), len(toc_links))
    summary["pdf_path"] = str(pdf_path)
    summary["page_count"] = len(pages)
    summary["case_text_count"] = len(case_texts)

    write_jsonl(documents_path(config.output_root), documents)
    write_jsonl(source_chunks_path(config.output_root), source_chunks)
    write_jsonl(chunks_path(config.output_root), all_chunks)
    write_jsonl(quality_report_path(config.output_root), quality_rows)
    write_jsonl(toc_items_path(config.output_root), toc_items)
    write_jsonl(toc_case_links_path(config.output_root), toc_links)
    write_json(loader_report_path(config.output_root), loader_report)
    write_json(page_coverage_path(config.output_root), build_page_coverage(pages, documents))
    write_json(preprocessing_summary_path(config.output_root), summary)

    if config.write_case_json_files:
        for doc in documents:
            write_json(case_json_dir(config.output_root) / f"{doc.review_case_id}.json", doc)

    return summary


def main() -> None:
    config, explicit_pdf_path = parse_args()
    summary = run_preprocess(config, resolve_pdf_path(config, explicit_pdf_path))
    print("[review_case preprocess] done")
    print(f"documents={summary['document_count']}")
    print(f"chunks={summary['chunk_count']}")
    print(f"fatal_flags={summary['fatal_flag_counts']}")


if __name__ == "__main__":
    main()
