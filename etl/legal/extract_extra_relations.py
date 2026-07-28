"""Build semantic LawChunk relations for the Neo4j Law Graph.

The ingestion validator owns structural relations such as HAS_ARTICLE. This
module adds text-derived relations that law_ground_search can traverse after
vector retrieval: HAS_PENALTY, HAS_APPENDIX, HAS_EXCEPTION, and RELATED_TO.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


DEFAULT_CHUNKS_PATH = Path("output/law_ingestion/chunks/law_chunks.jsonl")
DEFAULT_OUTPUT_PATH = Path("output/law_ingestion/relations/law_extra_relations.jsonl")

PENALTY_KEYWORDS = ("벌금", "과태료", "징역", "처한다", "부과한다", "범칙금")
EXCEPTION_KEYWORDS = ("예외", "제외", "적용하지 아니", "그러하지 아니하다", "다만", "면제", "감경")

STANDARD_ARTICLE_RE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
INTERNAL_ARTICLE_RE = re.compile(r"제\s*(\d+)\s*의\s*(\d+)\s*조")
APPENDIX_RE = re.compile(r"별표\s*(\d+(?:\s*의\s*\d+)?)")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    chunks_path = Path(args.chunks_path)
    output_path = Path(args.output_path)

    if not chunks_path.exists():
        print(f"Law chunks file not found: {chunks_path}")
        return 1

    chunks = list(read_jsonl(chunks_path))
    relations = build_extra_relations(chunks)
    write_jsonl(output_path, relations)

    counts = Counter(row["relation_type"] for row in relations)
    print(
        "Extra law relations generated: "
        f"HAS_PENALTY={counts.get('HAS_PENALTY', 0)}, "
        f"HAS_APPENDIX={counts.get('HAS_APPENDIX', 0)}, "
        f"HAS_EXCEPTION={counts.get('HAS_EXCEPTION', 0)}, "
        f"RELATED_TO={counts.get('RELATED_TO', 0)}"
    )
    print(f"File saved to {output_path}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks-path", default=str(DEFAULT_CHUNKS_PATH))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    return parser.parse_args(argv)


def build_extra_relations(
    chunks: Iterable[dict],
    *,
    created_at: str | None = None,
) -> list[dict]:
    chunk_rows = [chunk for chunk in chunks if chunk.get("chunk_id") and chunk.get("source_version_id")]
    article_map, appendix_map = build_chunk_indexes(chunk_rows)

    relations: dict[str, dict] = {}
    relation_created_at = created_at or datetime.now(timezone.utc).isoformat()

    for chunk in chunk_rows:
        current_chunk_id = chunk["chunk_id"]
        source_version_id = chunk["source_version_id"]
        text = str(chunk.get("provision_text") or "")
        if not text:
            continue

        article_refs = extract_article_refs(text)
        appendix_refs = extract_appendix_refs(text)

        if any(keyword in text for keyword in PENALTY_KEYWORDS):
            for target_id in resolve_refs(article_map, source_version_id, article_refs):
                add_relation(
                    relations,
                    relation_type="HAS_PENALTY",
                    from_chunk_id=target_id,
                    to_chunk_id=current_chunk_id,
                    confidence=0.9,
                    evidence_text="Text-derived penalty reference",
                    created_at=relation_created_at,
                )

        if any(keyword in text for keyword in EXCEPTION_KEYWORDS):
            for target_id in resolve_refs(article_map, source_version_id, article_refs):
                add_relation(
                    relations,
                    relation_type="HAS_EXCEPTION",
                    from_chunk_id=target_id,
                    to_chunk_id=current_chunk_id,
                    confidence=0.75,
                    evidence_text="Text-derived exception reference",
                    created_at=relation_created_at,
                )

        for target_id in resolve_refs(article_map, source_version_id, article_refs):
            add_relation(
                relations,
                relation_type="RELATED_TO",
                from_chunk_id=current_chunk_id,
                to_chunk_id=target_id,
                confidence=0.6,
                evidence_text="Text-derived article reference",
                created_at=relation_created_at,
            )

        for target_id in resolve_refs(appendix_map, source_version_id, appendix_refs):
            add_relation(
                relations,
                relation_type="HAS_APPENDIX",
                from_chunk_id=current_chunk_id,
                to_chunk_id=target_id,
                confidence=0.9,
                evidence_text="Text-derived appendix reference",
                created_at=relation_created_at,
            )

    return sorted(relations.values(), key=lambda row: row["relation_id"])


def build_chunk_indexes(chunks: Iterable[dict]) -> tuple[dict[tuple[str, str], list[str]], dict[tuple[str, str], list[str]]]:
    article_map: dict[tuple[str, str], list[str]] = defaultdict(list)
    appendix_map: dict[tuple[str, str], list[str]] = defaultdict(list)

    for chunk in chunks:
        source_version_id = chunk["source_version_id"]
        chunk_id = chunk["chunk_id"]
        article_no = normalize_article_no(chunk.get("article_no"))
        appendix_no = normalize_appendix_no(chunk.get("appendix_no"))

        if article_no:
            article_map[(source_version_id, article_no)].append(chunk_id)
        if appendix_no:
            appendix_map[(source_version_id, appendix_no)].append(chunk_id)

    return article_map, appendix_map


def extract_article_refs(text: str) -> set[str]:
    refs = set()
    for number, branch in STANDARD_ARTICLE_RE.findall(text):
        refs.add(normalize_article_no(f"제{number}조의{branch}" if branch else f"제{number}조"))
    for number, branch in INTERNAL_ARTICLE_RE.findall(text):
        refs.add(normalize_article_no(f"제{number}의{branch}조"))
    refs.discard("")
    return refs


def extract_appendix_refs(text: str) -> set[str]:
    refs = {normalize_appendix_no(f"별표{value}") for value in APPENDIX_RE.findall(text)}
    refs.discard("")
    return refs


def resolve_refs(index: dict[tuple[str, str], list[str]], source_version_id: str, refs: set[str]) -> list[str]:
    target_ids = []
    for ref in refs:
        target_ids.extend(index.get((source_version_id, ref), []))
    return target_ids


def add_relation(
    relations: dict[str, dict],
    *,
    relation_type: str,
    from_chunk_id: str,
    to_chunk_id: str,
    confidence: float,
    evidence_text: str,
    created_at: str,
) -> None:
    if not from_chunk_id or not to_chunk_id or from_chunk_id == to_chunk_id:
        return
    relation_id = f"rel:{relation_type}:{from_chunk_id}:{to_chunk_id}"
    relations[relation_id] = {
        "relation_id": relation_id,
        "relation_type": relation_type,
        "from_chunk_id": from_chunk_id,
        "to_chunk_id": to_chunk_id,
        "confidence": confidence,
        "evidence_text": evidence_text,
        "created_at": created_at,
    }


def normalize_article_no(value: object) -> str:
    text = re.sub(r"\s+", "", str(value or ""))
    if not text:
        return ""
    match = re.fullmatch(r"제(\d+)조(?:의(\d+))?", text)
    if match:
        number, branch = match.group(1), match.group(2)
        return f"제{number}의{branch}조" if branch else f"제{number}조"
    match = re.fullmatch(r"제(\d+)의(\d+)조", text)
    if match:
        return f"제{match.group(1)}의{match.group(2)}조"
    return text


def normalize_appendix_no(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def read_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
