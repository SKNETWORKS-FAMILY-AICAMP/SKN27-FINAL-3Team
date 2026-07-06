from __future__ import annotations

import re
from dataclasses import dataclass

from .chunk_config import DEFAULT_CHUNK_CONFIG, ChunkConfig


@dataclass(frozen=True)
class TextChunk:
    chunk_type: str
    text: str
    source_fields: list[str]


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def join_labeled_parts(parts: list[tuple[str, str | None]]) -> str:
    lines = []
    for label, value in parts:
        value = normalize_text(value)
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines).strip()


def split_long_text(
    text: str,
    chunk_type: str,
    source_fields: list[str],
    config: ChunkConfig = DEFAULT_CHUNK_CONFIG,
) -> list[TextChunk]:
    text = normalize_text(text)
    if not text:
        return []
    if len(text) <= config.chunk_size_chars:
        return [TextChunk(chunk_type=chunk_type, text=text, source_fields=source_fields)]

    chunks: list[TextChunk] = []
    start = 0
    while start < len(text):
        end = min(start + config.chunk_size_chars, len(text))
        window = text[start:end]

        if end < len(text):
            break_at = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("다. "))
            min_break = int(config.chunk_size_chars * 0.55)
            if break_at >= min_break:
                end = start + break_at + 1
                window = text[start:end]

        chunks.append(TextChunk(chunk_type=chunk_type, text=window.strip(), source_fields=source_fields))
        if end >= len(text):
            break
        start = max(end - config.chunk_overlap_chars, start + 1)

    return chunks
